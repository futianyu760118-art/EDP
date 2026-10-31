"""demo 服务（EDP-016，T7）：演示数据 seed——幂等重放 + 演示复位。

seed = 快照段（erp-demo/plm-demo → 管道）+ 回流段（events/batch + 场景 2
案例）+ 确定性回填接入耗时；时间基准 = 租户演示锚（tenants.attributes.
demo_seed.anchor）：resolve_anchor 命中复用，缺失则 now(UTC) 截整点写入。

幂等（spec §3.5）：
- 快照段：锚复用 → 同记录恒同 event_id（UUIDv5）→ 全 duplicated、不推
  revision、不重复投影；
- 回流段：稳定幂等键 seed-demo:results:v1 → 幂等键 TTL 内归档命中直接
  返回存档响应（本批 0 新增），过期后仍靠 event_id 收敛为 duplicated——
  两条路径的统计口径统一为「本次实际写入」；
- 案例：按 (source_type, source_id=源结果事件 id) 已存在即跳过；
- management 段（W4）：行 id = uuid5(NIL, "seed-mgmt:...")，ON CONFLICT DO
  NOTHING upsert——锚复用 → 同 period 同 id → 重跑 0 新增。

复位（reset=True）：逆依赖序清本租户业务数据（不碰审计，spec §3.3）+
重锚后重建。

快照段顺序（T5/T6 评审硬约束）：**不得按适配器分别 run_sync_per_record**
——跨适配器依赖 ORDER(erp)→PRODUCT(plm)、BOM(plm)→MATERIAL(erp) 在分
适配器两遍扫描下总有一遍先到而自然键尚未注册（duplicated 提前 return 使
投影永不重做），FK 被永久固化为 NULL。故取两适配器记录后按
SNAPSHOT_RECORDS 全局序（数据集本为依赖序）归并，逐条独立事务处理
（单条失败 failed+1 记日志继续，不连坐批次）；水位仍按适配器分别推进
（systems 行 name=erp-demo/plm-demo，复用 ingest 水位助手保持与 run_sync
同一 ORM 写回路径与审计口径）。

案例创建说明（T10 起）：_ensure_demo_case 经 decisions_service.find_case_by_source/
create_case（ORM + 审计切面，替代 T7 的 raw SQL 直写——评审 Important）；context
按 B.5 并入 source_event_id（T5 评审 Minor-4，seed 时由派生 event_id 回填）。

放大段（W6 T5，EDP-033 压测前置）：seed(scale=N)，N>1 时在基线外**追加**
确定性放大实体——每单元（1..N-1）= 基线快照数据集的自洽副本：source_id 与
payload 内 *_code 引用统一追加 scale_suffix(unit)（6 位数字，见 dataset 尾段
约定——T12 运营报告按 ``source_id ~ '-[0-9]{6}$'`` 在 SQL 侧排除放大实体，
事件/证据经 object_id join business_objects 同式过滤）；occurred_at 按单元
+unit 分钟确定性平移 → 同锚重放恒同 UUIDv5 → 幂等（duplicated 收敛）。
每放大对象另追加 SCALE_ACTIVITY_PER_OBJECT 条活动事件（event_type=
``{类型小写}.activity``，risk_level 稀疏 P0/P1 分布）与 checksum 证据
（verify 场景）。十类场景本体（RESULT_EVENTS/DEMO_CASE/management 段）
不放大。写入分批：快照段沿用逐条独立事务（最细分批）；活动段批量 INSERT
每批 ≤ SCALE_BATCH_SIZE 行（防单事务过大）。量级换算：基线 43 对象 /
53 事件 / 53 证据，每单元追加 43 对象 + 430 事件（43 快照 + 43×9 活动）+
86 证据（+稀疏风险证据）——目标量级 ≈5k 对象 / 50k 事件 / 10k 证据对应
**N=116**（≈4988 对象 / 49503 事件 / 10033 证据）。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from edp_adapters import DemoErpAdapter, DemoMesAdapter, DemoPlmAdapter
from edp_adapters.base import SourceRecord
from edp_adapters.demo_dataset import SNAPSHOT_RECORDS
from edp_adapters.demo_erp import SOURCE_SYSTEM as ERP_SOURCE_SYSTEM
from edp_adapters.demo_plm import SOURCE_SYSTEM as PLM_SOURCE_SYSTEM
from edp_adapters.mes_mock import SOURCE_SYSTEM as MES_SOURCE_SYSTEM
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from edp_api.core.contextvars import current_principal
from edp_api.core.db import bind_tenant
from edp_api.modules.decisions import service as decisions_service
from edp_api.modules.decisions.schemas import CaseCreateRequest, CaseOptionIn
from edp_api.modules.demo.dataset import (
    DEMO_CASE,
    MGMT_KPI_DEFINITIONS,
    MGMT_KPI_VALUES,
    MGMT_OBJECTIVES,
    RESULT_EVENTS,
    SCALE_ACTIVITY_PER_OBJECT,
    ResultEventSpec,
    scale_suffix,
    scaled_activity_event_type,
    scaled_risk_level,
)
from edp_api.modules.events import service as events_service
from edp_api.modules.events.schemas import EventIn
from edp_api.modules.events.uuidv5 import derive_event_id
from edp_api.modules.evidence import service as evidence_service
from edp_api.modules.ingest import service as ingest_service
from edp_api.modules.projections import service as projections_service
from edp_api.modules.tenantmgmt import service as tenantmgmt_service

logger = logging.getLogger(__name__)

DEFAULT_TENANT_SLUG = "default"

# NIL 命名空间（Python 3.12 的 uuid 模块尚无 NIL 常量）
_NIL = UUID(int=0)

# 回流段接口层幂等键（spec §3.3：稳定键，重放命中归档）
DEMO_RESULTS_IDEM_KEY = "seed-demo:results:v1"
# 案例来源类型（与 decisions 模块 T10 的 source_type 约定一致）
CASE_SOURCE_TYPE = "capability.result"
# 接入耗时确定性回填区间（ms）：60~299
LATENCY_FLOOR_MS = 60
LATENCY_SPAN_MS = 240
# management 段审计列（raw SQL 写不经 ORM 切面，显式置服务主体）
MGMT_ACTOR_ID = "adapter:erp"
# kpi_values.source 标记（演示 seed 来源）
MGMT_VALUE_SOURCE = "seed-mgmt"
# 放大段批量 INSERT 每批行数上限（防单事务过大；快照段沿用逐条独立事务）
SCALE_BATCH_SIZE = 1000
# 放大风险活动事件的确定性评分（对齐基线场景 P0/P1 量级）
_SCALE_RISK_SCORES = {"P0": 0.93, "P1": 0.86}
# 放大活动事件相对对象快照时刻的回溯步长（30 分钟 × (k+1)，保持发生于过去）
_SCALE_ACTIVITY_STEP_MINUTES = 30


@dataclass(slots=True)
class SeedStats:
    """seed 计数：快照段 fetched/registered/duplicated/failed + 回流段
    events_accepted/events_duplicated + case_created + management 段
    mgmt_inserted。

    events_* 为「本次实际写入」口径：归档命中（24h TTL 内）时存档响应中的
    accepted 计入 duplicated（本批 0 新增），与 event_id 幂等路径
    （accepted=0, duplicated=9）数值一致——两条重放路径统计可互换。
    mgmt_inserted 同理为本次实际插入行数（首跑 12 = 3 objectives + 3
    definitions + 6 values；锚复用重跑 0）。
    """

    fetched: int = 0
    registered: int = 0
    duplicated: int = 0
    failed: int = 0
    events_accepted: int = 0
    events_duplicated: int = 0
    case_created: bool = False
    mgmt_inserted: int = 0


def _truncate_to_hour(value: datetime) -> datetime:
    """截整点（UTC；演示锚粒度）。"""
    return value.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


async def resolve_anchor(sess: AsyncSession, tenant_id: UUID) -> datetime:
    """租户演示锚：命中复用；缺失则 now(UTC) 截整点写入后返回。"""
    anchor = await tenantmgmt_service.get_demo_anchor(sess, tenant_id)
    if anchor is not None:
        return anchor
    anchor = _truncate_to_hour(datetime.now(UTC))
    await tenantmgmt_service.set_demo_anchor(sess, tenant_id, anchor)
    return anchor


def merged_snapshot_records(anchor: datetime) -> list[SourceRecord]:
    """按 SNAPSHOT_RECORDS 全局序归并 erp-demo/mes-demo/plm-demo 记录（依赖序）。

    三适配器各自的 fetch_full 保持数据集内部顺序，归并后即全局依赖序：
    客户/物料/产品/供应商 → 订单/采购/BOM/交期/库存 → 项目+里程碑 → 产能。
    """
    by_system: dict[str, dict[str, SourceRecord]] = {
        ERP_SOURCE_SYSTEM: {
            record.source_id: record
            for record in DemoErpAdapter().fetch_full([], anchor=anchor)
        },
        MES_SOURCE_SYSTEM: {
            record.source_id: record
            for record in DemoMesAdapter().fetch_full([], anchor=anchor)
        },
        PLM_SOURCE_SYSTEM: {
            record.source_id: record
            for record in DemoPlmAdapter().fetch_full([], anchor=anchor)
        },
    }
    return [by_system[spec.source_system][spec.source_id] for spec in SNAPSHOT_RECORDS]


def _scaled_payload(payload: dict, suffix: str) -> dict:
    """payload 副本 + ``*_code`` 自然键引用统一追加后缀（含 lines/items 行内）。

    单元内自洽引用图：放大订单引用同单元放大客户/产品/物料——领域投影 FK
    在单元内解析（依赖序与 SNAPSHOT_RECORDS 全局序一致）。
    """
    scaled: dict = {}
    for key, value in payload.items():
        if key.endswith("_code") and isinstance(value, str):
            scaled[key] = f"{value}{suffix}"
        elif isinstance(value, list):
            scaled[key] = [
                _scaled_payload(item, suffix) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            scaled[key] = value
    return scaled


def scaled_source_records(anchor: datetime, scale: int) -> list[SourceRecord]:
    """--scale N 放大快照记录（单元 1..N-1 × SNAPSHOT_RECORDS 依赖序）。

    每单元 = 基线数据集的自洽副本：source_id / *_code 引用追加
    scale_suffix(unit)；occurred_at 按单元 +unit 分钟确定性平移（UUIDv5
    输入确定性 + 产能快照 uq(tenant, line, period, snapshot_at) 逐单元错开）。
    """
    if scale <= 1:
        return []
    records: list[SourceRecord] = []
    for unit in range(1, scale):
        suffix = scale_suffix(unit)
        shift = timedelta(minutes=unit)
        for spec in SNAPSHOT_RECORDS:
            records.append(
                SourceRecord(
                    source_system=spec.source_system,
                    object_type=spec.object_type,
                    source_id=f"{spec.source_id}{suffix}",
                    occurred_at=anchor
                    + timedelta(minutes=spec.offset_minutes)
                    + shift,
                    payload=_scaled_payload(spec.payload, suffix),
                )
            )
    return records


# 逆依赖序清场（子表 → 父表）：management（W4 独立段——kpi_values →
# kpi_definitions 先于 objectives 无 FK 关联，且 management 无 FK 到领域表，
# 放最前自成一段）→ decision/action → evidence → event → sales →
# delivery/rd/quality/finance/support（FK 指向 business_objects/customers 的
# 其余域表一并清，防残留行阻断父表删除）→ master（bom_items/boms 先于
# products）→ business_objects → systems/idempotency_keys。
# 不含 audit_logs（仅追加）与 tenants 控制面（spec §3.3）。
_PURGE_SQL: tuple[str, ...] = (
    # management 段（W4）：RESET 后 KPI/目标不残留旧锚期数
    "DELETE FROM management.kpi_values WHERE tenant_id = :t",
    "DELETE FROM management.kpi_definitions WHERE tenant_id = :t",
    "DELETE FROM management.objectives WHERE tenant_id = :t",
    # governance 段（V1.2 0014）：先子后父（review→admission→classification；
    # clean_records 引用 raw_records + business_objects → 先于两者删）
    "DELETE FROM governance.review_records WHERE tenant_id = :t",
    "DELETE FROM governance.admission_records WHERE tenant_id = :t",
    "DELETE FROM governance.object_classifications WHERE tenant_id = :t",
    "DELETE FROM governance.object_tags WHERE tenant_id = :t",
    "DELETE FROM governance.lineage WHERE tenant_id = :t",
    "DELETE FROM governance.clean_records WHERE tenant_id = :t",
    "DELETE FROM governance.raw_records WHERE tenant_id = :t",
    "DELETE FROM governance.taxonomies WHERE tenant_id = :t",
    "DELETE FROM governance.entity_aliases WHERE tenant_id = :t",
    "DELETE FROM governance.dimensions WHERE tenant_id = :t",
    "DELETE FROM governance.tags WHERE tenant_id = :t",
    "DELETE FROM governance.cleaning_rules WHERE tenant_id = :t",
    # result 段（V1.2 0015）：引用 business_objects → 先于其删
    "DELETE FROM result.results WHERE tenant_id = :t",
    # metric/value 段（V1.2 0016）：先子后父（values→metrics；value_ledger 独立）
    "DELETE FROM metric.metric_values WHERE tenant_id = :t",
    "DELETE FROM metric.metrics WHERE tenant_id = :t",
    "DELETE FROM value.value_ledger WHERE tenant_id = :t",
    "DELETE FROM decision.records WHERE tenant_id = :t",
    "DELETE FROM action.actions WHERE tenant_id = :t",
    "DELETE FROM decision.cases WHERE tenant_id = :t",
    "DELETE FROM evidence.links WHERE tenant_id = :t",
    "DELETE FROM evidence.records WHERE tenant_id = :t",
    "DELETE FROM event.outbox WHERE tenant_id = :t",
    "DELETE FROM event.events WHERE tenant_id = :t",
    "DELETE FROM sales.order_lines WHERE tenant_id = :t",
    "DELETE FROM sales.orders WHERE tenant_id = :t",
    "DELETE FROM delivery.inventory WHERE tenant_id = :t",
    "DELETE FROM delivery.purchase_orders WHERE tenant_id = :t",
    "DELETE FROM delivery.supplier_lead_times WHERE tenant_id = :t",
    "DELETE FROM delivery.capacity WHERE tenant_id = :t",
    "DELETE FROM rd.milestones WHERE tenant_id = :t",
    "DELETE FROM rd.projects WHERE tenant_id = :t",
    "DELETE FROM quality.inspections WHERE tenant_id = :t",
    "DELETE FROM quality.exceptions WHERE tenant_id = :t",
    "DELETE FROM finance.receivables WHERE tenant_id = :t",
    "DELETE FROM support.tickets WHERE tenant_id = :t",
    "DELETE FROM master.bom_items WHERE tenant_id = :t",
    "DELETE FROM master.boms WHERE tenant_id = :t",
    "DELETE FROM master.customers WHERE tenant_id = :t",
    "DELETE FROM master.materials WHERE tenant_id = :t",
    "DELETE FROM master.products WHERE tenant_id = :t",
    "DELETE FROM master.suppliers WHERE tenant_id = :t",
    "DELETE FROM master.business_objects WHERE tenant_id = :t",
    "DELETE FROM platform.systems WHERE tenant_id = :t",
    "DELETE FROM platform.idempotency_keys WHERE tenant_id = :t",
    # T7 评审 Important：计量行不清则 RESET 后 KPI/幂等命中率翻倍累计
    "DELETE FROM platform.tenant_usage_daily WHERE tenant_id = :t",
)


async def purge_tenant_business_data(sess: AsyncSession, tenant_id: UUID) -> None:
    """逆依赖序清本租户业务数据（不重锚、不碰审计）——seed 复位与集成测试
    清场共用（T4 评审：清场须先子后父，否则 FK 阻断）。调用方负责事务提交。
    """
    for sql in _PURGE_SQL:
        await sess.execute(text(sql), {"t": tenant_id})


async def _reset_tenant_data(
    sess: AsyncSession, tenant_id: UUID, *, anchor: datetime | None = None
) -> None:
    """清场 + 重锚（缺省 now 截整点；显式 anchor 供 E2E visual 固定基线，W6 T11）。

    显式 anchor 不截整点（调用方传确定值，如 CI seed --anchor）；后续
    resolve_anchor 复用该锚。
    """
    await purge_tenant_business_data(sess, tenant_id)
    await tenantmgmt_service.set_demo_anchor(
        sess,
        tenant_id,
        _truncate_to_hour(datetime.now(UTC)) if anchor is None else anchor,
    )


async def seed(
    engine: AsyncEngine,
    tenant_id: UUID,
    *,
    reset: bool = False,
    scale: int = 1,
    anchor: datetime | None = None,
) -> SeedStats:
    """演示数据 seed（幂等重放 / reset 复位重建 / scale 放大）。

    anchor（W6 T11，EDP-603）：显式演示锚（配合 --reset 使用）——E2E 视觉
    回归要求跨环境/跨次运行的页面时间文本确定：锚固定则全部 occurred_at/
    updated_at 派生展示（relTime 超过 30 天回退绝对日期）逐字节一致。缺省
    不传保持既有语义（reset 重锚 now 截整点；非 reset 复用存量锚）。

    事务边界：快照段（基线 + 放大）逐条独立事务（单条失败隔离）；水位按
    适配器独立短事务；回流段（batch + 案例）单事务；放大活动段批量 INSERT
    每批 ≤ SCALE_BATCH_SIZE 行独立事务；接入耗时回填独立短事务。

    scale（W6 T5）：1 = 十类场景基线（行为不变）；N>1 在基线外追加 N-1 份
    确定性放大实体（模块 docstring「放大段」），十类场景本体不放大。幂等：
    同 scale 重放计数不变（UUIDv5 + 确定性 evidence_id 收敛为 duplicated）；
    --reset 清场后按请求 scale 重建（降 scale 即回到较小规模）。
    """
    if scale < 1:
        raise ValueError(f"scale 必须 ≥ 1：{scale}")
    if anchor is not None and not reset:
        raise ValueError("anchor 仅在 --reset 时生效（非 reset 复用存量锚）")
    token = current_principal.set(ingest_service.service_principal(tenant_id))
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        if reset:
            async with factory.begin() as sess:
                await bind_tenant(sess, tenant_id)
                await _reset_tenant_data(sess, tenant_id, anchor=anchor)

        async with factory.begin() as sess:
            anchor = await resolve_anchor(sess, tenant_id)

        stats = SeedStats()
        records = merged_snapshot_records(anchor)
        scaled = scaled_source_records(anchor, scale)
        stats.fetched = len(records) + len(scaled)
        await _run_snapshot(factory, tenant_id, records + scaled, stats)
        await _advance_watermarks(factory, tenant_id, records + scaled)
        await _run_result_events(factory, tenant_id, anchor, stats)
        await _run_scale_activity(factory, tenant_id, anchor, scale, stats)
        await _run_management_seed(factory, tenant_id, anchor, stats)
        await _apply_demo_latency(factory, tenant_id, records + scaled)
        return stats
    finally:
        current_principal.reset(token)


async def _run_snapshot(
    factory: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    records: list[SourceRecord],
    stats: SeedStats,
) -> None:
    """逐条独立事务处理快照记录（全局依赖序）；单条失败仅回滚该条。"""
    for record in records:
        try:
            async with factory.begin() as sess:
                await bind_tenant(sess, tenant_id)
                registered = await ingest_service.process_record(
                    sess, tenant_id, record
                )
        except Exception:
            stats.failed += 1
            logger.warning(
                "seed 快照记录失败：%s/%s",
                record.source_system,
                record.source_id,
                exc_info=True,
            )
            continue
        if registered:
            stats.registered += 1
        else:
            stats.duplicated += 1


async def _advance_watermarks(
    factory: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    records: list[SourceRecord],
) -> None:
    """按适配器分别推进水位（max(既有水位, 本段 occurred_at 最大)；不回退）。

    复用 ingest 水位助手（_find_system/_advance_watermark）：与 run_sync
    同一 ORM 写回路径与审计口径（SYSTEMS_CREATE/SYSTEMS_UPDATE）。
    """
    for adapter, source_system in (
        (DemoErpAdapter(), ERP_SOURCE_SYSTEM),
        (DemoPlmAdapter(), PLM_SOURCE_SYSTEM),
    ):
        subset = [record for record in records if record.source_system == source_system]
        if not subset:
            continue
        async with factory.begin() as sess:
            await bind_tenant(sess, tenant_id)
            system = await ingest_service._find_system(sess, tenant_id, adapter.name)
            latest = system.last_watermark if system is not None else None
            for record in subset:
                if latest is None or record.occurred_at > latest:
                    latest = record.occurred_at
            if latest is not None:
                await ingest_service._advance_watermark(
                    sess, tenant_id, adapter, latest, system
                )


async def _run_result_events(
    factory: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    anchor: datetime,
    stats: SeedStats,
) -> None:
    """回流段：events/batch 服务调用（结果证据由 T9 服务端自动落）+ 案例。"""
    async with factory.begin() as sess:
        await bind_tenant(sess, tenant_id)
        events = await _build_result_events(sess, tenant_id, anchor)
        response = await events_service.ingest_batch(
            sess,
            ingest_service.service_principal(tenant_id),
            DEMO_RESULTS_IDEM_KEY,
            events,
        )
        if response.rejected:
            logger.warning("seed 回流事件被拒：%s", response.errors)
        if response.deduplicated:
            # 归档命中：本批 0 新增——存档 accepted 计入 duplicated，与
            # event_id 幂等路径（accepted=0, duplicated=全量）统计口径一致
            stats.events_duplicated = response.accepted
        else:
            stats.events_accepted = response.accepted
            stats.events_duplicated = response.duplicated
        stats.case_created = await _ensure_demo_case(sess, tenant_id, anchor)


async def _build_result_events(
    sess: AsyncSession, tenant_id: UUID, anchor: datetime
) -> list[EventIn]:
    """RESULT_EVENTS → EventIn（object_ref 自然键解析 object_id；缺失跳过）。"""
    events: list[EventIn] = []
    for spec in RESULT_EVENTS:
        object_type, source_id = spec.object_ref
        object_id = await projections_service.resolve_object_id(
            sess, tenant_id, object_type, source_id
        )
        if object_id is None:
            logger.warning("seed 回流事件对象缺失：%s/%s", object_type, source_id)
            continue
        events.append(_to_event_in(spec, object_id, anchor))
    return events


# ---- 放大活动段（W6 T5，EDP-033 压测前置）----

_SCALE_OBJECTS_SQL = text("""
    SELECT source_system, source_id, object_id
    FROM master.business_objects
    WHERE tenant_id = :t
""")

_SCALE_EVENT_COLUMNS = (
    "event_id",
    "tenant_id",
    "event_type",
    "object_id",
    "source_system",
    "occurred_at",
    "actor_type",
    "actor_id",
    "result_type",
    "risk_level",
    "score",
    "data",
    "ingest_latency_ms",
    "created_by",
    "updated_by",
)

_SCALE_EVIDENCE_COLUMNS = (
    "evidence_id",
    "tenant_id",
    "source_system",
    "source_record_id",
    "object_id",
    "event_id",
    "checksum",
    "snapshot",
    "captured_at",
    "created_by",
    "updated_by",
)

_SCALE_LINK_COLUMNS = (
    "link_id",
    "tenant_id",
    "evidence_id",
    "ref_type",
    "ref_id",
    "created_by",
    "updated_by",
)


async def _resolve_scaled_object_ids(
    factory: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    records: list[SourceRecord],
) -> dict[tuple[str, str], UUID]:
    """放大记录自然键 → object_id（快照段注册产物；缺行者跳过其活动事件）。"""
    wanted = {(record.source_system, record.source_id) for record in records}
    async with factory() as sess:
        await bind_tenant(sess, tenant_id)
        rows = (await sess.execute(_SCALE_OBJECTS_SQL, {"t": tenant_id})).all()
    return {
        (row.source_system, row.source_id): row.object_id
        for row in rows
        if (row.source_system, row.source_id) in wanted
    }


async def _bulk_insert_conflict_skip(
    sess: AsyncSession,
    table: str,
    columns: tuple[str, ...],
    rows: list[dict],
    *,
    jsonb_columns: frozenset[str],
    returning: str,
) -> int:
    """单语句多 VALUES 批量 INSERT ... ON CONFLICT DO NOTHING RETURNING。

    返回实际插入行数（RETURNING 计数——executemany 的 rowcount 在
    asyncpg 下不可靠）；jsonb 列经 CAST 绑定（与 _INSERT_EVENT_SQL 同法）。
    """
    placeholders: list[str] = []
    params: dict[str, object] = {}
    for row_index, row in enumerate(rows):
        row_ph: list[str] = []
        for col_index, column in enumerate(columns):
            name = f"p{row_index}_{col_index}"
            row_ph.append(f"CAST(:{name} AS jsonb)" if column in jsonb_columns else f":{name}")
            params[name] = row[column]
        placeholders.append(f"({', '.join(row_ph)})")
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES {', '.join(placeholders)}"
        f" ON CONFLICT DO NOTHING RETURNING {returning}"
    )
    result = await sess.execute(text(sql), params)
    return len(result.fetchall())


def _scaled_activity_rows(
    tenant_id: UUID,
    anchor: datetime,
    scale: int,
    object_ids: dict[tuple[str, str], UUID],
) -> Iterator[tuple[dict, list[dict], list[dict]]]:
    """放大活动事件行生成器：逐 (unit, record, k) 产出 (事件行, 证据行集, link 行集)。

    - event_id = derive_event_id(tenant, source_system, str(object_id),
      occurred_at, event_type)——与 events.ingest_batch 同派生式（object_id
      充当 source_id 槽位；对象行持久存在 → 同锚重放恒同 id）；
    - risk = scaled_risk_level(全局序号)——稀疏 P0/P1，多数为空；
    - 证据两路独立（evidence_id 含类型段，互不冲突）：k=0 恒落 checksum
      证据（verify 场景，snapshot 经 evidence_service.compute_checksum
      单一实现）；risk 非空恒落结果证据（source_record_id=result:{event_id}
      + RESULT link，与 ingest 路径同构）——uuid5(NIL, ...) 确定性幂等键。
    """
    actor = ingest_service.SERVICE_ACTOR_ID
    snapshot_count = len(SNAPSHOT_RECORDS)
    for unit in range(1, scale):
        suffix = scale_suffix(unit)
        shift = timedelta(minutes=unit)
        for record_index, spec in enumerate(SNAPSHOT_RECORDS):
            source_id = f"{spec.source_id}{suffix}"
            object_id = object_ids.get((spec.source_system, source_id))
            if object_id is None:
                logger.warning("seed 放大对象缺失，跳过活动事件：%s", source_id)
                continue
            base_seq = (
                (unit - 1) * snapshot_count + record_index
            ) * SCALE_ACTIVITY_PER_OBJECT
            base_at = anchor + timedelta(minutes=spec.offset_minutes) + shift
            event_type = scaled_activity_event_type(spec.object_type)
            for k in range(SCALE_ACTIVITY_PER_OBJECT):
                seq = base_seq + k
                risk = scaled_risk_level(seq)
                occurred_at = base_at - timedelta(
                    minutes=_SCALE_ACTIVITY_STEP_MINUTES * (k + 1)
                )
                event_id = derive_event_id(
                    tenant_id, spec.source_system, str(object_id), occurred_at, event_type
                )
                data = {"unit": unit, "object_type": spec.object_type, "seq": k}
                event_row = {
                    "event_id": event_id,
                    "tenant_id": tenant_id,
                    "event_type": event_type,
                    "object_id": object_id,
                    "source_system": spec.source_system,
                    "occurred_at": occurred_at,
                    "actor_type": "SERVICE",
                    "actor_id": actor,
                    "result_type": None,
                    "risk_level": risk,
                    "score": _SCALE_RISK_SCORES.get(risk),
                    "data": json.dumps(data, ensure_ascii=False),
                    "ingest_latency_ms": LATENCY_FLOOR_MS + seq % LATENCY_SPAN_MS,
                    "created_by": actor,
                    "updated_by": actor,
                }
                evidences: list[dict] = []
                links: list[dict] = []
                if k == 0:
                    snapshot = {"source_id": source_id, "unit": unit}
                    evidences.append(
                        {
                            "evidence_id": uuid5(
                                _NIL, f"seed-scale:evidence:activity:{event_id}"
                            ),
                            "tenant_id": tenant_id,
                            "source_system": spec.source_system,
                            "source_record_id": f"{source_id}#activity",
                            "object_id": object_id,
                            "event_id": event_id,
                            "checksum": evidence_service.compute_checksum(snapshot),
                            "snapshot": json.dumps(snapshot, ensure_ascii=False),
                            "captured_at": occurred_at,
                            "created_by": actor,
                            "updated_by": actor,
                        }
                    )
                if risk is not None:
                    evidences.append(
                        {
                            "evidence_id": uuid5(
                                _NIL, f"seed-scale:evidence:result:{event_id}"
                            ),
                            "tenant_id": tenant_id,
                            "source_system": spec.source_system,
                            "source_record_id": f"result:{event_id}",
                            "object_id": object_id,
                            "event_id": event_id,
                            "checksum": evidence_service.compute_checksum(data),
                            "snapshot": json.dumps(data, ensure_ascii=False),
                            "captured_at": occurred_at,
                            "created_by": actor,
                            "updated_by": actor,
                        }
                    )
                    links.append(
                        {
                            "link_id": uuid5(_NIL, f"seed-scale:link:{event_id}"),
                            "tenant_id": tenant_id,
                            "evidence_id": evidences[-1]["evidence_id"],
                            "ref_type": "RESULT",
                            "ref_id": event_id,
                            "created_by": actor,
                            "updated_by": actor,
                        }
                    )
                yield event_row, evidences, links


async def _run_scale_activity(
    factory: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    anchor: datetime,
    scale: int,
    stats: SeedStats,
) -> None:
    """放大活动段：活动事件 + checksum/结果证据批量落库（幂等重放收敛 duplicated）。

    事件 → 证据 → RESULT link 同批事务提交（FK 依赖前批已落）；批大小
    ≤ SCALE_BATCH_SIZE。raw SQL 批量路径不走 events.ingest_batch——不写
    幂等存档/outbox/逐行审计（防 50k 级演示数据撑爆 outbox PENDING 积压
    与 append-only 审计表；与 management 段 raw SQL 同口径），计量仍按
    实际写入逐批累加 tenant_usage_daily。
    """
    if scale <= 1:
        return
    records = scaled_source_records(anchor, scale)
    object_ids = await _resolve_scaled_object_ids(factory, tenant_id, records)
    event_chunk: list[dict] = []
    evidence_chunk: list[dict] = []
    link_chunk: list[dict] = []
    accepted = duplicated = 0

    async def _flush() -> None:
        nonlocal accepted, duplicated
        if not event_chunk:
            return
        async with factory.begin() as sess:
            await bind_tenant(sess, tenant_id)
            inserted = await _bulk_insert_conflict_skip(
                sess,
                "event.events",
                _SCALE_EVENT_COLUMNS,
                event_chunk,
                jsonb_columns=frozenset({"data"}),
                returning="event_id",
            )
            accepted += inserted
            duplicated += len(event_chunk) - inserted
            if evidence_chunk:
                await _bulk_insert_conflict_skip(
                    sess,
                    "evidence.records",
                    _SCALE_EVIDENCE_COLUMNS,
                    evidence_chunk,
                    jsonb_columns=frozenset({"snapshot"}),
                    returning="evidence_id",
                )
            if link_chunk:
                await _bulk_insert_conflict_skip(
                    sess,
                    "evidence.links",
                    _SCALE_LINK_COLUMNS,
                    link_chunk,
                    jsonb_columns=frozenset(),
                    returning="link_id",
                )
            await tenantmgmt_service.bump_usage_daily(
                sess,
                tenant_id,
                events_in=inserted,
                events_duplicated=len(event_chunk) - inserted,
            )
        event_chunk.clear()
        evidence_chunk.clear()
        link_chunk.clear()

    for event_row, evidences, links in _scaled_activity_rows(
        tenant_id, anchor, scale, object_ids
    ):
        event_chunk.append(event_row)
        evidence_chunk.extend(evidences)
        link_chunk.extend(links)
        if len(event_chunk) >= SCALE_BATCH_SIZE:
            await _flush()
    await _flush()
    stats.events_accepted += accepted
    stats.events_duplicated += duplicated


# ---- management 段（W4，EDP-012 残余）----

_INSERT_OBJECTIVE_SQL = text("""
    INSERT INTO management.objectives
        (objective_id, tenant_id, title, metric_type, target_value,
         current_value, period, status, created_by, updated_by)
    VALUES
        (:objective_id, :t, :title, :metric_type, :target_value,
         :current_value, :period, :status, :actor, :actor)
    ON CONFLICT DO NOTHING
""")

_INSERT_KPI_DEFINITION_SQL = text("""
    INSERT INTO management.kpi_definitions
        (kpi_id, tenant_id, code, name, unit, created_by, updated_by)
    VALUES
        (:kpi_id, :t, :code, :name, :unit, :actor, :actor)
    ON CONFLICT DO NOTHING
""")

_INSERT_KPI_VALUE_SQL = text("""
    INSERT INTO management.kpi_values
        (value_id, tenant_id, kpi_id, period, value, source,
         created_by, updated_by)
    VALUES
        (:value_id, :t, :kpi_id, :period, :value, :source, :actor, :actor)
    ON CONFLICT DO NOTHING
""")

# Metric Registry 镜像（V1.2 T26）：与 management 段同数据双写——EBMS
# reports 数据源（kpi_* 保留供 objectives 与既有兼容）；definition_owner
# 域映射 + target_owner=M01_KERNEL（V1.2 第五节边界）。
_METRIC_OWNERS = {
    "on_time_delivery": "DELIVERY",
    "inventory_turnover": "DELIVERY",
    "risk_closure_rate": "MANAGEMENT",
}
_METRIC_DEFINITIONS = {
    "on_time_delivery": "按承诺日期计算的准时交付订单比例",
    "inventory_turnover": "库存周转次数（月度）",
    "risk_closure_rate": "风险闭环处理比例",
}

_INSERT_METRIC_SQL = text("""
    INSERT INTO metric.metrics
        (metric_id, tenant_id, code, name, owner, definition_owner,
         definition_source, target_owner, business_definition, unit,
         version, effective_from, created_by, updated_by)
    VALUES
        (:metric_id, :t, :code, :name, :owner, :definition_owner, 'DOMAIN',
         'M01_KERNEL', :business_definition, :unit, 1, now(), :actor, :actor)
    ON CONFLICT DO NOTHING
""")

_INSERT_METRIC_VALUE_SQL = text("""
    INSERT INTO metric.metric_values
        (value_id, tenant_id, metric_id, period, value, source,
         created_by, updated_by)
    VALUES
        (:value_id, :t, :metric_id, :period, :value, :source, :actor, :actor)
    ON CONFLICT DO NOTHING
""")


def _month_period(anchor: datetime) -> str:
    """锚当月（YYYY-MM；锚恒为 UTC 截整点）。"""
    return f"{anchor.year:04d}-{anchor.month:02d}"


def _iso_week_period(anchor: datetime, week_offset: int) -> str:
    """锚 ± 偏移周的 ISO 周期（YYYY-Www，对齐 B.9 示例 2026-W36 风格）。"""
    iso = (anchor + timedelta(weeks=week_offset)).isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def _mgmt_objective_id(title: str) -> UUID:
    """objectives 行幂等键（标题为自然键；与 period 解耦——RESET 已清旧行）。"""
    return uuid5(_NIL, f"seed-mgmt:objective:{title}")


def _mgmt_kpi_id(code: str) -> UUID:
    """kpi_definitions 行幂等键（code 唯一索引 uq_kpi_code 同语义）。"""
    return uuid5(_NIL, f"seed-mgmt:kpi:{code}")


def _mgmt_value_id(code: str, period: str) -> UUID:
    """kpi_values 行幂等键（code + period；计划卡指定命名）。"""
    return uuid5(_NIL, f"seed-mgmt:{code}:{period}")


def _metric_id(code: str) -> UUID:
    """Metric Registry 行幂等键（code 唯一索引同语义）。"""
    return uuid5(_NIL, f"seed-metric:{code}")


def _metric_value_id(code: str, period: str) -> UUID:
    """Metric 计量值幂等键（code + period）。"""
    return uuid5(_NIL, f"seed-metric:{code}:{period}")


async def _run_management_seed(
    factory: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    anchor: datetime,
    stats: SeedStats,
) -> None:
    """management 段：objectives + kpi_definitions + kpi_values 确定性 upsert。

    幂等：行 id = uuid5(NIL, "seed-mgmt:...") + ON CONFLICT DO NOTHING——
    锚复用 → 同 period 同 id → 重跑 0 新增（mgmt_inserted 统计本次实际
    插入）。跨模块无 management service，故以 raw SQL 写（与 _PURGE_SQL
    同口径；RLS 会话已 bind_tenant）。
    """
    params: dict[str, object] = {"t": tenant_id, "actor": MGMT_ACTOR_ID}
    async with factory.begin() as sess:
        await bind_tenant(sess, tenant_id)
        inserted = 0
        month = _month_period(anchor)
        for spec in MGMT_OBJECTIVES:
            result = await sess.execute(
                _INSERT_OBJECTIVE_SQL,
                {
                    **params,
                    "objective_id": _mgmt_objective_id(spec.title),
                    "title": spec.title,
                    "metric_type": spec.metric_type,
                    "target_value": spec.target_value,
                    "current_value": spec.current_value,
                    "period": month,
                    "status": spec.status,
                },
            )
            inserted += max(result.rowcount, 0)
        for spec in MGMT_KPI_DEFINITIONS:
            result = await sess.execute(
                _INSERT_KPI_DEFINITION_SQL,
                {
                    **params,
                    "kpi_id": _mgmt_kpi_id(spec.code),
                    "code": spec.code,
                    "name": spec.name,
                    "unit": spec.unit,
                },
            )
            inserted += max(result.rowcount, 0)
        for spec in MGMT_KPI_VALUES:
            period = _iso_week_period(anchor, spec.week_offset)
            result = await sess.execute(
                _INSERT_KPI_VALUE_SQL,
                {
                    **params,
                    "value_id": _mgmt_value_id(spec.code, period),
                    "kpi_id": _mgmt_kpi_id(spec.code),
                    "period": period,
                    "value": spec.value,
                    "source": MGMT_VALUE_SOURCE,
                },
            )
            inserted += max(result.rowcount, 0)
        # Metric Registry 镜像（V1.2 T26）：同数据双写——EBMS reports 数据源
        for spec in MGMT_KPI_DEFINITIONS:
            await sess.execute(
                _INSERT_METRIC_SQL,
                {
                    **params,
                    "metric_id": _metric_id(spec.code),
                    "code": spec.code,
                    "name": spec.name,
                    "owner": _METRIC_OWNERS[spec.code],
                    "definition_owner": _METRIC_OWNERS[spec.code],
                    "business_definition": _METRIC_DEFINITIONS[spec.code],
                    "unit": spec.unit,
                },
            )
        for spec in MGMT_KPI_VALUES:
            period = _iso_week_period(anchor, spec.week_offset)
            await sess.execute(
                _INSERT_METRIC_VALUE_SQL,
                {
                    **params,
                    "value_id": _metric_value_id(spec.code, period),
                    "metric_id": _metric_id(spec.code),
                    "period": period,
                    "value": spec.value,
                    "source": MGMT_VALUE_SOURCE,
                },
            )
        stats.mgmt_inserted = inserted


def _to_event_in(spec: ResultEventSpec, object_id: UUID, anchor: datetime) -> EventIn:
    """结果事件规格 → EventIn（occurred_at = anchor + 固定偏移）。"""
    return EventIn(
        event_type=spec.event_type,
        object_id=object_id,
        source_system=spec.source_system,
        occurred_at=anchor + timedelta(minutes=spec.offset_minutes),
        actor_type=spec.actor_type,
        actor_id=spec.actor_id,
        result_type=spec.result_type,
        risk_level=spec.risk_level,
        score=spec.score,
        data=spec.data,
    )


_CASE_EVIDENCE_SQL = text("""
    SELECT evidence_id FROM evidence.records
    WHERE tenant_id = :t AND object_id = :object_id
    ORDER BY captured_at DESC, evidence_id DESC
    LIMIT 1
""")


async def _ensure_demo_case(
    sess: AsyncSession, tenant_id: UUID, anchor: datetime
) -> bool:
    """场景 2 决策案例（DEMO_CASE）：不存在则经 decisions 服务创建（+CASE 证据链）。

    幂等键 = (source_type="capability.result", source_id=源结果事件 id)；
    源事件缺失（快照未落）→ 跳过记 warning。返回是否新建。
    """
    object_type, source_id = DEMO_CASE.source_event_ref
    object_id = await projections_service.resolve_object_id(
        sess, tenant_id, object_type, source_id
    )
    if object_id is None:
        logger.warning("seed 案例源对象缺失：%s/%s", object_type, source_id)
        return False
    spec = next(
        spec for spec in RESULT_EVENTS if spec.object_ref == DEMO_CASE.source_event_ref
    )
    event_id = derive_event_id(
        tenant_id,
        spec.source_system,
        str(object_id),
        anchor + timedelta(minutes=spec.offset_minutes),
        spec.event_type,
    )
    if await events_service.get_event(sess, event_id) is None:
        logger.warning("seed 案例源事件缺失：%s", event_id)
        return False
    existing = await decisions_service.find_case_by_source(
        sess, CASE_SOURCE_TYPE, str(event_id)
    )
    if existing is not None:
        return False

    evidence_ids: list[UUID] = []
    for ref in DEMO_CASE.evidence_source_refs:
        evidence_id = await _latest_evidence_id(sess, tenant_id, ref)
        if evidence_id is None:
            logger.warning("seed 案例证据缺失：%s/%s", ref[0], ref[1])
            continue
        evidence_ids.append(evidence_id)

    await decisions_service.create_case(
        sess,
        ingest_service.service_principal(tenant_id),
        CaseCreateRequest(
            question=DEMO_CASE.question,
            # T5 评审 Minor-4：B.5 context 含 source_event_id（seed 派生回填）
            context={**DEMO_CASE.context, "source_event_id": str(event_id)},
            options=[
                CaseOptionIn(key=option.key, label=option.label)
                for option in DEMO_CASE.options
            ],
            risk_level=DEMO_CASE.risk_level,
            source_type=CASE_SOURCE_TYPE,
            source_id=str(event_id),
            evidence_ids=evidence_ids,
        ),
    )
    return True


async def _latest_evidence_id(
    sess: AsyncSession, tenant_id: UUID, ref: tuple[str, str]
) -> UUID | None:
    """证据自然键 → 最新证据 id（同对象多证据取 captured_at 最新）。"""
    object_type, source_id = ref
    object_id = await projections_service.resolve_object_id(
        sess, tenant_id, object_type, source_id
    )
    if object_id is None:
        return None
    return (
        await sess.execute(
            _CASE_EVIDENCE_SQL, {"t": tenant_id, "object_id": object_id}
        )
    ).scalar_one_or_none()


_LATENCY_SQL = text("""
    UPDATE event.events
    SET ingest_latency_ms = :floor + (abs(hashtext(event_id::text)) % :span)
    WHERE tenant_id = :t
      AND (event_id IN :ids OR idempotency_key LIKE :result_prefix)
""").bindparams(bindparam("ids", expanding=True))


def snapshot_event_ids(tenant_id: UUID, records: list[SourceRecord]) -> list[UUID]:
    """记录集 → 确定性 SNAPSHOT event_id 集合（基线与放大段共用派生式）。

    与 process_record 同派生式（derive_event_id + {object_type}_SNAPSHOT，
    occurred_at 用记录原值）——只按 event_id 精确圈定演示事件，不误伤同
    类型（``*_SNAPSHOT``）的真实 ErpMock 管道事件。
    """
    return [
        derive_event_id(
            tenant_id,
            record.source_system,
            record.source_id,
            record.occurred_at,
            ingest_service.SNAPSHOT_EVENT_TYPE(record.object_type),
        )
        for record in records
    ]


def demo_snapshot_event_ids(tenant_id: UUID, anchor: datetime) -> list[UUID]:
    """演示快照段事件的确定性 event_id 集合（基线数据集；放大段经
    snapshot_event_ids(records) 圈定）。"""
    return snapshot_event_ids(tenant_id, merged_snapshot_records(anchor))


async def _apply_demo_latency(
    factory: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    records: list[SourceRecord],
) -> None:
    """确定性覆盖演示事件的接入耗时（60~299ms，spec §6.2「seed 用确定性值」）。

    覆盖范围 = 演示数据集事件：快照段（基线 + 放大，按 anchor 复算的
    event_id 集合）与 seed 回流事件（幂等键前缀 ``seed-demo:results:v1:``）；
    放大活动事件在批量插入时即写确定性耗时（60 + seq % 240），不在本段。
    T9 起管道/批量会写实测耗时（亚毫秒级），若不覆盖则演示 KPI（P95 接入
    延迟）退化为 0——故此处对演示事件确定性覆盖；非演示事件（真实
    ErpMock 管道、真实批量入库等）的实测值一律不动。
    """
    async with factory.begin() as sess:
        await bind_tenant(sess, tenant_id)
        await sess.execute(
            _LATENCY_SQL,
            {
                "t": tenant_id,
                "floor": LATENCY_FLOOR_MS,
                "span": LATENCY_SPAN_MS,
                "ids": snapshot_event_ids(tenant_id, records),
                "result_prefix": f"{DEMO_RESULTS_IDEM_KEY}:%",
            },
        )
