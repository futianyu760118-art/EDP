"""quality 服务（EDP-030：T3 质量报告四段实时聚合 + T4 任务轨道）。

四段口径（B.13 + W5 spec §4.1；写死于本 docstring，单测/集成测试断言同口径）：

- **对账 reconciliation**：按 (source_system, object_type) 分组——
  ``edp_count`` = EDP 持有对象数（master.business_objects 分组计数。领域
  投影表主键 = object_id 与对象行 1:1 且无 source_system 列，注册对象表
  即「projections 领域快照行数」的实现口径——投影失败差异由 ingest 告警
  链路反映，口径同 spec §4.1）；``source_count`` = 适配器确定性数据集
  期望基数（edp_adapters.demo_dataset.SNAPSHOT_RECORDS 分组计数——Mock
  基线唯一「最小来源」；组不在数据集 → None，即 real/无水位降级：
  deviation_pct=0.0、ok=true）；``deviation_pct = round(|source-edp|/
  source*100, 2)``（source 为 0/null → 0.0）；``ok = deviation_pct <=
  2.0``（阈值 >2% 即 false；以四舍五入后的展示值判定，展示与判定一致）。
  组全集 = DB 实际组 ∪ 期望基数组（源声明而未同步的组 edp_count=0 可见）；
- **覆盖率 coverage**：已接入对象（≥1 event 或 ≥1 evidence 关联）/
  注册对象（master.business_objects 计数），overall 与 by_type 双口径；
  注册对象数为 0 时 overall=100.0（空集约定：无对象即无缺口）；
- **孤儿 orphans**：event.events.object_id 无对应注册对象计数；
  evidence.records 悬挂计数（object_id 无对应注册对象）；
- **checksum 抽检 checksum_sampling**：P0/P1 证据（evidence.records 经
  ``event_id`` 列或 links(ref_type='RESULT') 关联事件 risk_level IN
  ('P0','P1')）按 captured_at 降序抽样上限 120（或全量取小；抽样策略
  留痕：新证据优先入样——若按 evidence_id 升序，最旧证据恒占满限额，
  抽检样本将被永久冻结；降序保证抽检面随新证据滚动，evidence_id 降序
  作并列确定性 tie-break），重算
  canonical checksum（复用 evidence.service.compute_checksum 单一实现，
  杜绝两套序列化）比对；**仅失配行**经 events.service.ingest_batch
  （internal=True——W5-09 内部写入豁免计量）写
  ``quality.checksum_failed`` 事件（UUIDv5 幂等：occurred_at 取证据
  captured_at → 同失配重复抽检恒同 event_id，幂等键归档 + ON CONFLICT
  双保险不重复落数；risk_level 留空不计入异常面；审计/outbox 为既有
  副作用，随请求事务提交）。

kpi/dimensions 派生（纯函数，表驱动单测）：

- ``pending_exceptions`` = OPEN 异常数（risk_level 非空且无已 DECIDED
  关联案例——口径同 ebms exceptions 的 OPEN）；``high_priority`` =
  P0/P1 风险事件数；
- ``completeness_pct`` = coverage.overall_pct；
- ``sla_pct`` = 证据抽检通过率 = 100*(sampled-failed)/sampled
  （sampled=0 → 100.0）；
- 四维度评分（段内零异常=满分 100，按异常率线性扣减
  ``100*(1-bad/total)``，分母 0 → 100.0）：
  reconciliation（bad=ok=false 且有期望基数的组数 / total=有期望基数的
  组数——降级行不计分母）、coverage（= overall_pct）、orphans
  （bad=两类孤儿之和 / total=events+evidence 总行数）、checksum
  （bad=failed / total=sampled）；
- ``kpi.overall_pct`` = 四维度评分均分。

实时计算：date 参数接受并回显（缺省=请求日），不回溯——预聚合/物化
W6 压测后评估（偏差登记 §13.3）。

跨模块表（master.business_objects / event.events / evidence.records /
evidence.links / decision.cases）以纯 SQL 读（口径同 ebms 的跨模块纯
SQL 读——模块间仅可 import 对方 service，ORM 不可直接引用）；RLS 会话
已 bind_tenant，跨租户行不可见。

事务边界：本层只 flush 不 commit——请求级提交由 core.db.get_db 统一执行
（checksum 失配事件的 ingest 同事务）；例外：后台执行体（任务轨道，下述）
自开独立会话、自管逐段事务。

任务轨道（EDP-030 下半，T4）：``start_recheck`` 建 ops.tasks 行
（task_type=quality_recheck，scope ∈ RECONCILE|ORPHAN|CHECKSUM|ALL）→
202 后 ``asyncio.create_task`` 派发后台执行（同 adapters_admin 的派发
模式：强引用防 GC）——复用上方各段计算函数（scope 单段 / ALL 四段，
stats 无独立 scope——仅 ALL 覆盖 coverage 段）→ stats（段名 → 结果
摘要 dict）+ logs（``[{ts, level, message}]``，每段起止/关键计数）逐段
落库、终态回写 SUCCEEDED/FAILED + finished_at；完成写
``quality.recheck_succeeded`` / ``quality.recheck_failed`` 事件（复用
events.ingest_batch，internal=True——W5-09 内部写入豁免计量：同 T3
checksum_failed 写通道：UUIDv5 幂等 occurred_at=任务 started_at、幂等键
quality-recheck:{task_id}；事件 object 锚点 = 注册表最小 object_id
（ORDER BY LIMIT 1），ingest 通道校验 object 存在性，空注册表跳过事件
——结果已由任务行 stats/logs 留痕）。完成事件**移出终态事务**：终态先
行 commit 落库，事件随后经独立事务尽力写入——事件通道异常仅告警，不把
已成功的计算回滚改判 FAILED。后台会话独立于请求会话（get_session_local），
bind_tenant 事务级 → 每段独立事务；首段前可见性**有界重试**
（``wait_task_visible``——T5 评审移交的公共 helper，单一实现供
adapters_admin.service / evidence.service 后台执行体复用，防复制漂移）：
READ COMMITTED 下请求事务未提交的 INSERT
行对后台不可见，且 SELECT ... FOR UPDATE 对不可见（不存在）的行不
阻塞、立即返回空——后台可能先于请求 commit 启动，首次探测读空属
正常，按固定间隔重试至行可见再执行；deadline 后仍不可见 = 请求事务
已回滚（行确不存在），提前退出。

任务互斥（W6 T3 / Redis B 轻量项，redis-evaluation §4 建议）：三类后台
任务入口（quality recheck / evidence reindex / adapter sync）统一
``pg_try_advisory_lock(hashtext('ops.task:' || task_type))`` 会话级
advisory lock——``TaskMutex`` / ``try_acquire_task_lock`` 公共实现置于
本模块（quality 为任务轨道枢纽，evidence/adapters_admin 经 service 路径
复用）；锁被占 → 409 CONFLICT（复用既有 CONFLICT 码 + message/extra
区分任务冲突语义，**不扩 13 错误码表**——沿 registry 乐观锁 409 先例，
spec §2.3 留痕）。锁语义与连接生命周期详见 ``TaskMutex`` docstring。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn
from uuid import UUID, uuid4

from edp_adapters.demo_dataset import SNAPSHOT_RECORDS
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
)

from edp_api.core import db as core_db
from edp_api.core.errors import EdpError
from edp_api.core.security.principal import Principal
from edp_api.modules.events import service as events_service
from edp_api.modules.events.schemas import EventIn
from edp_api.modules.evidence import service as evidence_service
from edp_api.modules.quality.models import OpsTask
from edp_api.modules.quality.schemas import (
    ChecksumSampling,
    CoverageByType,
    CoverageReport,
    DimensionScore,
    DrillRecord,
    OrphansReport,
    OutboxStatusOut,
    QualityKpi,
    QualityReport,
    ReconciliationRow,
)

logger = logging.getLogger(__name__)

# 对账阈值：四舍五入后的 deviation_pct > 2.0 即 ok=false（2.0 边界 ok=true）
DEVIATION_THRESHOLD_PCT = 2.0
# checksum 抽样每日上限（或 P0/P1 证据全量取小）
CHECKSUM_SAMPLE_LIMIT = 120
CHECKSUM_FAILED_EVENT_TYPE = "quality.checksum_failed"
CHECKSUM_FAILED_SOURCE_SYSTEM = "edp-quality"
CHECKSUM_FAILED_ACTOR_ID = "service:quality"

# ---- 任务轨道（EDP-030 下半，T4）----

RECHECK_TASK_TYPE = "quality_recheck"
RECHECK_SUCCEEDED_EVENT_TYPE = "quality.recheck_succeeded"
RECHECK_FAILED_EVENT_TYPE = "quality.recheck_failed"
# 完成事件来源三件套与 T3 checksum_failed 事件同口径（同一 edp-quality 写通道）
RECHECK_EVENT_SOURCE_SYSTEM = CHECKSUM_FAILED_SOURCE_SYSTEM
RECHECK_EVENT_ACTOR_ID = CHECKSUM_FAILED_ACTOR_ID

# 任务行可见性有界重试（T4 评审 Important-1）：READ COMMITTED 下请求
# 事务未提交的 INSERT 行不可见且 FOR UPDATE 不等待——后台执行体先于
# 请求 commit 启动时首次探测读空属正常，重试至行可见；10 次 × 100ms
# ≈ 1s deadline 后仍不可见才判「请求事务已回滚」
TASK_VISIBILITY_ATTEMPTS = 10
TASK_VISIBILITY_INTERVAL_S = 0.1

# ---- 任务互斥 advisory lock（W6 T3 / Redis B 轻量项）----

_TASK_TRY_LOCK_SQL = text("SELECT pg_try_advisory_lock(hashtext(:key))")
_TASK_UNLOCK_SQL = text("SELECT pg_advisory_unlock(hashtext(:key))")


def task_lock_key(task_type: str, ref_name: str | None = None) -> str:
    """advisory lock 键：``ops.task:{task_type}``（adapter_sync 附
    ``:{ref_name}``——同一适配器互斥、不同适配器并行，沿任务轨道既有
    「同一适配器并发」语义；键不含 tenant_id，spec §2.3 取简口径）。"""
    suffix = f":{ref_name}" if ref_name else ""
    return f"ops.task:{task_type}{suffix}"


@dataclass(slots=True)
class TaskMutex:
    """任务互斥 advisory lock 句柄（锁语义与连接生命周期留痕）：

    - **会话级锁绑定连接**：``pg_try_advisory_lock`` 取得的锁归获取它的
      那条 DB 连接所有，连接关闭（显式释放 / 进程崩溃被服务端断开）即
      自动解锁——崩溃安全，无孤儿锁、无需 TTL；
    - **专用连接持有**：句柄持有自引擎池检出的**专用**连接至
      ``release()``。不能在请求会话或后台执行会话上获取：SQLAlchemy
      会话逐事务从池换用连接，事务结束连接归还池而会话级锁仍挂在它
      上——锁会泄漏给池中下一个使用者。专用连接在任务期间被占用
      （pool 10 + overflow 20，三类任务低频，可接受——redis-evaluation
      §4 已知权衡）；
    - **触发即互斥**：入口（start_recheck / start_reindex /
      trigger_sync）try-lock 成功才登记任务行并派发后台执行体（锁句柄
      随执行体走，执行体 finally 释放）——两个并发 POST 同 task_type
      恒一个 202 一个 409；入口登记/派发抛错由入口就地释放；
    - 被占 → 409 CONFLICT（复用既有错误码，extra 附 task_type 与
      current_task_hint——本租户最新 RUNNING 任务行 id 尽力探测，多副本
      下持锁方可能在他租户/他副本，无行可指则略）。
    """

    key: str
    conn: AsyncConnection

    async def release(self) -> None:
        """释放锁并归还连接（尽力：unlock 异常不阻断 close——连接关闭
        即解锁，双重保险）。"""
        try:
            await self.conn.execute(_TASK_UNLOCK_SQL, {"key": self.key})
        except Exception:
            logger.warning(
                "advisory lock 解锁失败（连接关闭即解锁，仅告警）：%s",
                self.key,
                exc_info=True,
            )
        finally:
            await self.conn.close()


async def try_acquire_task_lock(key: str) -> TaskMutex | None:
    """try-lock advisory lock：成功返回句柄（调用方负责随任务生命周期
    ``release``），被占返回 None（→ 409 TASK_CONFLICT 语义）。"""
    conn = await core_db.get_engine().connect()
    try:
        acquired = (await conn.execute(_TASK_TRY_LOCK_SQL, {"key": key})).scalar_one()
        if not acquired:
            await conn.close()
            return None
        # 结束获取语句的隐式事务（会话级锁不受事务结束影响）——避免句柄
        # 持有期连接滞留 idle in transaction
        await conn.rollback()
        return TaskMutex(key=key, conn=conn)
    except Exception:
        await conn.close()
        raise


async def running_task_hint(
    sess: AsyncSession,
    tenant_id: UUID,
    task_type: str,
    ref_name: str | None = None,
) -> UUID | None:
    """本租户同 task_type（可限 ref_name）最新 RUNNING 任务行 id——409
    envelope 的 current_task_hint 数据源（尽力：多副本下持锁方可能在别
    租户/副本，无可见行 → None）。"""
    stmt = (
        select(OpsTask.task_id)
        .where(
            OpsTask.tenant_id == tenant_id,
            OpsTask.task_type == task_type,
            OpsTask.status == "RUNNING",
        )
        .order_by(OpsTask.started_at.desc(), OpsTask.task_id.desc())
        .limit(1)
    )
    if ref_name is not None:
        stmt = stmt.where(OpsTask.ref_name == ref_name)
    return (await sess.execute(stmt)).scalar_one_or_none()


async def raise_task_conflict(
    sess: AsyncSession,
    tenant_id: UUID,
    task_type: str,
    ref_name: str | None = None,
) -> NoReturn:
    """锁被占 → 409 CONFLICT（复用既有码不扩错误码表——registry 乐观锁
    409 先例同构；message/extra 区分任务冲突语义）。三类任务入口共用
    （evidence/adapters_admin 经 service 路径调用）。"""
    key = task_lock_key(task_type, ref_name)
    hint = await running_task_hint(sess, tenant_id, task_type, ref_name)
    extra: dict = {"task_type": task_type}
    if ref_name is not None:
        extra["ref_name"] = ref_name
    if hint is not None:
        extra["current_task_hint"] = str(hint)
    raise EdpError.conflict(f"同类任务已在运行，请稍后再试：{key}", extra=extra)

# scope → 有序执行段（段名与 stats 键一致；coverage 无独立 scope——仅 ALL 覆盖）
_SCOPE_SEGMENTS: dict[str, tuple[str, ...]] = {
    "RECONCILE": ("reconciliation",),
    "ORPHAN": ("orphans",),
    "CHECKSUM": ("checksum",),
    "ALL": ("reconciliation", "coverage", "orphans", "checksum"),
}
_SEGMENT_LABELS = {
    "reconciliation": "对账",
    "coverage": "覆盖率",
    "orphans": "孤儿",
    "checksum": "抽检",
}

# create_task 强引用防 GC（官方建议模式，同 adapters_admin；完成回调自清理）
_recheck_tasks: set[asyncio.Task[None]] = set()

_EDP_COUNT_SQL = text("""
    SELECT source_system, object_type, count(*) AS n
    FROM master.business_objects
    GROUP BY source_system, object_type
""")

_COVERAGE_SQL = text("""
    SELECT t.object_type,
           count(*) AS registered,
           count(*) FILTER (WHERE t.connected) AS connected
    FROM (
        SELECT bo.object_type,
               (EXISTS (SELECT 1 FROM event.events e
                         WHERE e.object_id = bo.object_id)
                OR EXISTS (SELECT 1 FROM evidence.records r
                            WHERE r.object_id = bo.object_id)) AS connected
        FROM master.business_objects bo
    ) t
    GROUP BY t.object_type
    ORDER BY t.object_type
""")

_ORPHANS_SQL = text("""
    SELECT
        (SELECT count(*) FROM event.events e
          WHERE NOT EXISTS (SELECT 1 FROM master.business_objects bo
                             WHERE bo.object_id = e.object_id)) AS event_orphans,
        (SELECT count(*) FROM evidence.records r
          WHERE NOT EXISTS (SELECT 1 FROM master.business_objects bo
                             WHERE bo.object_id = r.object_id)) AS evidence_orphans,
        (SELECT count(*) FROM event.events) AS events_total,
        (SELECT count(*) FROM evidence.records) AS evidence_total
""")

# P0/P1 证据：event_id 列直关联或 links(ref_type='RESULT') 关联（结果证据
# 两条路径皆命中；快照证据不入选）
_CHECKSUM_SAMPLE_SQL = text("""
    SELECT r.evidence_id, r.object_id, r.checksum, r.snapshot, r.captured_at
    FROM evidence.records r
    WHERE r.event_id IN (SELECT e.event_id FROM event.events e
                          WHERE e.risk_level IN ('P0', 'P1'))
       OR r.evidence_id IN (
           SELECT l.evidence_id FROM evidence.links l
           JOIN event.events e ON e.event_id = l.ref_id
            AND e.risk_level IN ('P0', 'P1')
           WHERE l.ref_type = 'RESULT')
    ORDER BY r.captured_at DESC, r.evidence_id DESC
    LIMIT :limit
""")

# OPEN 异常（risk_level 非空且无已 DECIDED 关联案例——与 ebms exceptions
# 的 OPEN 判定同构：cases.source_id 存事件 id 文本，status='DECIDED'）
_EXCEPTION_COUNT_SQL = text("""
    SELECT
        count(*) FILTER (WHERE NOT EXISTS (
            SELECT 1 FROM decision.cases c
             WHERE c.tenant_id = e.tenant_id
               AND c.source_id = e.event_id::text
               AND c.status = 'DECIDED')) AS pending,
        count(*) FILTER (WHERE e.risk_level IN ('P0', 'P1')) AS high
    FROM event.events e
    WHERE e.risk_level IS NOT NULL
""")


@dataclass(frozen=True, slots=True)
class OrphanCounts:
    """孤儿段内部计数（孤儿两值 + 评分分母的总量两值）。"""

    event_orphans: int
    evidence_orphans: int
    events_total: int
    evidence_total: int


# ---- 纯派生函数（表驱动单测：tests/unit/test_quality_metrics.py） ----


def deviation_pct(source_count: int | None, edp_count: int) -> tuple[float, bool]:
    """对账偏差 → (deviation_pct, ok)。

    source 为 None/0 → (0.0, True)（real/无水位或零基数降级）；
    否则 pct = round(|source-edp|/source*100, 2)，ok 以四舍五入后的
    展示值判定（<= 2.0 边界含）——展示与判定一致。
    """
    if not source_count:
        return (0.0, True)
    pct = round(abs(source_count - edp_count) / source_count * 100, 2)
    return (pct, pct <= DEVIATION_THRESHOLD_PCT)


def coverage_pct(connected: int, registered: int) -> float:
    """覆盖率（已接入/注册，round 1 位）；registered=0 → 100.0（空集约定）。"""
    if not registered:
        return 100.0
    return round(connected / registered * 100, 1)


def score_from_anomaly_rate(bad: int, total: int) -> float:
    """段内评分：零异常=满分 100，按异常率线性扣减（round 1 位）；
    total=0 → 100.0（段内无数据视为无缺口）。"""
    if not total:
        return 100.0
    return round((1 - bad / total) * 100, 1)


def expected_source_counts() -> dict[tuple[str, str], int]:
    """适配器确定性数据集期望基数：(source_system, object_type) → 记录数。

    Mock 基线的「最小来源」——SNAPSHOT_RECORDS 常量分组计数（edp_adapters
    为外部包，模块间 import 约束不适用；与 demo seed 同一数据集）。
    """
    return dict(
        Counter(
            (record.source_system, record.object_type) for record in SNAPSHOT_RECORDS
        )
    )


def derive_dimensions(
    *,
    reconciliation: list[ReconciliationRow],
    coverage_overall: float,
    orphan_counts: OrphanCounts,
    sampling: ChecksumSampling,
) -> list[DimensionScore]:
    """四维度评分（每段 → 一条；段内零异常=满分 100，按异常率线性扣减）：

    - reconciliation：bad=ok=false 且有期望基数的组数 / total=有期望基数
      的组数（降级行 source_count=None 不计分母）；
    - coverage：= coverage.overall_pct（未接入率即扣减）；
    - orphans：bad=两类孤儿之和 / total=events+evidence 总行数；
    - checksum：bad=failed / total=sampled。
    """
    measurable = [row for row in reconciliation if row.source_count is not None]
    bad_groups = sum(1 for row in measurable if not row.ok)
    return [
        DimensionScore(
            domain="reconciliation",
            label="对账一致性",
            score_pct=score_from_anomaly_rate(bad_groups, len(measurable)),
        ),
        DimensionScore(
            domain="coverage",
            label="对象覆盖率",
            score_pct=coverage_overall,
        ),
        DimensionScore(
            domain="orphans",
            label="数据悬挂",
            score_pct=score_from_anomaly_rate(
                orphan_counts.event_orphans + orphan_counts.evidence_orphans,
                orphan_counts.events_total + orphan_counts.evidence_total,
            ),
        ),
        DimensionScore(
            domain="checksum",
            label="证据完整性",
            score_pct=score_from_anomaly_rate(sampling.failed, sampling.sampled),
        ),
    ]


def derive_kpi(
    *,
    dimensions: list[DimensionScore],
    coverage_overall: float,
    sampling: ChecksumSampling,
    pending_exceptions: int,
    high_priority: int,
) -> QualityKpi:
    """KPI 带派生：overall=四维度均分；sla=抽检通过率；completeness=
    coverage.overall_pct；pending/high 为计数透传。"""
    overall = (
        round(sum(item.score_pct for item in dimensions) / len(dimensions), 1)
        if dimensions
        else 100.0
    )
    return QualityKpi(
        overall_pct=overall,
        sla_pct=score_from_anomaly_rate(sampling.failed, sampling.sampled),
        completeness_pct=coverage_overall,
        pending_exceptions=pending_exceptions,
        high_priority=high_priority,
    )


# ---- 四段聚合（实时） ----


async def _reconciliation_rows(sess: AsyncSession) -> list[ReconciliationRow]:
    """对账段：DB 实际组 ∪ 期望基数组，按 (source_system, object_type) 排序。"""
    edp_counts = {
        (source_system, object_type): count
        for source_system, object_type, count in (
            await sess.execute(_EDP_COUNT_SQL)
        ).all()
    }
    expected = expected_source_counts()
    rows: list[ReconciliationRow] = []
    for group in sorted(set(edp_counts) | set(expected)):
        source_count = expected.get(group)
        edp_count = edp_counts.get(group, 0)
        pct, ok = deviation_pct(source_count, edp_count)
        rows.append(
            ReconciliationRow(
                source_system=group[0],
                object_type=group[1],
                source_count=source_count,
                edp_count=edp_count,
                deviation_pct=pct,
                ok=ok,
            )
        )
    return rows


async def build_coverage(sess: AsyncSession) -> CoverageReport:
    """覆盖率段（overall + by_type；/admin/quality/coverage 端点同形复用）。"""
    type_rows = (await sess.execute(_COVERAGE_SQL)).all()
    if not type_rows:
        return CoverageReport(overall_pct=100.0, by_type=[])
    return CoverageReport(
        overall_pct=coverage_pct(
            sum(row.connected for row in type_rows),
            sum(row.registered for row in type_rows),
        ),
        by_type=[
            CoverageByType(
                object_type=row.object_type,
                coverage_pct=coverage_pct(row.connected, row.registered),
            )
            for row in type_rows
        ],
    )


async def _orphan_counts(sess: AsyncSession) -> OrphanCounts:
    row = (await sess.execute(_ORPHANS_SQL)).one()
    return OrphanCounts(
        event_orphans=row.event_orphans,
        evidence_orphans=row.evidence_orphans,
        events_total=row.events_total,
        evidence_total=row.evidence_total,
    )


async def _checksum_sampling(
    sess: AsyncSession, principal: Principal
) -> ChecksumSampling:
    """抽检段：抽样重算比对；仅失配行落 quality.checksum_failed 事件。"""
    records = (
        await sess.execute(_CHECKSUM_SAMPLE_SQL, {"limit": CHECKSUM_SAMPLE_LIMIT})
    ).mappings().all()
    failed = 0
    for record in records:
        actual = evidence_service.compute_checksum(record["snapshot"])
        if actual == record["checksum"]:
            continue
        failed += 1
        await _record_checksum_failure(sess, principal, record, actual)
    return ChecksumSampling(sampled=len(records), failed=failed)


async def _record_checksum_failure(
    sess: AsyncSession,
    principal: Principal,
    record: Mapping,
    actual: str,
) -> None:
    """失配行 → quality.checksum_failed 事件（复用 events.ingest_batch，
    internal=True——W5-09 内部写入豁免计量：UUIDv5 幂等——occurred_at 取
    证据 captured_at、幂等键按 evidence_id 稳定，同失配重复抽检不重复
    落数；ingest 的审计/outbox 为既有副作用，计量随 internal 豁免）。"""
    await events_service.ingest_batch(
        sess,
        principal,
        f"quality-checksum:{record['evidence_id']}",
        [
            EventIn(
                event_type=CHECKSUM_FAILED_EVENT_TYPE,
                object_id=record["object_id"],
                source_system=CHECKSUM_FAILED_SOURCE_SYSTEM,
                occurred_at=record["captured_at"],
                actor_type="SERVICE",
                actor_id=CHECKSUM_FAILED_ACTOR_ID,
                data={
                    "evidence_id": str(record["evidence_id"]),
                    "expected": record["checksum"],
                    "actual": actual,
                },
            )
        ],
        internal=True,
    )


async def _exception_counts(sess: AsyncSession) -> tuple[int, int]:
    """(OPEN 异常数, P0/P1 风险事件数)——kpi.pending/high 数据源。"""
    row = (await sess.execute(_EXCEPTION_COUNT_SQL)).one()
    return (row.pending, row.high)


async def build_report(
    sess: AsyncSession, principal: Principal, *, report_date: str
) -> QualityReport:
    """四段实时聚合 + kpi/dimensions 组装（date 原样回显，不回溯）。"""
    reconciliation = await _reconciliation_rows(sess)
    coverage = await build_coverage(sess)
    orphan_counts = await _orphan_counts(sess)
    sampling = await _checksum_sampling(sess, principal)
    pending, high = await _exception_counts(sess)
    dimensions = derive_dimensions(
        reconciliation=reconciliation,
        coverage_overall=coverage.overall_pct,
        orphan_counts=orphan_counts,
        sampling=sampling,
    )
    kpi = derive_kpi(
        dimensions=dimensions,
        coverage_overall=coverage.overall_pct,
        sampling=sampling,
        pending_exceptions=pending,
        high_priority=high,
    )
    return QualityReport(
        date=report_date,
        reconciliation=reconciliation,
        coverage=coverage,
        orphans=OrphansReport(
            event_orphans=orphan_counts.event_orphans,
            evidence_orphans=orphan_counts.evidence_orphans,
        ),
        checksum_sampling=sampling,
        kpi=kpi,
        dimensions=dimensions,
    )


# ---- 任务轨道（EDP-030 下半，T4）----


async def start_recheck(
    sess: AsyncSession, principal: Principal, *, scope: str
) -> OpsTask:
    """登记 quality_recheck 任务行并派发后台执行（路由层 202 语义）。

    **任务互斥（W6 T3）**：入口先 ``try_acquire_task_lock``——被占 →
    409 CONFLICT（不登记行）；拿到锁才建行/派发，锁句柄随后台执行体走
    （执行体 finally 释放，见 ``TaskMutex`` docstring）。状态落库多副本
    安全（行级回写、终态幂等）。任务行可见性由请求级 commit 兜底，后台
    执行体先等行可见再执行（见 ``_run_recheck`` docstring）。
    """
    mutex = await try_acquire_task_lock(task_lock_key(RECHECK_TASK_TYPE))
    if mutex is None:
        await raise_task_conflict(sess, principal.tenant_id, RECHECK_TASK_TYPE)
    try:
        started_at = datetime.now(UTC)
        task = OpsTask(
            task_id=uuid4(),
            tenant_id=principal.tenant_id,
            task_type=RECHECK_TASK_TYPE,
            status="RUNNING",
            scope=scope,
            started_at=started_at,
            created_by=principal.id,
        )
        sess.add(task)
        await sess.flush()  # 审计 TASK_CREATE 随请求事务落库
        background = asyncio.create_task(
            _run_recheck(
                task_id=task.task_id,
                tenant_id=principal.tenant_id,
                principal=principal,
                scope=scope,
                started_at=started_at,
                mutex=mutex,
            )
        )
        _recheck_tasks.add(background)
        background.add_done_callback(_recheck_tasks.discard)
    except Exception:
        await mutex.release()  # 登记/派发失败就地释放（后台未接手）
        raise
    return task


async def get_task(sess: AsyncSession, task_id: UUID) -> OpsTask | None:
    """任务行查询（RLS 会话——跨租户行不可见 → None → 路由层 404）。"""
    return (
        await sess.execute(select(OpsTask).where(OpsTask.task_id == task_id))
    ).scalar_one_or_none()


async def _run_recheck(
    *,
    task_id: UUID,
    tenant_id: UUID,
    principal: Principal,
    scope: str,
    started_at: datetime,
    mutex: TaskMutex | None = None,
) -> None:
    """后台执行体：独立会话逐段执行 T3 聚合 → stats/logs 落 ops.tasks →
    终态 + 完成事件。

    互斥锁：入口已取得的 ``mutex`` 句柄随执行体走——**finally 释放**
    （任务终态/提前退出均达）；缺省 None 容忍直接调用（测试竞态用例直调
    本体，无锁语境）。

    会话与事务：不复用请求会话（随请求关闭）——经 get_session_local 开
    独立会话；bind_tenant 事务级（set_config is_local）→ 每段独立事务
    （段间 commit 落进度，段前重绑）。首段前可见性有界重试
    （``wait_task_visible`` 公共 helper）：READ COMMITTED 下请求事务未提交的
    INSERT 行不可见且 FOR UPDATE 对不存在的行不等待——后台先于请求
    commit 启动时首次探测读空属正常，重试至行可见再执行；deadline 后
    仍不可见 = 请求事务已回滚（行不存在 → 提前退出，无处回写终态）。

    失败语义：任一段异常 → 整任务 FAILED（已完成段的进度已逐段落库，
    失败段不落 stats）；FAILED 回写经独立事务尽力落库（回写自身异常仅
    告警）。完成事件（succeeded/failed）移出终态事务：终态先行 commit，
    事件随后独立事务尽力写入（事件失败仅告警——成功计算不因事件通道
    异常改判 FAILED）。
    """
    factory = core_db.get_session_local()
    stats: dict[str, dict] = {}
    logs: list[dict] = [_log_line("INFO", f"任务启动：scope={scope}")]
    try:
        async with factory() as sess:
            if not await wait_task_visible(sess, tenant_id, task_id):
                logger.warning(
                    "recheck 任务行 %d 次探测均不可见（deadline 后仍不可见，"
                    "请求事务已回滚）：%s",
                    TASK_VISIBILITY_ATTEMPTS,
                    task_id,
                )
                return
            for segment in _SCOPE_SEGMENTS[scope]:
                await core_db.bind_tenant(sess, tenant_id)
                await _run_segment(sess, principal, segment, stats, logs)
                await _apply_task(
                    sess,
                    task_id,
                    stats=dict(stats),
                    logs=list(logs),
                    actor=principal.id,
                )
                await sess.commit()
            await core_db.bind_tenant(sess, tenant_id)
            finished_at = datetime.now(UTC)
            logs.append(_log_line("INFO", "任务完成：SUCCEEDED"))
            await _apply_task(
                sess,
                task_id,
                stats=dict(stats),
                logs=list(logs),
                actor=principal.id,
                status="SUCCEEDED",
                finished_at=finished_at,
            )
            await sess.commit()  # 终态先行落库——完成事件失败不回滚成功计算
        await _record_completion_event(
            factory,
            tenant_id,
            principal,
            task_id=task_id,
            scope=scope,
            started_at=started_at,
            event_type=RECHECK_SUCCEEDED_EVENT_TYPE,
            stats=stats,
        )
    except Exception as exc:
        logger.error("质量重校验任务失败：%s（scope=%s）", task_id, scope, exc_info=True)
        try:
            async with factory() as sess:
                await core_db.bind_tenant(sess, tenant_id)
                error = str(exc)[:500]
                logs.append(_log_line("ERROR", f"任务失败：{exc!r}"))
                await _apply_task(
                    sess,
                    task_id,
                    stats=dict(stats),
                    logs=list(logs),
                    actor=principal.id,
                    status="FAILED",
                    finished_at=datetime.now(UTC),
                )
                await sess.commit()  # FAILED 终态先行落库
            await _record_completion_event(
                factory,
                tenant_id,
                principal,
                task_id=task_id,
                scope=scope,
                started_at=started_at,
                event_type=RECHECK_FAILED_EVENT_TYPE,
                stats=stats,
                error=error,
            )
        except Exception:
            logger.error("recheck FAILED 终态回写失败：%s", task_id, exc_info=True)
    finally:
        if mutex is not None:
            await mutex.release()  # 互斥窗 = 入口取锁至执行体收尾（终态/提前退出均达）


async def wait_task_visible(
    sess: AsyncSession, tenant_id: UUID, task_id: UUID
) -> bool:
    """任务行可见性有界重试（T4 评审 Important-1 修正；**单一公共实现**）。

    READ COMMITTED 下请求事务**未提交**的 ops.tasks INSERT 行对本会话
    不可见，且 ``SELECT ... FOR UPDATE`` 对不可见（尚不存在）的行不
    阻塞、立即返回空——时序上后台执行体可能先于请求事务 commit 启动，
    首次探测读空属正常，不构成「请求事务已回滚」的证据。故按
    ``TASK_VISIBILITY_INTERVAL_S`` 间隔重试探测直至行可见（此时请求
    事务已提交）再放行执行；仅当 ``TASK_VISIBILITY_ATTEMPTS`` 次
    （deadline ≈1s）探测后仍不可见才判定请求事务已回滚——此时行确不
    存在，诊断成立。

    bind_tenant 事务级（set_config is_local）→ 每次探测独立事务、逐次
    重绑（探测为只读 SELECT，commit 即结束探测事务）。

    **放置点留痕（W5 T5 评审移交，T6 收口）**：T4/T5 各留一份私有复制
    （quality.service / adapters_admin.service），T6 evidence reindex 将
    出现第三处消费——故抽为公开单一实现于本模块（ops.tasks ORM 映射
    亦在本模块 family 内，adapters_admin 已循 ``service→service`` 路径
    引 OpsTask），adapters_admin.service / evidence.service 改为 import
    本函数；不再新增 modules/ops 小模块（OpsTask 映射仍在 quality.models，
    拆小模块会造成 quality↔ops 新循环且无独立演进诉求）。
    """
    for attempt in range(1, TASK_VISIBILITY_ATTEMPTS + 1):
        await core_db.bind_tenant(sess, tenant_id)
        visible = (
            await sess.execute(
                select(OpsTask.task_id).where(OpsTask.task_id == task_id)
            )
        ).scalar_one_or_none()
        await sess.commit()
        if visible is not None:
            return True
        if attempt < TASK_VISIBILITY_ATTEMPTS:
            logger.info(
                "任务行暂不可见（请求事务未提交，重试 %d/%d）：%s",
                attempt,
                TASK_VISIBILITY_ATTEMPTS,
                task_id,
            )
            await asyncio.sleep(TASK_VISIBILITY_INTERVAL_S)
    return False


async def _record_completion_event(
    factory: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    principal: Principal,
    *,
    task_id: UUID,
    scope: str,
    started_at: datetime,
    event_type: str,
    stats: dict,
    error: str | None = None,
) -> None:
    """完成事件移出终态事务（T4 评审 Minor）：终态已先行 commit，事件
    经独立会话/事务尽力写入——ingest 抛错仅告警不回滚，已落的终态
    （如 SUCCEEDED）不因事件通道异常改判 FAILED。"""
    try:
        async with factory() as sess:
            await core_db.bind_tenant(sess, tenant_id)
            await _record_recheck_event(
                sess,
                principal,
                task_id=task_id,
                scope=scope,
                started_at=started_at,
                event_type=event_type,
                stats=stats,
                error=error,
            )
            await sess.commit()
    except Exception:
        logger.error(
            "recheck 完成事件写入失败（终态已落库，仅告警）：%s", task_id, exc_info=True
        )


async def _run_segment(
    sess: AsyncSession,
    principal: Principal,
    segment: str,
    stats: dict[str, dict],
    logs: list[dict],
) -> None:
    """执行单段（复用 T3 聚合函数）→ stats 结果摘要 + logs 起止/关键计数。

    段函数按模块全局名直调——测试 monkeypatch 段函数即可构造 FAILED 路径。
    """
    label = _SEGMENT_LABELS[segment]
    logs.append(_log_line("INFO", f"{label}段开始"))
    if segment == "reconciliation":
        rows = await _reconciliation_rows(sess)
        bad = sum(1 for row in rows if row.source_count is not None and not row.ok)
        stats[segment] = {"groups": len(rows), "bad_groups": bad}
        done = f"{label}段完成：组数 {len(rows)}，超差组 {bad}"
    elif segment == "coverage":
        coverage = await build_coverage(sess)
        stats[segment] = {"overall_pct": coverage.overall_pct}
        done = f"{label}段完成：overall {coverage.overall_pct}%"
    elif segment == "orphans":
        counts = await _orphan_counts(sess)
        stats[segment] = {
            "event_orphans": counts.event_orphans,
            "evidence_orphans": counts.evidence_orphans,
        }
        done = (
            f"{label}段完成：事件悬挂 {counts.event_orphans}，"
            f"证据悬挂 {counts.evidence_orphans}"
        )
    else:
        sampling = await _checksum_sampling(sess, principal)
        stats[segment] = {"sampled": sampling.sampled, "failed": sampling.failed}
        done = f"{label}段完成：抽样 {sampling.sampled}，失配 {sampling.failed}"
    logs.append(_log_line("INFO", done))


async def _apply_task(
    sess: AsyncSession,
    task_id: UUID,
    *,
    stats: dict,
    logs: list[dict],
    actor: str,
    status: str | None = None,
    finished_at: datetime | None = None,
) -> None:
    """ops.tasks 回写（不 commit——事务边界在调用方）。stats/logs 整行
    重赋值（JSONB 原位修改对 ORM 变更检测不可见）；行不存在（请求事务
    回滚）静默跳过——审计 TASK_UPDATE 随调用方事务落库。"""
    task = (
        await sess.execute(select(OpsTask).where(OpsTask.task_id == task_id))
    ).scalar_one_or_none()
    if task is None:
        return
    task.stats = stats
    task.logs = logs
    task.updated_by = actor
    if status is not None:
        task.status = status
        task.finished_at = finished_at


async def _record_recheck_event(
    sess: AsyncSession,
    principal: Principal,
    *,
    task_id: UUID,
    scope: str,
    started_at: datetime,
    event_type: str,
    stats: dict,
    error: str | None = None,
) -> None:
    """完成事件（复用 events.ingest_batch，internal=True——W5-09 内部
    写入豁免计量；同 T3 checksum_failed 写通道）：UUIDv5 幂等
    （occurred_at=任务 started_at → 同任务重放恒同 event_id；
    幂等键 quality-recheck:{task_id}）；审计/outbox 为既有副作用随本
    事务提交（调用方 ``_record_completion_event`` 开独立尽力事务——终态
    已先行落库，本写失败仅告警不回滚）。

    事件 object 锚点 = 注册表最小 object_id（ORDER BY LIMIT 1——PG 无
    min(uuid) 聚合；ingest 通道校验 object 存在性——质量完成事件无自然
    业务对象，取租户内确定性锚点；空注册表 → 跳过事件，结果已由任务行
    stats/logs 留痕）。
    """
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
    data: dict = {"task_id": str(task_id), "scope": scope, "stats": stats}
    if error is not None:
        data["error"] = error
    await events_service.ingest_batch(
        sess,
        principal,
        f"quality-recheck:{task_id}",
        [
            EventIn(
                event_type=event_type,
                object_id=anchor,
                source_system=RECHECK_EVENT_SOURCE_SYSTEM,
                occurred_at=started_at,
                actor_type="SERVICE",
                actor_id=RECHECK_EVENT_ACTOR_ID,
                data=data,
            )
        ],
        internal=True,
    )


def _log_line(level: str, message: str) -> dict:
    """log 行（形状对齐 mocks/types.ts QualityTask.logs：{ts, level, message}）。"""
    return {"ts": datetime.now(UTC).isoformat(), "level": level, "message": message}


# ---- outbox 状态聚合（W5-05 收口：GET /admin/outbox/status 数据源） ----


async def build_outbox_status(sess: AsyncSession) -> OutboxStatusOut:
    """outbox 状态响应（数据源 = events.service.outbox_status——outbox ORM
    归 events 模块，模块间仅 service）；last_published_at ISO 串化输出。"""
    status = await events_service.outbox_status(sess)
    return OutboxStatusOut(
        pending_count=status.pending_count,
        oldest_pending_age_seconds=status.oldest_pending_age_seconds,
        published_last_hour=status.published_last_hour,
        dlq_count=status.dlq_count,
        last_published_at=(
            status.last_published_at.isoformat()
            if status.last_published_at is not None
            else None
        ),
    )


# ---- 演练记录只读归档（EDP-502 后端 / W5 T7）----

# 默认仓库相对路径（相对 cwd 解析——开发/CLI 场景 cwd=仓库根）；容器内
# 该路径不存在，经卷挂载 + EDP_DRILLS_FILE 指向挂载点（staging compose
# 注释 T14 处理）；测试以 monkeypatch setenv 指向 tmp_path 临时文件
DRILLS_FILE_ENV = "EDP_DRILLS_FILE"
DEFAULT_DRILLS_FILE = "deploy/drills/drill-records.json"


def list_drills() -> list[DrillRecord]:
    """读 drill-records.json → DrillRecord 列表（演练线唯一写者，API 只读）。

    每请求直读不做 mtime 缓存：文件 KB 级、读开销可忽略，免缓存失效
    复杂度，T14~T16 回填后新值即时可见。

    容错（只读归档面不 500，前端空态）：文件缺失/不可读/坏 JSON/顶层
    结构不符 → []；单项 schema 不符 → 跳过该项（手工回填防误伤全列表）。
    """
    path = Path(os.environ.get(DRILLS_FILE_ENV, DEFAULT_DRILLS_FILE))
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("演练记录文件不可读（缺失/坏 JSON → 空列表）：%s", path)
        return []
    items = doc.get("items") if isinstance(doc, dict) else None
    if not isinstance(items, list):
        logger.warning("演练记录顶层结构不符（缺 items 数组 → 空列表）：%s", path)
        return []
    records: list[DrillRecord] = []
    for item in items:
        try:
            records.append(DrillRecord.model_validate(item))
        except ValidationError:
            logger.warning("演练记录单项不符 schema，跳过：%r", item)
    return records
