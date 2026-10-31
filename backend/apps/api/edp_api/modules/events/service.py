"""events 服务：批量入库（三层幂等）/ outbox 读写入口 / 游标查询 / 点查。

幂等三层（设计文档 7.1）：
1. 接口层——platform.idempotency_keys (tenant, key, endpoint) 命中且未过期
   → 直接反序列化存档响应并置 deduplicated=True，不重算（复合 PK
   (tenant_id, key)＝迁移 0007：幂等键按租户命名空间隔离，跨租户同
   Key 字符串互不冲突、互不可见）；存档表归 platform 模块——读写经
   platform.service.load/store_idempotent_response（模块间仅 service）；
2. 适配器层——event_id = derive_event_id(tenant_ns, source_system|source_id|
   occurred_at|event_type)（uuidv5.py；B.3 批次事件不携带源记录 source_id，
   派生时以 str(object_id) 充当该槽位：同一对象+类型+时刻的重放恒派生相同
   event_id）；
3. 数据层——INSERT ... ON CONFLICT DO NOTHING（无目标子句，同时覆盖
   event_id 主键与 uq_events_idem 部分唯一索引），rowcount=0 计 duplicated，
   天然 0 重复行。

event.idempotency_key 列存 "{批次键}:{批次内下标}"：批次内逐行唯一（满足
uq_events_idem (tenant_id, idempotency_key) 逐行唯一语义），且同批次重放
恒定——存档过期后的重放仍靠 event_id 收敛为 duplicated。

存档策略：rejected>0（部分失败）不写幂等存档——修复后可整批重试；
accepted+duplicated==len 且 rejected==0 才存档（TTL=设置项 idempotency_ttl）。

RLS：会话由 tenant_scoped 预 bind_tenant（FORCE RLS）——object_id 存在性
校验（经 registry.service.object_exists）、幂等表读写（经 platform.service）、
事件写入全部天然限本租户（跨租户 object_id 与不存在同义 → rejected）。

事务边界：本层只 flush 不 commit（请求级提交归 core.db.get_db）；accepted
事件同事务写 event.outbox（事务性发件箱；event_type 用原事件类型，状态
流转归 T13 worker——认领/记果经本模块 claim_pending_outbox /
record_outbox_result，worker 不直连表）。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from typing import Literal
from uuid import UUID

from sqlalchemy import Text, Uuid, and_, column, func, or_, select, table, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.config import get_settings
from edp_api.core.errors import EdpError
from edp_api.core.pagination import Page, decode_cursor, encode_cursor
from edp_api.core.security.principal import Principal
from edp_api.modules.audit import service as audit_service
from edp_api.modules.events.models import Event, Outbox
from edp_api.modules.events.schemas import (
    BatchResponse,
    EventBatchError,
    EventIn,
    EventResponse,
)
from edp_api.modules.events.uuidv5 import derive_event_id, normalize_occurred_at
from edp_api.modules.evidence import service as evidence_service
from edp_api.modules.evidence.schemas import EvidenceCreateRequest, EvidenceLinkIn
from edp_api.modules.platform import service as platform_service
from edp_api.modules.registry import service as registry_service
from edp_api.modules.tenantmgmt import service as tenantmgmt_service

INGEST_ENDPOINT = "/events/batch"
AGGREGATE_TYPE_EVENT = "EVENT"

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

# 跨模块表参与 join：master.business_objects 归 registry 模块（模块间仅可
# import 对方 service，ORM 不可直接引用）——以核心表构造参与 ORM 主查询
# （口径同 tools/ingest 的跨模块纯 SQL 读）；RLS 会话已 bind，跨租户行不可见。
_BUSINESS_OBJECTS = table(
    "business_objects",
    column("object_id", Uuid),
    column("source_id", Text),
    schema="master",
)

# outbox.status → 契约分发状态（spec §6.2）；无 outbox 行/未知状态 → None
_DELIVERY_STATUS = {
    "PUBLISHED": "DELIVERED",
    "PENDING": "PENDING",
    "FAILED": "DEAD_LETTER",
}


# ---- outbox 写入口（registry 与 events 共用） ----


async def append_outbox(
    sess: AsyncSession,
    tenant_id: UUID,
    aggregate_type: str,
    aggregate_id: UUID,
    event_type: str,
    payload: dict,
    actor: str,
) -> Outbox:
    """outbox 唯一写入口（事务性发件箱）：同事务 flush 一条 PENDING 记录。

    registry（OBJECT_UPSERT 轨迹）与 events（事件入库）共用；payload 需
    JSONB 可序列化（datetime 请先 isoformat）。
    """
    entry = Outbox(
        tenant_id=tenant_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload=payload,
        created_by=actor,
        updated_by=actor,
    )
    sess.add(entry)
    await sess.flush()
    return entry


async def outbox_for_aggregate(
    sess: AsyncSession, aggregate_type: str, aggregate_id: UUID
) -> Sequence[Outbox]:
    """按聚合查询 outbox 轨迹（outbox_id 升序）——registry history 数据源。"""
    return (
        (
            await sess.execute(
                select(Outbox)
                .where(
                    Outbox.aggregate_type == aggregate_type,
                    Outbox.aggregate_id == aggregate_id,
                )
                .order_by(Outbox.outbox_id)
            )
        )
        .scalars()
        .all()
    )


# ---- outbox 分发读口（worker 专用；模块间仅 service，worker 不直连表） ----


@dataclass(slots=True)
class ClaimedOutbox:
    """claim_pending_outbox 认领行（worker 构造 OutboxMessage 的投影）。"""

    outbox_id: int
    tenant_id: UUID
    aggregate_type: str
    aggregate_id: UUID
    event_type: str
    payload: dict
    retry_count: int


_CLAIM_SQL = text(
    "SELECT outbox_id, tenant_id, aggregate_type, aggregate_id, event_type,"
    " payload, retry_count"
    " FROM event.outbox"
    " WHERE tenant_id = :tenant_id AND status = 'PENDING'"
    " AND available_at <= now()"
    " ORDER BY outbox_id"
    " LIMIT :limit"
    " FOR UPDATE SKIP LOCKED"
)

_PUBLISH_RESULT_SQL = text(
    "UPDATE event.outbox"
    " SET status = 'PUBLISHED', published_at = now(), updated_at = now()"
    " WHERE outbox_id = :outbox_id"
)

# retry_count+1、退避与 FAILED 升级同语句原子落库；UPDATE 右值表达式均引用
# 旧行值（retry_count = 认领时的值；now() = 事务开始时刻）
_RETRY_RESULT_SQL = text(
    "UPDATE event.outbox"
    " SET retry_count = retry_count + 1,"
    " status = CASE WHEN retry_count + 1 >= :max_retries THEN 'FAILED'"
    "  ELSE status END,"
    " available_at = now() + make_interval(secs => power(2, retry_count + 1)"
    " * :base_s),"
    " updated_at = now()"
    " WHERE outbox_id = :outbox_id"
    " RETURNING status"
)


async def claim_pending_outbox(
    sess: AsyncSession, tenant_id: UUID, batch_size: int
) -> list[ClaimedOutbox]:
    """认领待分发 outbox 行：FOR UPDATE SKIP LOCKED——多 worker 副本并发
    同租户天然不双发（行锁互斥，锁内行被跳过）。

    RLS：event.outbox FORCE RLS——调用方（worker）需已 bind_tenant；显式
    tenant_id 条件双保险。行锁随调用方事务提交/回滚释放。
    """
    rows = (
        await sess.execute(_CLAIM_SQL, {"tenant_id": tenant_id, "limit": batch_size})
    ).mappings().all()
    return [ClaimedOutbox(**dict(row)) for row in rows]


async def record_outbox_result(
    sess: AsyncSession,
    outbox_id: int,
    outcome: Literal["published", "retry", "failed"],
    backoff_base_s: float,
    max_retries: int,
) -> Literal["published", "retry", "failed"]:
    """记分发结果（与认领同事务）：

    - published → PUBLISHED + published_at；
    - retry/failed → retry_count+1、available_at = now() + 2^retry_count *
      backoff_base_s（指数退避），达 max_retries 自动转 FAILED（停止重投）。

    返回实际 outcome（retry 达阈值升级为 failed，调用方按返回值计数）。
    """
    if outcome == "published":
        await sess.execute(_PUBLISH_RESULT_SQL, {"outbox_id": outbox_id})
        return "published"
    status = (
        await sess.execute(
            _RETRY_RESULT_SQL,
            {
                "outbox_id": outbox_id,
                "max_retries": max_retries,
                "base_s": backoff_base_s,
            },
        )
    ).scalar_one()
    return "failed" if status == "FAILED" else "retry"


# ---- outbox 状态聚合（W5-05 收口：/admin/outbox/status 数据源） ----


@dataclass(slots=True)
class OutboxStatus:
    """outbox 聚合读数（裸 DB 值——ISO 串化归调用方响应层）。

    oldest_pending_age_seconds / last_published_at 无对应行 → None。
    """

    pending_count: int
    oldest_pending_age_seconds: int | None
    published_last_hour: int
    dlq_count: int
    last_published_at: datetime | None


_OUTBOX_STATUS_SQL = text(
    "SELECT"
    " count(*) FILTER (WHERE status = 'PENDING') AS pending_count,"
    " min(created_at) FILTER (WHERE status = 'PENDING') AS oldest_pending_at,"
    " now() AS taken_at,"
    " count(*) FILTER (WHERE status = 'PUBLISHED'"
    "   AND published_at >= now() - interval '1 hour') AS published_last_hour,"
    " count(*) FILTER (WHERE status = 'FAILED') AS dlq_count,"
    " max(published_at) AS last_published_at"
    " FROM event.outbox"
)


async def outbox_status(sess: AsyncSession) -> OutboxStatus:
    """outbox 状态单条聚合 SQL（RLS 会话已 bind_tenant → 天然限本租户）：
    pending 计数 / 最老 PENDING 积压龄（DB now() - min(created_at)，无
    PENDING → None）/ 近 1h PUBLISHED 计数 / DLQ=FAILED 计数（DLQ 语义
    同 _DELIVERY_STATUS：FAILED 即死信）/ 最近发布时刻。"""
    row = (await sess.execute(_OUTBOX_STATUS_SQL)).one()
    oldest_age = (
        int((row.taken_at - row.oldest_pending_at).total_seconds())
        if row.oldest_pending_at is not None
        else None
    )
    return OutboxStatus(
        pending_count=int(row.pending_count),
        oldest_pending_age_seconds=oldest_age,
        published_last_hour=int(row.published_last_hour),
        dlq_count=int(row.dlq_count),
        last_published_at=row.last_published_at,
    )


# ---- 批量入库 ----


async def ingest_batch(
    sess: AsyncSession,
    principal: Principal,
    idem_key: str,
    events: list[EventIn],
    *,
    internal: bool = False,
) -> BatchResponse:
    """批量入库（三层幂等；逐事件校验，不整批失败）。

    - 每条 accepted 事件以 perf_counter 计时写 ``ingest_latency_ms``；
    - ``risk_level`` 非空的能力结果事件同事务自动落结果证据
      （snapshot=ev.data、source_record_id=``result:{event_id}``、
      captured_at=occurred_at）+ ``RESULT`` link；duplicated 路径不建；
    - 批次末 upsert ``tenant_usage_daily``（events_in/events_duplicated）；
    - EDP-025 批量限额：事件数 > ``tenant_quotas.batch_max_events`` →
      400 VALIDATION_ERROR（不落库、不占幂等存档）；
    - ``internal=True``（W5-09）：内部来源写事件（quality 抽检
      checksum_failed / recheck 完成事件、evidence reindex 失配与完成
      事件——平台自身写入）**豁免 usage 计量 upsert**（内部写入不占
      租户用量口径；事件落库/证据/outbox/审计/幂等存档副作用不变）；
      外部调用方（/events/batch 路由、demo seed、适配器管道）不传——
      照常计量。

    Returns:
        {accepted, duplicated, rejected, deduplicated, errors?}——rejected 的
        事件附 ``errors:[{index, code=VALIDATION_ERROR, message}]``。
    """
    tenant_id = principal.tenant_id

    quota = await tenantmgmt_service.get_quota(sess, tenant_id)
    if len(events) > quota.batch_max_events:
        raise EdpError.validation_error(
            f"批量事件数 {len(events)} 超过租户上限 {quota.batch_max_events}"
        )

    archived_json = await platform_service.load_idempotent_response(
        sess, tenant_id, idem_key, INGEST_ENDPOINT
    )
    if archived_json is not None:
        data = dict(archived_json)
        data["deduplicated"] = True
        return BatchResponse.model_validate(data)

    accepted = duplicated = rejected = 0
    errors: list[EventBatchError] = []
    actor = principal.id

    for index, ev in enumerate(events):
        started = perf_counter()
        event_id = derive_event_id(
            tenant_id, ev.source_system, str(ev.object_id), ev.occurred_at, ev.event_type
        )
        if not await registry_service.object_exists(sess, ev.object_id):
            rejected += 1
            errors.append(
                EventBatchError(
                    index=index, message=f"object_id 不存在：{ev.object_id}"
                )
            )
            continue

        occurred_at = normalize_occurred_at(ev.occurred_at)
        latency_ms = int((perf_counter() - started) * 1000)
        stmt = (
            pg_insert(Event)
            .values(
                event_id=event_id,
                tenant_id=tenant_id,
                event_type=ev.event_type,
                object_id=ev.object_id,
                source_system=ev.source_system,
                occurred_at=occurred_at,
                actor_type=ev.actor_type,
                actor_id=ev.actor_id,
                result_type=ev.result_type,
                risk_level=ev.risk_level,
                score=ev.score,
                data=ev.data,
                idempotency_key=f"{idem_key}:{index}",
                ingest_latency_ms=latency_ms,
                created_by=actor,
                updated_by=actor,
            )
            .on_conflict_do_nothing()
        )
        result = await sess.execute(stmt)
        if result.rowcount == 0:
            duplicated += 1
            continue

        accepted += 1
        if ev.risk_level is not None:
            # 结果证据（spec §5.1）：能力结果事件（risk_level 非空）同事务
            # 落证据 + RESULT link；duplicated 路径在 continue 前不达此处
            await evidence_service.create_record(
                sess,
                principal,
                EvidenceCreateRequest(
                    source_system=ev.source_system,
                    source_record_id=f"result:{event_id}",
                    object_id=ev.object_id,
                    event_id=event_id,
                    snapshot=ev.data,
                    captured_at=occurred_at,
                    links=[EvidenceLinkIn(ref_type="RESULT", ref_id=event_id)],
                ),
            )
        # pg_insert 不经 ORM 状态（切面不可见）——显式补审计（模块间仅 service）；
        # detail 在 flush 前以请求值构造完毕
        await audit_service.record_explicit(
            sess,
            action="EVENT_CREATE",
            resource_type="events",
            resource_id=str(event_id),
            detail={
                "event_type": ev.event_type,
                "object_id": str(ev.object_id),
                "source_system": ev.source_system,
                "occurred_at": normalize_occurred_at(ev.occurred_at).isoformat(),
                "idempotency_key": f"{idem_key}:{index}",
            },
            principal=principal,
        )
        await append_outbox(
            sess,
            tenant_id=tenant_id,
            aggregate_type=AGGREGATE_TYPE_EVENT,
            aggregate_id=event_id,
            event_type=ev.event_type,
            payload={
                "event_id": str(event_id),
                "event_type": ev.event_type,
                "object_id": str(ev.object_id),
                "occurred_at": normalize_occurred_at(ev.occurred_at).isoformat(),
                "risk_level": ev.risk_level,
                "source_system": ev.source_system,
            },
            actor=actor,
        )

    # 计量（spec §5.1）：与事件行同事务累加（批次回滚则计数一并回滚）；
    # internal=True 豁免（W5-09——内部来源写事件不占租户用量口径）
    if not internal:
        await tenantmgmt_service.bump_usage_daily(
            sess, tenant_id, events_in=accepted, events_duplicated=duplicated
        )

    response = BatchResponse(
        accepted=accepted,
        duplicated=duplicated,
        rejected=rejected,
        deduplicated=False,
        errors=errors or None,
    )
    if rejected == 0 and accepted + duplicated == len(events):
        await platform_service.store_idempotent_response(
            sess,
            tenant_id,
            idem_key,
            INGEST_ENDPOINT,
            response.model_dump(mode="json", exclude_none=True),
            ttl_s=get_settings().idempotency_ttl_seconds,
        )
    return response


# ---- 查询 ----


async def get_event(sess: AsyncSession, event_id: UUID) -> Event | None:
    """按 event_id 点查（裸 ORM 行；内部调用方用）；跨租户 = None。"""
    return await sess.get(Event, event_id)


def _event_query():
    """事件查询骨架（列表/详情共用同一响应组装路径）：outbox 左连派生
    ``delivery_status``、business_objects 左连派生 ``object_source_id``。"""
    return (
        select(Event, Outbox.status, _BUSINESS_OBJECTS.c.source_id)
        .select_from(Event)
        .outerjoin(
            Outbox,
            and_(
                Outbox.aggregate_type == AGGREGATE_TYPE_EVENT,
                Outbox.aggregate_id == Event.event_id,
                Outbox.tenant_id == Event.tenant_id,
            ),
        )
        .outerjoin(_BUSINESS_OBJECTS, _BUSINESS_OBJECTS.c.object_id == Event.object_id)
    )


async def get_event_response(
    sess: AsyncSession, event_id: UUID
) -> EventResponse | None:
    """按 event_id 点查响应（含派生字段，spec §6.2 列表 + 详情同口径）；
    RLS 下跨租户 = 不存在（None，不泄露存在性）。"""
    row = (
        await sess.execute(_event_query().where(Event.event_id == event_id))
    ).one_or_none()
    if row is None:
        return None
    return _event_response(*row)


async def query_events(
    sess: AsyncSession,
    *,
    object_id: UUID | None = None,
    event_type: str | None = None,
    event_type_prefix: str | None = None,
    risk_level: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[EventResponse]:
    """过滤（object_id/event_type 精确、event_type_prefix 前缀 LIKE
    ``prefix%``（与 event_type 互斥，路由层拦）/risk_level/since/until，
    时间闭区间）+ 同过滤计数（``total``，不含 cursor）+ 游标分页
    （occurred_at DESC, event_id DESC tiebreak）；主查询左连 outbox 派生
    ``delivery_status``、左连 business_objects 派生 ``object_source_id``；
    非法 cursor 视为首页。"""
    limit = max(1, min(limit, MAX_LIMIT))
    conditions = []
    if object_id is not None:
        conditions.append(Event.object_id == object_id)
    if event_type:
        conditions.append(Event.event_type == event_type)
    if event_type_prefix:
        conditions.append(Event.event_type.like(f"{event_type_prefix}%"))
    if risk_level:
        conditions.append(Event.risk_level == risk_level)
    if since is not None:
        conditions.append(Event.occurred_at >= since)
    if until is not None:
        conditions.append(Event.occurred_at <= until)

    total = (
        await sess.execute(select(func.count()).select_from(Event).where(*conditions))
    ).scalar_one()

    stmt = _event_query().where(*conditions)

    decoded = decode_cursor(cursor)
    if decoded is not None:
        anchor = _parse_anchor(decoded)
        if anchor is not None:
            occurred_at, event_id_anchor = anchor
            stmt = stmt.where(
                or_(
                    Event.occurred_at < occurred_at,
                    and_(
                        Event.occurred_at == occurred_at,
                        Event.event_id < event_id_anchor,
                    ),
                )
            )

    stmt = stmt.order_by(Event.occurred_at.desc(), Event.event_id.desc()).limit(
        limit + 1
    )
    rows = (await sess.execute(stmt)).all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1][0]
        next_cursor = encode_cursor(
            {"o": last.occurred_at.isoformat(), "i": str(last.event_id)}
        )
    return Page(
        items=[_event_response(event, status, source_id) for event, status, source_id in page_rows],
        next_cursor=next_cursor,
        total=total,
    )


def _event_response(
    event: Event, outbox_status: str | None, object_source_id: str | None
) -> EventResponse:
    """ORM 行 + 派生列 → 响应（ingest_latency_ms 经 from_attributes 直取）。"""
    response = EventResponse.model_validate(event)
    response.delivery_status = _DELIVERY_STATUS.get(outbox_status or "")
    response.object_source_id = object_source_id
    return response


def _parse_anchor(decoded: dict) -> tuple[datetime, UUID] | None:
    """cursor 载荷 → (occurred_at, event_id)；缺字段/格式非法 → None。"""
    try:
        return datetime.fromisoformat(str(decoded["o"])), UUID(str(decoded["i"]))
    except (KeyError, TypeError, ValueError):
        return None
