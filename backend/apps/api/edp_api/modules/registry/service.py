"""registry 服务：组合键 upsert（乐观锁）/ 点查 / 组合键游标查询 / 历史轨迹。

并发正确性（7.4）：
- 更新路径的 UPDATE 语句带 ``WHERE revision = :expected``（expected = 请求
  携带的 expected_revision，未携带则为读到的当前版本）——affected_rows = 0
  即并发丢更新，重查现值后以 409 CONFLICT + current_revision 返回；
- 创建路径并发竞争（uq_bo_natural_key 唯一索引冲突）→ 回滚、重新绑定租户、
  重查胜者版本 → 同样 409 + current_revision。

租户隔离：会话由 tenant_scoped 预先 bind_tenant（FORCE RLS），显式
tenant_id 条件与 RLS 双保险；跨租户读取恒表现为"不存在"。

事务边界：本层只 flush 不 commit——请求级提交由 core.db.get_db 统一执行，
outbox 与对象变更同事务（事务性发件箱；outbox 写入口/查询归 events 模块
service.append_outbox / outbox_for_aggregate，模块间仅 import service）。
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import bind_tenant
from edp_api.core.errors import EdpError
from edp_api.core.pagination import Page, decode_cursor, encode_cursor
from edp_api.core.security.principal import Principal
from edp_api.modules.audit import service as audit_service
from edp_api.modules.events import service as events_service
from edp_api.modules.registry.models import BusinessObject
from edp_api.modules.registry.schemas import (
    HistoryEntry,
    ObjectResponse,
    ObjectUpsertRequest,
)

AGGREGATE_TYPE_OBJECT = "OBJECT"
EVENT_TYPE_OBJECT_UPSERT = "OBJECT_UPSERT"

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


async def _find_by_composite(
    sess: AsyncSession, tenant_id: UUID, req: ObjectUpsertRequest
) -> BusinessObject | None:
    """按自然键 (tenant, source_system, object_type, source_id) 查现有对象。

    RLS 已限本租户；显式 tenant_id 条件为无 RLS 环境（超级用户会话）下的
    双保险。
    """
    return (
        await sess.execute(
            select(BusinessObject).where(
                BusinessObject.tenant_id == tenant_id,
                BusinessObject.source_system == req.source_system,
                BusinessObject.object_type == req.object_type,
                BusinessObject.source_id == req.source_id,
            )
        )
    ).scalar_one_or_none()


def _conflict(current_revision: int | None) -> EdpError:
    return EdpError.conflict(
        "revision 乐观锁冲突",
        extra={"current_revision": current_revision},
    )


async def _append_outbox(
    sess: AsyncSession, tenant_id: UUID, obj: BusinessObject, principal: Principal
) -> None:
    """同事务写 event.outbox（OBJECT_UPSERT 轨迹；payload 含 revision/actor）。
    写入口收敛至 events.service.append_outbox。"""
    await events_service.append_outbox(
        sess,
        tenant_id=tenant_id,
        aggregate_type=AGGREGATE_TYPE_OBJECT,
        aggregate_id=obj.object_id,
        event_type=EVENT_TYPE_OBJECT_UPSERT,
        payload={
            "revision": obj.revision,
            "source_system": obj.source_system,
            "source_id": obj.source_id,
            "object_type": obj.object_type,
            "actor": principal.id,
        },
        actor=principal.id,
    )


async def upsert_object(
    sess: AsyncSession, principal: Principal, req: ObjectUpsertRequest
) -> tuple[BusinessObject, bool]:
    """组合键 upsert：不存在 → INSERT revision=1；存在 → 乐观锁更新。

    Returns:
        (对象, created)；更新路径对象已 refresh 至最新行值。

    Raises:
        EdpError(CONFLICT, extra={"current_revision": n}): expected_revision
        与当前不符、并发 UPDATE 抢先（affected_rows=0）或并发首插唯一键冲突。
    """
    tenant_id = principal.tenant_id
    current = await _find_by_composite(sess, tenant_id, req)

    if current is None:
        obj = BusinessObject(
            object_id=uuid4(),
            tenant_id=tenant_id,
            object_type=req.object_type,
            owner_domain=req.owner_domain,
            source_system=req.source_system,
            source_id=req.source_id,
            revision=1,
            status="ACTIVE",
            attributes=req.attributes,
            created_by=principal.id,
            updated_by=principal.id,
        )
        sess.add(obj)
        try:
            await sess.flush()
        except IntegrityError:
            # 并发首插竞争：唯一索引胜者已提交——回滚后重绑租户（事务级
            # set_config 已随回滚失效）重查胜者版本 → 409
            await sess.rollback()
            await bind_tenant(sess, tenant_id)
            winner = await _find_by_composite(sess, tenant_id, req)
            raise _conflict(winner.revision if winner else None) from None
        await sess.refresh(obj)  # 载入 server 默认（created_at/updated_at）
        await _append_outbox(sess, tenant_id, obj, principal)
        return obj, True

    expected_req = req.idempotency.expected_revision
    if expected_req is not None and expected_req != current.revision:
        raise _conflict(current.revision)
    # 未携带 expected_revision 时用读到的版本兜底：并发丢更新可探测
    expected = expected_req if expected_req is not None else current.revision
    previous_revision = current.revision

    result = await sess.execute(
        update(BusinessObject)
        .where(
            BusinessObject.object_id == current.object_id,
            BusinessObject.revision == expected,
        )
        .values(
            attributes=req.attributes,
            revision=current.revision + 1,
            updated_by=principal.id,
            updated_at=func.now(),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        fresh = await _find_by_composite(sess, tenant_id, req)
        raise _conflict(fresh.revision if fresh else None)
    await sess.refresh(current)
    # SQL UPDATE 不经 ORM 状态（切面不可见）——显式补审计（模块间仅 service）：
    # before 取 update 前内存值（previous_revision），after 取 refresh 后行值
    await audit_service.record_explicit(
        sess,
        action="OBJECT_UPDATE",
        resource_type="business_objects",
        resource_id=str(current.object_id),
        detail={
            "before": {"revision": previous_revision},
            "after": {"revision": current.revision},
            "changed": ["revision"],
            "source_system": current.source_system,
            "source_id": current.source_id,
        },
        principal=principal,
    )
    await _append_outbox(sess, tenant_id, current, principal)
    return current, False


async def get_object(sess: AsyncSession, object_id: UUID) -> BusinessObject | None:
    """按 object_id 点查；RLS 下跨租户 = 不存在（None）。"""
    return await sess.get(BusinessObject, object_id)


async def object_exists(sess: AsyncSession, object_id: UUID) -> bool:
    """object_id 存在性（events 批量入库的对象校验入口——模块间仅 service，
    events 经本函数读 master.business_objects；RLS 下跨租户/不存在同义）。"""
    return await sess.get(BusinessObject, object_id) is not None


async def query_objects(
    sess: AsyncSession,
    *,
    object_type: str | None = None,
    source_system: str | None = None,
    source_id: str | None = None,
    owner_domain: str | None = None,
    status: str | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[ObjectResponse]:
    """组合键/类型/域/状态过滤 + 游标分页（updated_at DESC, object_id DESC
    tiebreak）；cursor 用 core.pagination 编解码，非法 cursor 视为首页。"""
    limit = max(1, min(limit, MAX_LIMIT))
    stmt = select(BusinessObject)
    if object_type:
        stmt = stmt.where(BusinessObject.object_type == object_type)
    if source_system:
        stmt = stmt.where(BusinessObject.source_system == source_system)
    if source_id:
        stmt = stmt.where(BusinessObject.source_id == source_id)
    if owner_domain:
        stmt = stmt.where(BusinessObject.owner_domain == owner_domain)
    if status:
        stmt = stmt.where(BusinessObject.status == status)

    decoded = decode_cursor(cursor)
    if decoded is not None:
        anchor = _parse_anchor(decoded)
        if anchor is not None:
            updated_at, object_id_anchor = anchor
            stmt = stmt.where(
                or_(
                    BusinessObject.updated_at < updated_at,
                    and_(
                        BusinessObject.updated_at == updated_at,
                        BusinessObject.object_id < object_id_anchor,
                    ),
                )
            )

    stmt = stmt.order_by(
        BusinessObject.updated_at.desc(), BusinessObject.object_id.desc()
    ).limit(limit + 1)
    rows = (await sess.execute(stmt)).scalars().all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"u": last.updated_at.isoformat(), "i": str(last.object_id)}
        )
    return Page(
        items=[ObjectResponse.model_validate(row) for row in page_rows],
        next_cursor=next_cursor,
    )


def _parse_anchor(decoded: dict) -> tuple[datetime, UUID] | None:
    """cursor 载荷 → (updated_at, object_id)；缺字段/格式非法 → None。"""
    try:
        return datetime.fromisoformat(str(decoded["u"])), UUID(str(decoded["i"]))
    except (KeyError, TypeError, ValueError):
        return None


async def object_history(
    sess: AsyncSession, object_id: UUID
) -> list[HistoryEntry]:
    """对象 revision 变更轨迹：event.outbox 聚合 OBJECT 记录按 outbox_id 升序。

    W1 数据源为 outbox（唯一携带 actor/revision 的同事务记录；查询经
    events.service.outbox_for_aggregate）；W2 切换为审计日志聚合（B.2 语义不变）。
    """
    rows = await events_service.outbox_for_aggregate(
        sess, AGGREGATE_TYPE_OBJECT, object_id
    )
    return [
        HistoryEntry(
            revision=entry.payload.get("revision"),
            action=entry.event_type,
            actor_id=entry.payload.get("actor"),
            occurred_at=entry.created_at,
        )
        for entry in rows
    ]
