"""evidence 服务：canonical checksum（管道/verify 共用）/ 证据创建 /
verify 重算比对（失败告警审计）/ 逆向追溯查询 / 证据重索引（W3-04 收口）。

checksum 单一实现（EDP-008 防漂移）：canonical_json = 键排序 + 紧凑分隔符
+ ensure_ascii=False；compute_checksum = "sha256:" + hex。T14 管道落证据
与本模块 verify 共用这两个函数，杜绝两套序列化导致的假阳性告警。

verify 失败（重算 ≠ 存储）经 audit.service.record_explicit 同事务落
EVIDENCE_VERIFY_FAILED 行（detail.risk=P1 + expected/actual）；请求级提交
由 core.db.get_db 统一执行（record_explicit 只 add 不 flush）。

RLS：会话由 tenant_scoped 预 bind_tenant（evidence.* FORCE RLS）——
object 存在性校验（经 registry.service.object_exists）与读写天然限本
租户，跨租户 object_id/evidence_id 与不存在同义。

重索引（``start_reindex``，W3-04 收口）：POST /admin/evidence/reindex 建
ops.tasks 行（task_type=evidence_reindex）→ 202；后台执行体
（``_run_reindex``）遍历本租户 evidence.records 全量重算 canonical
checksum（复用本模块 compute_checksum）——**重算与原值不一致仅计数 +
落 ``quality.reindex_mismatch`` 事件，保留原值不回写**（checksum 语义
不变：存储值 = 入库时快照的指纹，篡改探测依赖该不变量；修复动作留给
  人工/后续任务）。执行语义（会话/事务/可见性重试/任务互斥 advisory
  lock（W6 T3，锁句柄经 ``quality.service.TaskMutex`` 复用）/终态与完成
  事件移出终态事务）沿 T4 quality recheck 口径，详见 ``_run_reindex``
  docstring。
"""

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from edp_api.core import db as core_db
from edp_api.core.errors import EdpError
from edp_api.core.pagination import Page, decode_cursor, encode_cursor
from edp_api.core.security.principal import Principal
from edp_api.modules.audit import service as audit_service
from edp_api.modules.events import service as events_service
from edp_api.modules.events.schemas import EventIn

# quality.service 互引本模块（compute_checksum）——模块别名引用（运行时取
# 属性）避免部分初始化期的名字导入竞态；OpsTask 映射与 wait_task_visible
# 公共 helper 经 service 路径透出（import-linter 跨模块仅准 service）
from edp_api.modules.evidence.models import EvidenceLink, EvidenceRecord
from edp_api.modules.evidence.schemas import (
    EvidenceCreateRequest,
    EvidenceListItem,
    RefType,
)
from edp_api.modules.quality import service as quality_service
from edp_api.modules.registry import service as registry_service

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

VERIFY_FAILED_ACTION = "EVIDENCE_VERIFY_FAILED"

# ---- 证据重索引（W3-04 收口）----

REINDEX_TASK_TYPE = "evidence_reindex"
REINDEX_MISMATCH_EVENT_TYPE = "quality.reindex_mismatch"
REINDEX_SUCCEEDED_EVENT_TYPE = "quality.reindex_succeeded"
REINDEX_FAILED_EVENT_TYPE = "quality.reindex_failed"
# 全量扫描分批大小（keyset 分页，控制单事务内存驻留的 snapshot 份数）
REINDEX_SCAN_BATCH = 200


def canonical_json(payload: dict) -> str:
    """单一 canonical 实现：键排序 + 紧凑分隔符（管道/verify 共用，防漂移）。"""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_checksum(payload: dict) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


async def create_record(
    sess: AsyncSession, principal: Principal, req: EvidenceCreateRequest
) -> EvidenceRecord:
    """创建证据：object 存在性校验 → INSERT（checksum 服务端计算）+ links。

    Raises:
        EdpError(VALIDATION_ERROR): object_id 在本租户不存在（RLS 下跨租户
        与不存在同义）。
    """
    if not await registry_service.object_exists(sess, req.object_id):
        raise EdpError.validation_error(f"object_id 不存在：{req.object_id}")

    captured_at = req.captured_at
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=UTC)

    record = EvidenceRecord(
        evidence_id=uuid4(),
        tenant_id=principal.tenant_id,
        source_system=req.source_system,
        source_record_id=req.source_record_id,
        object_id=req.object_id,
        event_id=req.event_id,
        checksum=compute_checksum(req.snapshot),
        snapshot=req.snapshot,
        captured_at=captured_at,
        created_by=principal.id,
        updated_by=principal.id,
    )
    sess.add(record)
    # 先 flush 记录再插 links：ORM 列不声明 ForeignKey（模块约定），unit of
    # work 无法自行推导 records→links 插入次序，须显式分两步
    await sess.flush()  # 约束违反（如 event_id 外键）在请求内即时暴露
    for link in req.links:
        sess.add(
            EvidenceLink(
                link_id=uuid4(),
                tenant_id=principal.tenant_id,
                evidence_id=record.evidence_id,
                ref_type=link.ref_type,
                ref_id=link.ref_id,
                created_by=principal.id,
                updated_by=principal.id,
            )
        )
    if req.links:
        await sess.flush()
    return record


async def ensure_link(
    sess: AsyncSession,
    principal: Principal,
    *,
    evidence_id: UUID,
    ref_type: RefType,
    ref_id: UUID,
) -> EvidenceLink | None:
    """按 (evidence_id, ref_type, ref_id) 幂等建链（跨模块消费口：decisions 的
    CASE 关联等）。

    证据不存在（含跨租户，RLS 下同义）→ None（调用方决定 400/跳过）；已存在
    → 返回既有行不重复写；新建走 ORM（切面审计可见）。
    """
    if await sess.get(EvidenceRecord, evidence_id) is None:
        return None
    existing = (
        (
            await sess.execute(
                select(EvidenceLink).where(
                    EvidenceLink.evidence_id == evidence_id,
                    EvidenceLink.ref_type == ref_type,
                    EvidenceLink.ref_id == ref_id,
                )
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        return existing
    link = EvidenceLink(
        link_id=uuid4(),
        tenant_id=principal.tenant_id,
        evidence_id=evidence_id,
        ref_type=ref_type,
        ref_id=ref_id,
        created_by=principal.id,
        updated_by=principal.id,
    )
    sess.add(link)
    await sess.flush()
    return link


async def get_record(
    sess: AsyncSession, evidence_id: UUID
) -> EvidenceRecord | None:
    """按 evidence_id 点查；RLS 下跨租户 = 不存在（None）。"""
    return await sess.get(EvidenceRecord, evidence_id)


async def links_for(sess: AsyncSession, evidence_id: UUID) -> list[EvidenceLink]:
    """按证据查 links（created_at 升序稳定输出）。"""
    return list(
        (
            await sess.execute(
                select(EvidenceLink)
                .where(EvidenceLink.evidence_id == evidence_id)
                .order_by(EvidenceLink.created_at, EvidenceLink.link_id)
            )
        )
        .scalars()
        .all()
    )


async def verify_record(
    sess: AsyncSession, principal: Principal, evidence_id: UUID
) -> tuple[EvidenceRecord, bool] | None:
    """重算 checksum 与存储值比对；失配时同事务落 EVIDENCE_VERIFY_FAILED
    审计行（detail.risk=P1 + expected=存储值 / actual=重算值）。

    Returns:
        (记录, valid)；evidence_id 不存在（含跨租户）→ None。
    """
    record = await get_record(sess, evidence_id)
    if record is None:
        return None
    recomputed = compute_checksum(record.snapshot)
    valid = recomputed == record.checksum
    if not valid:
        await audit_service.record_explicit(
            sess,
            action=VERIFY_FAILED_ACTION,
            resource_type="evidence",
            resource_id=str(evidence_id),
            detail={
                "risk": "P1",
                "expected": record.checksum,
                "actual": recomputed,
            },
            principal=principal,
        )
    return record, valid


async def query_records(
    sess: AsyncSession,
    *,
    ref_type: str | None = None,
    ref_id: UUID | None = None,
    object_id: UUID | None = None,
    q: str | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[EvidenceListItem]:
    """过滤（ref_type+ref_id 可对 → links 子查询 IN；object_id 直接过滤；
    ``q`` 对 source_record_id/source_system ILIKE 模糊匹配，``%``/``_`` 转义）
    + 游标分页（captured_at DESC, evidence_id DESC tiebreak，锚 {"c","i"}；非法
    cursor 视为首页）。"""
    limit = max(1, min(limit, MAX_LIMIT))
    stmt = select(EvidenceRecord)
    if ref_type and ref_id is not None:
        stmt = stmt.where(
            EvidenceRecord.evidence_id.in_(
                select(EvidenceLink.evidence_id).where(
                    EvidenceLink.ref_type == ref_type,
                    EvidenceLink.ref_id == ref_id,
                )
            )
        )
    if object_id is not None:
        stmt = stmt.where(EvidenceRecord.object_id == object_id)
    if q:
        pattern = f"%{q.strip().replace('\\', '\\\\').replace('%', r'\%').replace('_', r'\_')}%"
        stmt = stmt.where(
            or_(
                EvidenceRecord.source_record_id.ilike(pattern, escape="\\"),
                EvidenceRecord.source_system.ilike(pattern, escape="\\"),
            )
        )

    decoded = decode_cursor(cursor)
    if decoded is not None:
        anchor = _parse_anchor(decoded)
        if anchor is not None:
            captured_at, evidence_id_anchor = anchor
            stmt = stmt.where(
                or_(
                    EvidenceRecord.captured_at < captured_at,
                    and_(
                        EvidenceRecord.captured_at == captured_at,
                        EvidenceRecord.evidence_id < evidence_id_anchor,
                    ),
                )
            )

    stmt = stmt.order_by(
        EvidenceRecord.captured_at.desc(), EvidenceRecord.evidence_id.desc()
    ).limit(limit + 1)
    rows = (await sess.execute(stmt)).scalars().all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"c": last.captured_at.isoformat(), "i": str(last.evidence_id)}
        )
    return Page(
        items=[EvidenceListItem.model_validate(row) for row in page_rows],
        next_cursor=next_cursor,
    )


def _parse_anchor(decoded: dict) -> tuple[datetime, UUID] | None:
    """cursor 载荷 → (captured_at, evidence_id)；缺字段/格式非法 → None。"""
    try:
        return datetime.fromisoformat(str(decoded["c"])), UUID(str(decoded["i"]))
    except (KeyError, TypeError, ValueError):
        return None


# ---- 证据重索引（W3-04 收口）----

# create_task 强引用防 GC（官方建议模式，同 quality/adapters_admin；完成回调自清理）
_reindex_tasks: set[asyncio.Task[None]] = set()


async def start_reindex(
    sess: AsyncSession, principal: Principal, *, scope: str
) -> "quality_service.OpsTask":
    """登记 evidence_reindex 任务行并派发后台执行（路由层 202 语义）。

    **任务互斥（W6 T3）**：入口先 ``quality_service.try_acquire_task_lock``
    （evidence_reindex 键）——被占 → 409 CONFLICT（不登记行）；拿到锁才
    建行/派发，锁句柄随后台执行体走（执行体 finally 释放；锁语义与连接
    生命周期见 ``quality_service.TaskMutex`` docstring）。状态落库多副本
    安全（行级回写、终态幂等）。任务行可见性由请求级 commit 兜底，后台
    执行体先等行可见再执行（``_run_reindex`` docstring）。
    """
    mutex = await quality_service.try_acquire_task_lock(
        quality_service.task_lock_key(REINDEX_TASK_TYPE)
    )
    if mutex is None:
        await quality_service.raise_task_conflict(
            sess, principal.tenant_id, REINDEX_TASK_TYPE
        )
    try:
        started_at = datetime.now(UTC)
        task = quality_service.OpsTask(
            task_id=uuid4(),
            tenant_id=principal.tenant_id,
            task_type=REINDEX_TASK_TYPE,
            status="RUNNING",
            scope=scope,
            started_at=started_at,
            created_by=principal.id,
        )
        sess.add(task)
        await sess.flush()  # 审计 TASK_CREATE 随请求事务落库
        background = asyncio.create_task(
            _run_reindex(
                task_id=task.task_id,
                tenant_id=principal.tenant_id,
                principal=principal,
                scope=scope,
                started_at=started_at,
                mutex=mutex,
            )
        )
        _reindex_tasks.add(background)
        background.add_done_callback(_reindex_tasks.discard)
    except Exception:
        await mutex.release()  # 登记/派发失败就地释放（后台未接手）
        raise
    return task


async def _run_reindex(
    *,
    task_id: UUID,
    tenant_id: UUID,
    principal: Principal,
    scope: str,
    started_at: datetime,
    mutex: "quality_service.TaskMutex | None" = None,
) -> None:
    """后台执行体：等行可见（``quality.service.wait_task_visible`` 公共
    helper）→ 全量分批重算 checksum → stats/logs 落 ops.tasks → 终态 +
    事件。

    互斥锁：入口已取得的 ``mutex`` 句柄随执行体走——**finally 释放**
    （任务终态/提前退出均达；缺省 None 容忍无锁直调）。

    会话与事务：不复用请求会话（随请求关闭）——经 get_session_local 开
    独立会话；bind_tenant 事务级（set_config is_local）→ 每扫描批次独立
    事务（进度逐批 commit 落库，批前重绑），终态先行 commit 后事件经独立
    事务尽力写入（沿 T4 语义，见 ``_record_reindex_events``）。

    扫描：keyset 分页（evidence_id 升序游标 + LIMIT 批量），total = 扫描
    起始时全租户行数、rechecked = 实际重算行数（并发写入下两者可不相等）；
    **重算 ≠ 存储值仅计数 + 落事件，保留原值不回写**（checksum 语义 =
    入库指纹，篡改探测依赖其不变量；修复留给人工/后续任务）。

    失败语义：任一批异常 → 整任务 FAILED（已完成批次进度已逐批落库）；
    FAILED 回写经独立事务尽力落库（回写自身异常仅告警）。
    """
    factory = core_db.get_session_local()
    stats: dict[str, int] = {"total": 0, "rechecked": 0, "mismatched": 0}
    mismatches: list[dict] = []
    logs = [_log_line("INFO", f"任务启动：scope={scope}")]
    try:
        async with factory() as sess:
            if not await quality_service.wait_task_visible(sess, tenant_id, task_id):
                logger.warning(
                    "reindex 任务行 %d 次探测均不可见（deadline 后仍不可见，"
                    "请求事务已回滚）：%s",
                    quality_service.TASK_VISIBILITY_ATTEMPTS,
                    task_id,
                )
                return
            await core_db.bind_tenant(sess, tenant_id)
            stats["total"] = (
                await sess.execute(select(func.count()).select_from(EvidenceRecord))
            ).scalar_one()
            logs.append(_log_line("INFO", f"全量重算开始：共 {stats['total']} 条证据"))
            last_id: UUID | None = None
            while True:
                await core_db.bind_tenant(sess, tenant_id)
                stmt = (
                    select(
                        EvidenceRecord.evidence_id,
                        EvidenceRecord.checksum,
                        EvidenceRecord.snapshot,
                    )
                    .order_by(EvidenceRecord.evidence_id)
                    .limit(REINDEX_SCAN_BATCH)
                )
                if last_id is not None:
                    stmt = stmt.where(EvidenceRecord.evidence_id > last_id)
                rows = (await sess.execute(stmt)).all()
                if not rows:
                    break
                for evidence_id, stored, snapshot in rows:
                    actual = compute_checksum(snapshot)
                    stats["rechecked"] += 1
                    if actual != stored:
                        stats["mismatched"] += 1
                        mismatches.append(
                            {
                                "evidence_id": str(evidence_id),
                                "expected": stored,
                                "actual": actual,
                            }
                        )
                    last_id = evidence_id
                logs.append(
                    _log_line(
                        "INFO",
                        f"进度：已重算 {stats['rechecked']}/{stats['total']}"
                        f"，失配 {stats['mismatched']}",
                    )
                )
                await _apply_reindex_task(
                    sess, task_id, stats=dict(stats), logs=list(logs), actor=principal.id
                )
                await sess.commit()
            await core_db.bind_tenant(sess, tenant_id)
            logs.append(_log_line("INFO", "任务完成：SUCCEEDED"))
            await _apply_reindex_task(
                sess,
                task_id,
                stats=dict(stats),
                logs=list(logs),
                actor=principal.id,
                status="SUCCEEDED",
                finished_at=datetime.now(UTC),
            )
            await sess.commit()  # 终态先行落库——事件失败不回滚重算结果
        await _record_reindex_events(
            factory,
            tenant_id,
            principal,
            task_id=task_id,
            scope=scope,
            started_at=started_at,
            stats=stats,
            mismatches=mismatches,
        )
    except Exception as exc:
        logger.error("证据重索引任务失败：%s（scope=%s）", task_id, scope, exc_info=True)
        try:
            async with factory() as sess:
                await core_db.bind_tenant(sess, tenant_id)
                error = str(exc)[:500]
                logs.append(_log_line("ERROR", f"任务失败：{exc!r}"))
                await _apply_reindex_task(
                    sess,
                    task_id,
                    stats=dict(stats),
                    logs=list(logs),
                    actor=principal.id,
                    status="FAILED",
                    finished_at=datetime.now(UTC),
                )
                await sess.commit()  # FAILED 终态先行落库
            await _record_reindex_events(
                factory,
                tenant_id,
                principal,
                task_id=task_id,
                scope=scope,
                started_at=started_at,
                stats=stats,
                mismatches=mismatches,
                error=error,
            )
        except Exception:
            logger.error("reindex FAILED 终态回写失败：%s", task_id, exc_info=True)
    finally:
        if mutex is not None:
            await mutex.release()  # 互斥窗 = 入口取锁至执行体收尾（终态/提前退出均达）


async def _apply_reindex_task(
    sess: AsyncSession,
    task_id: UUID,
    *,
    stats: dict,
    logs: list[dict],
    actor: str,
    status: str | None = None,
    finished_at: datetime | None = None,
) -> None:
    """ops.tasks 回写（不 commit——事务边界在调用方；同 quality._apply_task）。
    stats/logs 整行重赋值（JSONB 原位修改对 ORM 变更检测不可见）；行不
    存在（请求事务回滚）静默跳过——审计 TASK_UPDATE 随调用方事务落库。"""
    task = (
        await sess.execute(
            select(quality_service.OpsTask).where(
                quality_service.OpsTask.task_id == task_id
            )
        )
    ).scalar_one_or_none()
    if task is None:
        return
    task.stats = stats
    task.logs = logs
    task.updated_by = actor
    if status is not None:
        task.status = status
        task.finished_at = finished_at


async def _record_reindex_events(
    factory: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    principal: Principal,
    *,
    task_id: UUID,
    scope: str,
    started_at: datetime,
    stats: dict,
    mismatches: list[dict],
    error: str | None = None,
) -> None:
    """事件移出终态事务（沿 T4 语义）：终态已先行 commit，失配事件 +
    完成事件经独立会话/事务**尽力**写入（ingest 均 internal=True——
    W5-09 内部写入豁免计量；审计/outbox 副作用不变）——ingest 抛错仅
    告警不回滚，已落的终态不因事件通道异常改判（失配明细同时由任务行
    stats/logs 留痕）。

    失配事件 ``quality.reindex_mismatch``（仅 mismatched>0）：**聚合一条**
    （实现取简并留痕——逐条事件的 per-evidence 幂等可由 T3
    quality.checksum_failed 抽检通道覆盖，reindex 事件携带全量失配清单，
    data.mismatches = [{evidence_id, expected, actual}]）；UUIDv5 幂等
    （occurred_at=任务 started_at、幂等键 quality-reindex-mismatch:{task_id}
    ——同任务重放恒同 event_id），risk_level 留空不计入异常面。完成事件
    ``quality.reindex_succeeded/failed`` 同 T4 形状（幂等键
    quality-reindex:{task_id}）。两事件 object 锚点 = 注册表最小
    object_id（T4 口径；空注册表跳过事件——结果已由任务行 stats/logs
    留痕）。
    """
    try:
        async with factory() as sess:
            await core_db.bind_tenant(sess, tenant_id)
            anchor = (
                await sess.execute(
                    text(
                        "SELECT object_id FROM master.business_objects"
                        " ORDER BY object_id LIMIT 1"
                    )
                )
            ).scalar()
            if anchor is None:
                return
            # 写通道三件套复用 quality 的 edp-quality 通道常量（运行时取
            # 属性——模块级别名会在 quality.service 部分初始化期踩未定义名）
            source_system = quality_service.RECHECK_EVENT_SOURCE_SYSTEM
            actor_id = quality_service.RECHECK_EVENT_ACTOR_ID
            if mismatches:
                await events_service.ingest_batch(
                    sess,
                    principal,
                    f"quality-reindex-mismatch:{task_id}",
                    [
                        EventIn(
                            event_type=REINDEX_MISMATCH_EVENT_TYPE,
                            object_id=anchor,
                            source_system=source_system,
                            occurred_at=started_at,
                            actor_type="SERVICE",
                            actor_id=actor_id,
                            data={
                                "task_id": str(task_id),
                                "mismatched": len(mismatches),
                                "mismatches": mismatches,
                            },
                        )
                    ],
                    internal=True,
                )
            event_type = (
                REINDEX_FAILED_EVENT_TYPE if error is not None
                else REINDEX_SUCCEEDED_EVENT_TYPE
            )
            data: dict = {"task_id": str(task_id), "scope": scope, "stats": stats}
            if error is not None:
                data["error"] = error
            await events_service.ingest_batch(
                sess,
                principal,
                f"quality-reindex:{task_id}",
                [
                    EventIn(
                        event_type=event_type,
                        object_id=anchor,
                        source_system=source_system,
                        occurred_at=started_at,
                        actor_type="SERVICE",
                        actor_id=actor_id,
                        data=data,
                    )
                ],
                internal=True,
            )
            await sess.commit()
    except Exception:
        logger.error(
            "reindex 完成事件写入失败（终态已落库，仅告警）：%s", task_id, exc_info=True
        )


def _log_line(level: str, message: str) -> dict:
    """log 行（形状对齐 quality 任务 logs / mocks QualityTask：{ts, level,
    message}——与 quality/adapters_admin 的同名私有 helper 同形，模块私用）。"""
    return {"ts": datetime.now(UTC).isoformat(), "level": level, "message": message}
