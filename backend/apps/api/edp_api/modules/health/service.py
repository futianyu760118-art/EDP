"""health 服务：基础健康 + 运行指标（B.13 子集 / spec §6.3 + W6 扩展 5 字段）。

``GET /api/v1/health`` 的 KPI 真数据源（事件流页 KPI 带）：探活 +
``ops_metrics``（近 24h 窗口，字段名与 MSW ``HealthResponse.ops_metrics``
逐字一致）；``deep=true`` 追加 ``db_ha``（pg_is_in_recovery /
pg_stat_replication）。

W6 扩展 5 可选字段（总览页 KPI 真数据源；全 ``| None``，exclude_none 下
无数据不出现；派生口径）：
- ``backup``：drills JSON（quality.service.list_drills）最近一项已执行的
  备份相关演练（drill_type ∈ {pitr, tenant_restore}——从备份集恢复/回放
  即备份可验证性的实测读数；switchover 为 HA 演练不计）→
  {last_backup_at=executed_at, status=result, source="drills"}；无记录 null；
- ``audit_events_7d``：platform.audit_logs 近 7d 计数（控制面表无 RLS——
  显式 tenant_id 过滤）；
- ``policy_hits_today``：审计策略命中当日计数——audit_policies 命中**不打
  独立动作行**（实测口径：审计切面在命中行 detail 打 ``policy_hits`` 键，
  audit/aspect.py），故 = 当日（UTC 日起）本租户含该键的审计行数；
- ``adapters_success_rate``：ops.tasks 最近 20 条 task_type=adapter_sync 的
  SUCCEEDED 占比（0.0~1.0；无记录 null）；
- ``evidence_valid_rate``：最近一次 quality_recheck（scope 含 CHECKSUM 或
  ALL）stats.checksum 派生 ``1 - failed/sampled``（无任务/无 checksum 段/
  sampled=0 → null）。

口径与已知偏差（T9 评审遗留，记入 T14 契约偏差清单，本轮不修）：
- ``idempotency_hit_rate`` 取 ``tenant_usage_daily`` 近两日行
  ``dup/(in+dup)``（日粒度近似，spec §6.3）——**归档命中路径漏计**：同
  ``Idempotency-Key`` 重放直接返回幂等存档、不重算，``bump_usage_daily``
  不累加 duplicated，该路径命中不计入本率（仅新 Key 重放的 event_id 幂等
  路径计数）；
- ``p95_latency_ms`` 的 ``ingest_latency_ms`` 口径为「函数入口 → INSERT 前」
  （events.ingest_batch 的 perf_counter 区间），不含 INSERT/证据/outbox/
  审计写入耗时。

跨模块表（event.events/outbox、evidence.records、platform.systems/
tenant_usage_daily/audit_logs、ops.tasks）以 core ``table()`` 构造参与纯
SQL 读——模块间仅可 import 对方 service，ORM 不可直接引用（口径同
ebms/ingest）；RLS 会话已 bind_tenant，跨租户行不可见（audit_logs 无 RLS
故显式 tenant 条件）。drills 读取经 quality.service.list_drills（文件读，
无 DB 访问）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Integer,
    TableClause,
    Text,
    Uuid,
    column,
    func,
    select,
    table,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.modules.health.schemas import BackupMetric, DbHa, HealthResponse, OpsMetrics
from edp_api.modules.quality import service as quality_service

HEALTH_VERSION = "2.0.0"
WINDOW_HOURS = 24
# 本部署无只读副本（spec §6.3「基础值」）：复制延迟恒 0
REPLICATION_LAG_MB = 0.0

_STATUS_PENDING = "PENDING"
_STATUS_FAILED = "FAILED"
_STATUS_PUBLISHED = "PUBLISHED"
_STATUS_SUCCEEDED = "SUCCEEDED"

# 备份相关演练类型（backup 字段口径，见模块 docstring）
BACKUP_DRILL_TYPES = frozenset({"pitr", "tenant_restore"})

_EVENTS = table(
    "events",
    column("event_id", Uuid),
    column("tenant_id", Uuid),
    column("ingest_latency_ms", Integer),
    column("created_at", DateTime(timezone=True)),
    schema="event",
)

_OUTBOX = table(
    "outbox",
    column("outbox_id", BigInteger),
    column("tenant_id", Uuid),
    column("status", Text),
    schema="event",
)

_EVIDENCE = table(
    "records",
    column("evidence_id", Uuid),
    column("tenant_id", Uuid),
    schema="evidence",
)

_SYSTEMS = table(
    "systems",
    column("system_id", Uuid),
    column("tenant_id", Uuid),
    column("name", Text),
    column("last_watermark", DateTime(timezone=True)),
    schema="platform",
)

_USAGE_DAILY = table(
    "tenant_usage_daily",
    column("tenant_id", Uuid),
    column("usage_date", Date),
    column("events_in", BigInteger),
    column("events_duplicated", BigInteger),
    schema="platform",
)

_AUDIT_LOGS = table(
    "audit_logs",
    column("audit_id", BigInteger),
    column("tenant_id", Uuid),
    column("occurred_at", DateTime(timezone=True)),
    column("detail", JSONB),
    schema="platform",
)

_TASKS = table(
    "tasks",
    column("task_id", Uuid),
    column("tenant_id", Uuid),
    column("task_type", Text),
    column("status", Text),
    column("scope", Text),
    column("stats", JSONB),
    column("created_at", DateTime(timezone=True)),
    schema="ops",
)


async def build_health(
    sess: AsyncSession, tenant_id: UUID, *, deep: bool = False
) -> HealthResponse:
    """组装健康响应（基础 + ops_metrics；deep=true 追加 db_ha）。"""
    await sess.execute(text("SELECT 1"))  # 探活：失败随请求异常（同一会话）
    cutoff = datetime.now(UTC) - timedelta(hours=WINDOW_HOURS)

    outbox_pending = await _count(
        sess,
        _OUTBOX,
        _OUTBOX.c.tenant_id == tenant_id,
        _OUTBOX.c.status == _STATUS_PENDING,
    )
    dlq = await _count(
        sess,
        _OUTBOX,
        _OUTBOX.c.tenant_id == tenant_id,
        _OUTBOX.c.status == _STATUS_FAILED,
    )
    evidence_count = await _count(sess, _EVIDENCE, _EVIDENCE.c.tenant_id == tenant_id)
    events_24h = await _count(
        sess,
        _EVENTS,
        _EVENTS.c.tenant_id == tenant_id,
        _EVENTS.c.created_at >= cutoff,
    )

    return HealthResponse(
        status="OK",
        db="OK",
        db_ha=await _db_ha(sess) if deep else None,
        outbox_pending=outbox_pending,
        last_sync=await _last_sync(sess, tenant_id),
        version=HEALTH_VERSION,
        ops_metrics=OpsMetrics(
            events_24h=events_24h,
            ingest_peak_24h=await _ingest_peak(sess, tenant_id, cutoff),
            p95_latency_ms=await _p95_latency(sess, tenant_id, cutoff),
            idempotency_hit_rate=await _hit_rate(sess, tenant_id),
            dlq=dlq,
            evidence_count=evidence_count,
            backup=_backup_metric(),
            audit_events_7d=await _audit_events_7d(sess, tenant_id),
            policy_hits_today=await _policy_hits_today(sess, tenant_id),
            adapters_success_rate=await _adapters_success_rate(sess, tenant_id),
            evidence_valid_rate=await _evidence_valid_rate(sess, tenant_id),
        ),
    )


async def _count(sess: AsyncSession, source: TableClause, *conditions) -> int:
    """COUNT(*)（无条件下为全表；RLS 会话下天然限本租户）。"""
    stmt = select(func.count()).select_from(source)
    if conditions:
        stmt = stmt.where(*conditions)
    return int((await sess.execute(stmt)).scalar_one())


async def _ingest_peak(sess: AsyncSession, tenant_id: UUID, cutoff: datetime) -> int:
    """近 24h 小时桶最大事件数（date_trunc('hour') 分组取 max；无数据 → 0）。"""
    bucket = func.date_trunc("hour", _EVENTS.c.created_at)
    hourly = (
        select(func.count().label("cnt"))
        .where(_EVENTS.c.tenant_id == tenant_id, _EVENTS.c.created_at >= cutoff)
        .group_by(bucket)
        .subquery()
    )
    stmt = select(func.coalesce(func.max(hourly.c.cnt), 0))
    return int((await sess.execute(stmt)).scalar_one())


async def _p95_latency(sess: AsyncSession, tenant_id: UUID, cutoff: datetime) -> int:
    """近 24h ingest_latency_ms 的 P95（percentile_cont；无数据 → 0）。

    latency 口径 = 「函数入口 → INSERT 前」（见模块 docstring 偏差记录）。
    """
    stmt = select(
        func.percentile_cont(0.95).within_group(_EVENTS.c.ingest_latency_ms.asc())
    ).where(
        _EVENTS.c.tenant_id == tenant_id,
        _EVENTS.c.created_at >= cutoff,
        _EVENTS.c.ingest_latency_ms.is_not(None),
    )
    value = (await sess.execute(stmt)).scalar_one()
    return int(round(float(value))) if value is not None else 0


async def _hit_rate(sess: AsyncSession, tenant_id: UUID) -> float:
    """幂等命中率 = dup/(in+dup)（近 24h 日粒度两行；无数据 → 0.0）。

    偏差（模块 docstring）：同 Idempotency-Key 的归档命中不累加 duplicated，
    本率只覆盖 event_id 幂等路径。
    """
    usage_cutoff: date = (datetime.now(UTC) - timedelta(hours=WINDOW_HOURS)).date()
    row = (
        await sess.execute(
            select(
                func.coalesce(func.sum(_USAGE_DAILY.c.events_in), 0),
                func.coalesce(func.sum(_USAGE_DAILY.c.events_duplicated), 0),
            ).where(
                _USAGE_DAILY.c.tenant_id == tenant_id,
                _USAGE_DAILY.c.usage_date >= usage_cutoff,
            )
        )
    ).one()
    total_in, total_dup = int(row[0]), int(row[1])
    total = total_in + total_dup
    return total_dup / total if total > 0 else 0.0


async def _last_sync(sess: AsyncSession, tenant_id: UUID) -> dict[str, str]:
    """systems 行 adapter → last_watermark ISO（未同步的适配器不出现）。"""
    rows = (
        await sess.execute(
            select(_SYSTEMS.c.name, _SYSTEMS.c.last_watermark)
            .where(
                _SYSTEMS.c.tenant_id == tenant_id,
                _SYSTEMS.c.last_watermark.is_not(None),
            )
            .order_by(_SYSTEMS.c.name)
        )
    ).all()
    return {name: watermark.isoformat() for name, watermark in rows}


async def _db_ha(sess: AsyncSession) -> DbHa:
    """数据库 HA 基础值（deep=true）：主从角色 + 复制连接数。

    ``replication_lag_mb`` 恒 0——本部署无只读副本；``pg_stat_replication``
    对无 pg_read_all_stats 权限的角色返回 0 行（不报错），开发库 replicas=0。
    """
    in_recovery = bool(
        (await sess.execute(text("SELECT pg_is_in_recovery()"))).scalar_one()
    )
    replicas = int(
        (await sess.execute(text("SELECT count(*) FROM pg_stat_replication"))).scalar_one()
    )
    return DbHa(
        role="replica" if in_recovery else "primary",
        replication_lag_mb=REPLICATION_LAG_MB,
        replicas=replicas,
    )


# ---- W6 扩展 5 字段派生（口径见模块 docstring） ----


def _backup_metric() -> BackupMetric | None:
    """备份读数（drills JSON 派生，无 DB 访问）：最近一项已执行的备份相关
    演练（drill_type ∈ BACKUP_DRILL_TYPES 且 executed_at 非空——pitr/
    tenant_restore 均为从备份集恢复/回放的实测归档）→
    {last_backup_at=executed_at, status=result, source="drills"}；
    无已执行记录 → None（exclude_none 下该键不出现）。"""
    executed = sorted(
        (
            record
            for record in quality_service.list_drills()
            if record.drill_type in BACKUP_DRILL_TYPES
            and record.executed_at is not None
        ),
        key=lambda record: record.executed_at,
    )
    if not executed:
        return None
    latest = executed[-1]
    return BackupMetric(
        last_backup_at=latest.executed_at.isoformat(),
        status=latest.result,
        source="drills",
    )


async def _audit_events_7d(sess: AsyncSession, tenant_id: UUID) -> int:
    """audit 表 7d 计数（platform.audit_logs；控制面表无 RLS → 显式
    tenant_id 过滤；空库 → 0 为合法计数仍返回）。"""
    cutoff = datetime.now(UTC) - timedelta(days=7)
    return await _count(
        sess,
        _AUDIT_LOGS,
        _AUDIT_LOGS.c.tenant_id == tenant_id,
        _AUDIT_LOGS.c.occurred_at >= cutoff,
    )


async def _policy_hits_today(sess: AsyncSession, tenant_id: UUID) -> int:
    """审计策略命中当日计数：audit_policies 命中不打独立动作行——审计
    切面在命中行 detail 打 ``policy_hits`` 键（实测 audit/aspect.py 口径），
    故 = 当日（UTC 日起）本租户 detail 含该键的审计行数（昨日命中不计）。"""
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return await _count(
        sess,
        _AUDIT_LOGS,
        _AUDIT_LOGS.c.tenant_id == tenant_id,
        _AUDIT_LOGS.c.occurred_at >= today_start,
        _AUDIT_LOGS.c.detail.has_key("policy_hits"),
    )


async def _adapters_success_rate(sess: AsyncSession, tenant_id: UUID) -> float | None:
    """ops.tasks 最近 20 条 task_type=adapter_sync 的 SUCCEEDED 占比
    （0.0~1.0；created_at DESC, task_id DESC tiebreak 取最近；无记录 → None）。"""
    stmt = (
        select(_TASKS.c.status)
        .where(_TASKS.c.tenant_id == tenant_id, _TASKS.c.task_type == "adapter_sync")
        .order_by(_TASKS.c.created_at.desc(), _TASKS.c.task_id.desc())
        .limit(20)
    )
    statuses = [row[0] for row in (await sess.execute(stmt)).all()]
    if not statuses:
        return None
    return statuses.count(_STATUS_SUCCEEDED) / len(statuses)


async def _evidence_valid_rate(sess: AsyncSession, tenant_id: UUID) -> float | None:
    """最近一次 quality_recheck（scope ∈ {CHECKSUM, ALL}——仅这两档执行
    checksum 段）stats.checksum 派生 ``1 - failed/sampled``；无任务 / 无
    checksum 段 / sampled=0 → None。"""
    stmt = (
        select(_TASKS.c.stats)
        .where(
            _TASKS.c.tenant_id == tenant_id,
            _TASKS.c.task_type == "quality_recheck",
            _TASKS.c.scope.in_(["CHECKSUM", "ALL"]),
        )
        .order_by(_TASKS.c.created_at.desc(), _TASKS.c.task_id.desc())
        .limit(1)
    )
    stats = (await sess.execute(stmt)).scalar_one_or_none()
    checksum = stats.get("checksum") if isinstance(stats, dict) else None
    if not isinstance(checksum, dict):
        return None
    sampled, failed = checksum.get("sampled"), checksum.get("failed")
    if not isinstance(sampled, (int, float)) or sampled <= 0:
        return None
    failed_value = failed if isinstance(failed, (int, float)) else 0
    return 1 - failed_value / sampled
