"""ingest 管道服务（EDP-010）：源记录三元组单事务落库 + 水位 + 对账。

process_record 是单条记录的唯一处理实现（T15 CLI 与 T16 sync API 共用，
run_sync 内部亦循环调用它）：对象 upsert → 领域投影（T4，savepoint 隔离，
投影失败不连坐）→ SNAPSHOT 事件 → 证据 → outbox，全部写在同一事务内
（本层只 flush 不 commit，事务边界归调用方：run_sync 挂调用方单会话整批
提交；run_sync_per_record 每记录 engine.begin() 独立提交——CLI 与 T16
触发式任务的事务入口，单条失败只回滚该条不连坐批次）。

幂等（UUIDv5 适配器层 + ON CONFLICT 数据层双保险）：
- event_id = derive_event_id(tenant, source_system, source_id, occurred_at,
  "{object_type}_SNAPSHOT")——同记录重放恒派生相同 event_id（B.3 批量路径
  以 str(object_id) 充当 source_id 槽位，管道这里传真实 source_id）；
- 先查 event 已存在 → duplicated 跳过（不动 revision、不写证据）；
- INSERT ... ON CONFLICT DO NOTHING rowcount=0 → 同判（竞态双保险）。

RLS：platform.systems / master.business_objects / event.* / evidence.* 均
FORCE RLS——调用方会话需已 bind_tenant（CLI/API 各自绑定；显式 tenant_id
条件双保险）。

审计（T11 覆盖情况，管道每条 registered 记录落三行，另每次 sync 落
一行 SYSTEMS_*）：
- OBJECT_CREATE / OBJECT_UPDATE：upsert 路径（ORM INSERT 由切面自动捕获；
  SQL UPDATE 由 registry 显式补点）——每记录恰一行（新建 CREATE/更新 UPDATE）；
- EVENT_CREATE：本模块纯 SQL INSERT 不经 ORM 状态——显式 record_explicit
  （detail.via="pipeline" 区分管道来源，与 events 批量入库路径同构）；
- EVIDENCE_CREATE：ORM INSERT 由切面自动捕获；
- SYSTEMS_CREATE / SYSTEMS_UPDATE：水位写回（_advance_watermark ORM 路径，
  切面捕获），每次 run_sync 至多一行；
- outbox 两行（OBJECT_UPSERT + SNAPSHOT）与领域投影行（13 张快照表）
  被切面排除（派生行，业务写已逐行有审计）；
- 切面（before_flush）仅由宿主进程安装（create_app / CLI），本模块不
  自装——未装切面的宿主只有显式补点的 EVENT_CREATE / OBJECT_UPDATE 行；
- run_sync 进入时 set current_principal（服务主体），使无请求上下文的
  CLI/后台任务中切面派生行（OBJECT_CREATE / EVIDENCE_CREATE / SYSTEMS_*）
  actor 也收敛为 SERVICE/adapter:erp。

已知边界（单写者语义，可接受）：upsert_object 在并发首插 IntegrityError
时会 rollback 整个事务（既有行为）——管道为单写者无并发竞争；run_sync 对
单条失败仅计数记日志 continue、不 rollback（flush-only），失败记录可能遗留
部分未提交写，由调用方事务策略收敛（CLI 逐条事务天然隔离）。

对账（reconcile）：ok 判定为记录级三计数齐等（source == events == evidence）
——objects 为实体数（DELTA 更新不新增对象、只推 revision），仅展示不参与
判定；删任一证据/事件行即使三计数失配 → ok=False。
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Literal
from uuid import UUID, uuid4

from edp_adapters.base import SourceAdapter, SourceRecord
from sqlalchemy import TextClause, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from edp_api.core.contextvars import current_principal
from edp_api.core.db import bind_tenant
from edp_api.core.errors import EdpError
from edp_api.core.security.principal import Principal
from edp_api.modules.audit import service as audit_service
from edp_api.modules.events import service as events_service
from edp_api.modules.events.uuidv5 import derive_event_id, normalize_occurred_at
from edp_api.modules.evidence import service as evidence_service
from edp_api.modules.evidence.schemas import EvidenceCreateRequest
from edp_api.modules.governance import service as governance_service
from edp_api.modules.ingest.models import System
from edp_api.modules.ingest.schemas import ImportErrorItem, ImportStats
from edp_api.modules.projections import service as projections_service
from edp_api.modules.registry import service as registry_service
from edp_api.modules.registry.schemas import (
    OBJECT_TYPE_PATTERN,
    SOURCE_ID_PATTERN,
    ObjectUpsertRequest,
)
from edp_api.modules.tenantmgmt import service as tenantmgmt_service

logger = logging.getLogger(__name__)

SERVICE_ACTOR_ID = "adapter:erp"
ADAPTER_TYPE_ERP = "ERP"
ADAPTER_MODE_MOCK = "mock"
AGGREGATE_TYPE_EVENT = "EVENT"

_SNAPSHOT_SUFFIX_LEN = len("_SNAPSHOT")
# fetch_incremental 的"自纪元起"哨兵：返回源全集（对账数据源）
_EPOCH = datetime.min.replace(tzinfo=UTC)

# 同步模式（T13）：replay = fetch_full 全量重放 + 可选 occurred_at ≥ since 过滤
SyncMode = Literal["full", "incremental", "replay"]


def SNAPSHOT_EVENT_TYPE(object_type: str) -> str:  # noqa: N802 —— 计划冻结命名
    """管道 SNAPSHOT 事件类型：{object_type}_SNAPSHOT（对账按后缀反解类型）。"""
    return f"{object_type}_SNAPSHOT"


@dataclass(slots=True)
class SyncStats:
    """一次同步的计数结果（T16 status 端点透出）。"""

    fetched: int = 0
    registered: int = 0
    duplicated: int = 0
    failed: int = 0


@dataclass(slots=True)
class ReconciliationRow:
    """对账单行：源计数 vs DB 三计数（ok = source==events==evidence）。"""

    source_system: str
    object_type: str
    source_count: int
    edp_count_objects: int
    edp_count_events: int
    edp_count_evidence: int
    ok: bool


@dataclass(slots=True)
class CaptureReconciliationRow:
    """双轨对账单行（V1.3 T47）：拉取轨计数 vs CDC 轨计数。

    source_count = 拉取适配器全集（fetch_incremental(纪元)，同 reconcile
    口径）；capture_count = capture 通道 SNAPSHOT 事件计数。ok = 两计数
    相等（CDC 漏数由本行暴露，拉取轨兜底补数后收敛）。
    """

    source_system: str
    capture_source_system: str
    object_type: str
    source_count: int
    capture_count: int
    ok: bool


def service_principal(tenant_id: UUID) -> Principal:
    """管道服务主体（ErpMock 固定 adapter:erp；真实适配器接入时泛化）。"""
    return Principal(id=SERVICE_ACTOR_ID, kind="SERVICE", tenant_id=tenant_id)


# SNAPSHOT 事件写入（与 events.ingest_batch 的 pg_insert(Event).on_conflict_
# do_nothing() 同语义；此处为纯 SQL——跨模块仅准 import service，Event ORM
# 映射不可直接引用）。ON CONFLICT 无目标子句：同时覆盖 event_id 主键与
# uq_events_idem 部分唯一索引。
_INSERT_EVENT_SQL = text("""
    INSERT INTO event.events
        (event_id, tenant_id, event_type, object_id, source_system, occurred_at,
         actor_type, actor_id, result_type, risk_level, score, data,
         idempotency_key, ingest_latency_ms, created_by, updated_by)
    VALUES
        (:event_id, :tenant_id, :event_type, :object_id, :source_system,
         :occurred_at, 'SERVICE', :actor, NULL, NULL, NULL,
         CAST(:data AS jsonb), :idempotency_key, :latency_ms, :actor, :actor)
    ON CONFLICT DO NOTHING
""")

_OBJECT_COUNT_SQL = text("""
    SELECT object_type, count(*) AS n
    FROM master.business_objects
    WHERE tenant_id = :tid AND source_system = :src
    GROUP BY object_type
""")

# RAW 留存（V1.2 T08）：先留存后处理——源记录原始 payload 落 governance.
# raw_records（checksum 复用 evidence_service.compute_checksum 单一实现）；
# ON CONFLICT DO NOTHING 幂等（同 (source_system, source_record_id,
# source_timestamp) 重放不重复落数）；审计不单列 RAW 行（派生归档行，业务
# 写已由 OBJECT_*/EVENT_CREATE/EVIDENCE_CREATE 逐行有审计，同 outbox/投影
# 排除惯例）。
_INSERT_RAW_SQL = text("""
    INSERT INTO governance.raw_records
        (raw_record_id, tenant_id, source_system, source_record_id, object_type,
         source_timestamp, raw_payload, batch_id, checksum, schema_version)
    VALUES
        (:raw_record_id, :tenant_id, :source_system, :source_record_id, :object_type,
         :source_timestamp, CAST(:payload AS jsonb), :batch_id, :checksum, :schema_version)
    ON CONFLICT (tenant_id, source_system, source_record_id, source_timestamp)
    DO NOTHING
""")

# event_type 尾缀反解 object_type（ORDER_SNAPSHOT → ORDER）
_EVENT_COUNT_SQL = text(r"""
    SELECT substr(event_type, 1, length(event_type) - :suffix_len) AS object_type,
           count(*) AS n
    FROM event.events
    WHERE tenant_id = :tid AND source_system = :src
      AND event_type LIKE '%\_SNAPSHOT'
    GROUP BY 1
""")

# 证据无 object_type 列——经 object_id 关联业务对象取类型
_EVIDENCE_COUNT_SQL = text("""
    SELECT bo.object_type AS object_type, count(*) AS n
    FROM evidence.records er
    JOIN master.business_objects bo
      ON bo.object_id = er.object_id AND bo.tenant_id = er.tenant_id
    WHERE er.tenant_id = :tid AND er.source_system = :src
    GROUP BY bo.object_type
""")

# capture 通道计数（V1.3 T47）：via='capture' 的 SNAPSHOT 事件按对象类型
_CAPTURE_COUNT_SQL = text(r"""
    SELECT bo.object_type AS object_type, count(*) AS n
    FROM event.events e
    JOIN master.business_objects bo
      ON bo.object_id = e.object_id AND bo.tenant_id = e.tenant_id
    WHERE e.tenant_id = :tid AND e.source_system = :src
      AND e.event_type LIKE '%\_SNAPSHOT' AND e.data->>'via' = 'capture'
    GROUP BY bo.object_type
""")


async def process_record(
    sess: AsyncSession,
    tenant_id: UUID,
    record: SourceRecord,
    *,
    via: str = "pipeline",
    batch_id: str | None = None,
) -> bool:
    """单条源记录 → 三元组（对象/事件/证据）+ outbox；返回 registered。

    通道标记（V1.3 T45）：``via`` 落事件 data 与审计 detail（缺省
    "pipeline"；实时消费侧传 "capture"），``batch_id`` 落 RAW 留存行
    （消费侧传 "capture:{topic}:{partition}:{offset}"——血缘回放可定位
    Kafka 坐标）；其余管道语义不变。

    duplicated（事件已存在 / ON CONFLICT 命中）返回 False 且不触碰 revision；
    领域投影（T4）在对象 upsert 后、事件写入前调用（savepoint 隔离：投影
    失败仅回滚投影写入记 warning，不阻断三元组/outbox）；CLI（逐条独立
    事务）与 run_sync 共用本实现。

    W3（T9）：registered/duplicated 两路径各经 tenantmgmt 累加
    tenant_usage_daily（events_in / events_duplicated，同事务）；
    ``ingest_latency_ms`` = 本条处理耗时（函数入口至事件 INSERT 前，
    perf_counter 毫秒截断）。
    """
    principal = service_principal(tenant_id)
    started = perf_counter()
    event_type = SNAPSHOT_EVENT_TYPE(record.object_type)
    event_id = derive_event_id(
        tenant_id, record.source_system, record.source_id, record.occurred_at, event_type
    )

    # 幂等第一道：事件已存在 → 整条跳过（不动 revision、不写证据、不投影
    # ——投影已随首次注册的事务完成，重放重做无意义）
    if await events_service.get_event(sess, event_id) is not None:
        await tenantmgmt_service.bump_usage_daily(
            sess, tenant_id, events_duplicated=1
        )
        return False

    occurred_at = normalize_occurred_at(record.occurred_at)

    # RAW 留存（V1.2 T08）：幂等命中（rowcount=0，RAW 已有同版本）不阻断
    # 既有流程；checksum 复用 evidence 单一实现——evidence 快照与 RAW 的
    # checksum 同源（canonical_json 键排序+紧凑），可互为校验
    await sess.execute(
        _INSERT_RAW_SQL,
        {
            "raw_record_id": uuid4(),
            "tenant_id": tenant_id,
            "source_system": record.source_system,
            "source_record_id": record.source_id,
            "object_type": record.object_type,
            "source_timestamp": occurred_at,
            "payload": json.dumps(record.payload, ensure_ascii=False),
            "batch_id": batch_id,
            "checksum": evidence_service.compute_checksum(record.payload),
            "schema_version": None,
        },
    )
    # 取实际 RAW 行（幂等冲突时行已存在，用既有行 id——clean_records 外键）
    raw_record_id = (
        await sess.execute(
            text(
                "SELECT raw_record_id FROM governance.raw_records"
                " WHERE tenant_id = :tid AND source_system = :src"
                " AND source_record_id = :rid AND source_timestamp = :ts"
            ),
            {
                "tid": tenant_id,
                "src": record.source_system,
                "rid": record.source_id,
                "ts": occurred_at,
            },
        )
    ).scalar_one_or_none()

    # 清洗（V1.2 T09）：初始无规则 = 恒等变换（既有测试零影响）；清洗结果
    # 用于对象 upsert 与领域投影，evidence 快照仍存原始 payload（证据=源快照，
    # 清洗不得覆盖 RAW/证据口径）
    cleaning_result = await governance_service.cleaning.apply_cleaning(
        sess, tenant_id, record.object_type, record.payload
    )
    cleaned_record = replace(record, payload=cleaning_result.cleaned)

    # 对象 upsert（新建 revision=1；更新 revision+1）——owner_domain 提升为
    # 独立列，attributes 存其余字段（清洗后）
    attributes = {
        k: v for k, v in cleaned_record.payload.items() if k != "owner_domain"
    }
    obj, _created = await registry_service.upsert_object(
        sess,
        principal,
        ObjectUpsertRequest(
            object_type=record.object_type,
            owner_domain=cleaned_record.payload.get("owner_domain")
            or record.payload["owner_domain"],
            source_system=record.source_system,
            source_id=record.source_id,
            attributes=attributes,
        ),
    )

    # 清洗留痕（V1.2 T09）：对象 upsert 后落 clean_records（每 fix 一行）
    await governance_service.record_cleaning(
        sess, tenant_id, obj.object_id, raw_record_id, cleaning_result
    )

    # 领域投影（spec §2.1：对象 upsert 后、事件写入前，同事务）——savepoint
    # 包裹：投影失败（如 NOT NULL FK 自然键未命中）只回滚投影写入并记
    # warning，不把 session 置入 PendingRollback、不连坐三元组/outbox
    try:
        async with sess.begin_nested():
            await projections_service.project_record(
                sess, tenant_id, cleaned_record, obj.object_id
            )
    except Exception:
        logger.warning(
            "领域投影失败：%s/%s",
            record.source_system,
            record.source_id,
            exc_info=True,
        )

    occurred_at = normalize_occurred_at(record.occurred_at)
    latency_ms = int((perf_counter() - started) * 1000)
    result = await sess.execute(
        _INSERT_EVENT_SQL,
        {
            "event_id": event_id,
            "tenant_id": tenant_id,
            "event_type": event_type,
            "object_id": obj.object_id,
            "source_system": record.source_system,
            "occurred_at": occurred_at,
            "actor": SERVICE_ACTOR_ID,
            "data": json.dumps({"via": via}, ensure_ascii=False),
            "idempotency_key": f"adapter:{event_id}",
            "latency_ms": latency_ms,
        },
    )
    # 幂等第二道（竞态双保险）：并发重放胜者已写入 → 按 duplicated 收敛；
    # 此前已发生的 upsert revision 推进在单写者管道下不会出现
    if result.rowcount == 0:
        await tenantmgmt_service.bump_usage_daily(
            sess, tenant_id, events_duplicated=1
        )
        return False

    # 纯 SQL INSERT 不经 ORM 状态（切面不可见）——显式补审计
    await audit_service.record_explicit(
        sess,
        action="EVENT_CREATE",
        resource_type="events",
        resource_id=str(event_id),
        detail={
            "via": via,
            "event_type": event_type,
            "object_id": str(obj.object_id),
            "source_system": record.source_system,
            "source_id": record.source_id,
            "occurred_at": occurred_at.isoformat(),
            "idempotency_key": f"adapter:{event_id}",
        },
        principal=principal,
    )

    # 证据快照存完整原始 payload（含 owner_domain——canonical 单源在
    # evidence 服务端计算 checksum）
    await evidence_service.create_record(
        sess,
        principal,
        EvidenceCreateRequest(
            source_system=record.source_system,
            source_record_id=f"{record.source_id}#v{obj.revision}",
            object_id=obj.object_id,
            event_id=event_id,
            snapshot=record.payload,
            captured_at=occurred_at,
        ),
    )

    await events_service.append_outbox(
        sess,
        tenant_id=tenant_id,
        aggregate_type=AGGREGATE_TYPE_EVENT,
        aggregate_id=event_id,
        event_type=event_type,
        payload={
            "event_id": str(event_id),
            "object_id": str(obj.object_id),
            "occurred_at": occurred_at.isoformat(),
            "source_system": record.source_system,
        },
        actor=SERVICE_ACTOR_ID,
    )
    await tenantmgmt_service.bump_usage_daily(sess, tenant_id, events_in=1)

    # 准入推进（V1.2 T07/T08）：同步管线至 CLASSIFIED（RECEIVED→PROFILED→
    # CLEANED→STANDARDIZED→CLASSIFIED，逐边事件留痕）；A2 起由人工审核驱动
    await governance_service.ensure_admission_pipeline(sess, tenant_id, obj.object_id)
    return True


def _fetch_records(
    adapter: SourceAdapter,
    mode: SyncMode,
    watermark: datetime | None,
    anchor: datetime | None,
    since: datetime | None,
) -> list[SourceRecord]:
    """按模式拉取源记录（T13：replay = 全量重放 + 可选 occurred_at ≥ since）。

    - full：fetch_full([]) 全集；
    - incremental：自水位（未登记 → 纪元哨兵）；
    - replay：fetch_full([]) 后按 since 过滤（since 经 normalize_occurred_at
      归一——naive 按 UTC 解释，前端 datetime-local 无时区值可直传）；
      其余语义同 full：UUIDv5 幂等 → 重放计 duplicated、不推 revision。
    未知模式抛 ValueError。
    """
    if mode == "full":
        return adapter.fetch_full([], anchor=anchor)
    if mode == "incremental":
        return adapter.fetch_incremental(
            watermark if watermark is not None else _EPOCH, anchor=anchor
        )
    if mode == "replay":
        records = adapter.fetch_full([], anchor=anchor)
        if since is None:
            return records
        cutoff = normalize_occurred_at(since)
        return [record for record in records if record.occurred_at >= cutoff]
    raise ValueError(f"未知同步模式：{mode}")


async def run_sync(
    sess: AsyncSession,
    tenant_id: UUID,
    adapter: SourceAdapter,
    mode: SyncMode,
    since: datetime | None = None,
) -> SyncStats:
    """同步入口：读水位 → 拉取（full=fetch_full([]) / incremental=自水位 /
    replay=全量重放 + since 过滤，见 _fetch_records）→
    逐条 process_record（单条失败 failed+1 记日志 continue）→ 水位推进
    max(fetched occurred_at) 写回 systems 行（未登记则 INSERT：
    type=ERP / adapter_mode=mock）。

    事务边界归调用方（CLI 逐条独立提交 / API 批提交）；水位不回退——
    full 重放时 fetched 可能整体早于既有水位，取 max(既有水位, fetched)。

    拉取前经 tenantmgmt 解析演示时间锚（T6）并传入 fetch_*：需要相对时间
    的演示适配器（erp-demo/plm-demo）以锚 + 固定偏移生成 occurred_at；
    未设置锚 → None 由适配器回退 DEMO_ANCHOR；ErpMock 忽略该参数。
    """
    token = current_principal.set(service_principal(tenant_id))
    try:
        system = await _find_system(sess, tenant_id, adapter.name)
        watermark = system.last_watermark if system is not None else None
        anchor = await tenantmgmt_service.get_demo_anchor(sess, tenant_id)
        records = _fetch_records(adapter, mode, watermark, anchor, since)

        stats = SyncStats(fetched=len(records))
        latest = watermark
        for record in records:
            try:
                registered = await process_record(sess, tenant_id, record)
            except Exception:
                stats.failed += 1
                logger.warning(
                    "管道单条处理失败：%s/%s",
                    record.source_system,
                    record.source_id,
                    exc_info=True,
                )
                continue
            if registered:
                stats.registered += 1
            else:
                stats.duplicated += 1
            if latest is None or record.occurred_at > latest:
                latest = record.occurred_at

        if records and latest is not None:
            await _advance_watermark(sess, tenant_id, adapter, latest, system)
        return stats
    finally:
        current_principal.reset(token)


async def run_sync_per_record(
    engine: AsyncEngine,
    tenant_id: UUID,
    adapter: SourceAdapter,
    mode: SyncMode,
    since: datetime | None = None,
) -> SyncStats:
    """逐记录独立事务同步（CLI / T16 触发式任务的事务策略）。

    与 run_sync 共用 process_record 单实现与同一统计口径（fetched/
    registered/duplicated/failed）；区别在事务边界：每条记录一个独立
    engine.begin() 事务（bind_tenant → process_record → 提交），单条失败
    仅回滚该条（failed+1 记日志继续，不连坐批次）；水位读取与推进各占
    独立短事务（推进时重取 systems 行——跨会话不重用 detached 实例）。
    水位语义与 run_sync 一致：不回退，取 max(既有水位, fetched 最大时刻)。
    时间锚与水位同段短事务解析（T6），拉取时透传 fetch_*。
    """
    token = current_principal.set(service_principal(tenant_id))
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as sess:
            await bind_tenant(sess, tenant_id)
            watermark = await get_watermark(sess, tenant_id, adapter.name)
            anchor = await tenantmgmt_service.get_demo_anchor(sess, tenant_id)

        records = _fetch_records(adapter, mode, watermark, anchor, since)

        stats = SyncStats(fetched=len(records))
        latest = watermark
        for record in records:
            try:
                async with factory.begin() as sess:
                    await bind_tenant(sess, tenant_id)
                    registered = await process_record(sess, tenant_id, record)
            except Exception:
                stats.failed += 1
                logger.warning(
                    "管道单条处理失败：%s/%s",
                    record.source_system,
                    record.source_id,
                    exc_info=True,
                )
                continue
            if registered:
                stats.registered += 1
            else:
                stats.duplicated += 1
            if latest is None or record.occurred_at > latest:
                latest = record.occurred_at

        if records and latest is not None:
            async with factory.begin() as sess:
                await bind_tenant(sess, tenant_id)
                system = await _find_system(sess, tenant_id, adapter.name)
                await _advance_watermark(sess, tenant_id, adapter, latest, system)
        return stats
    finally:
        current_principal.reset(token)


async def get_watermark(
    sess: AsyncSession, tenant_id: UUID, adapter_name: str
) -> datetime | None:
    """当前同步水位（systems.last_watermark；适配器未登记 → None）。"""
    system = await _find_system(sess, tenant_id, adapter_name)
    return system.last_watermark if system is not None else None


async def reconcile(
    sess: AsyncSession, tenant_id: UUID, adapter: SourceAdapter
) -> list[ReconciliationRow]:
    """对账：源全集（fetch_incremental(纪元)=BASE+DELTA 全量）按
    (source_system, object_type) 计数 vs DB 三计数；ok = 记录级三计数齐等
    （source == events == evidence；objects 为实体数仅展示）。DB 独有类型
    （源已删而 DB 残留）同样成行，source_count=0 偏差可见。"""
    source_counts: dict[str, int] = {}
    for record in adapter.fetch_incremental(_EPOCH):
        source_counts[record.object_type] = (
            source_counts.get(record.object_type, 0) + 1
        )

    params = {"tid": tenant_id, "src": adapter.name}
    object_counts = await _count_by_type(sess, _OBJECT_COUNT_SQL, params)
    event_counts = await _count_by_type(
        sess, _EVENT_COUNT_SQL, {**params, "suffix_len": _SNAPSHOT_SUFFIX_LEN}
    )
    evidence_counts = await _count_by_type(sess, _EVIDENCE_COUNT_SQL, params)

    rows: list[ReconciliationRow] = []
    all_types = set(source_counts) | set(object_counts) | set(event_counts)
    all_types |= set(evidence_counts)
    for object_type in sorted(all_types):
        source_count = source_counts.get(object_type, 0)
        count_objects = object_counts.get(object_type, 0)
        count_events = event_counts.get(object_type, 0)
        count_evidence = evidence_counts.get(object_type, 0)
        rows.append(
            ReconciliationRow(
                source_system=adapter.name,
                object_type=object_type,
                source_count=source_count,
                edp_count_objects=count_objects,
                edp_count_events=count_events,
                edp_count_evidence=count_evidence,
                ok=source_count == count_events == count_evidence,
            )
        )
    return rows


async def reconcile_capture(
    sess: AsyncSession,
    tenant_id: UUID,
    adapter: SourceAdapter,
    capture_source_system: str,
) -> list[CaptureReconciliationRow]:
    """双轨对账（V1.3 T47）：拉取轨全集 vs CDC 轨（via='capture'）计数。

    拉取轨口径与 reconcile 一致（fetch_incremental(纪元)=全集）；capture
    轨按事件 data.via='capture' 过滤——两轨各自 source_system（路由配置
    双轨同源时一致，测试/混部可不同）。单侧独有类型同样成行（偏差可见）。
    """
    source_counts: dict[str, int] = {}
    for record in adapter.fetch_incremental(_EPOCH):
        source_counts[record.object_type] = (
            source_counts.get(record.object_type, 0) + 1
        )

    capture_counts = await _count_by_type(
        sess,
        _CAPTURE_COUNT_SQL,
        {"tid": tenant_id, "src": capture_source_system},
    )

    rows: list[CaptureReconciliationRow] = []
    for object_type in sorted(set(source_counts) | set(capture_counts)):
        source_count = source_counts.get(object_type, 0)
        capture_count = capture_counts.get(object_type, 0)
        rows.append(
            CaptureReconciliationRow(
                source_system=adapter.name,
                capture_source_system=capture_source_system,
                object_type=object_type,
                source_count=source_count,
                capture_count=capture_count,
                ok=source_count == capture_count,
            )
        )
    return rows


async def _find_system(
    sess: AsyncSession, tenant_id: UUID, adapter_name: str
) -> System | None:
    """按 (tenant, name) 查 systems 登记行（uq_systems_name 唯一）。"""
    return (
        await sess.execute(
            select(System).where(
                System.tenant_id == tenant_id, System.name == adapter_name
            )
        )
    ).scalar_one_or_none()


async def _advance_watermark(
    sess: AsyncSession,
    tenant_id: UUID,
    adapter: SourceAdapter,
    watermark: datetime,
    system: System | None,
) -> None:
    """水位写回（ORM 路径，切面可见：SYSTEMS_CREATE / SYSTEMS_UPDATE）。"""
    if system is None:
        sess.add(
            System(
                system_id=uuid4(),
                tenant_id=tenant_id,
                name=adapter.name,
                type=ADAPTER_TYPE_ERP,
                adapter_mode=ADAPTER_MODE_MOCK,
                status="ACTIVE",
                last_watermark=watermark,
                created_by=SERVICE_ACTOR_ID,
                updated_by=SERVICE_ACTOR_ID,
            )
        )
    else:
        system.last_watermark = watermark
        system.updated_by = SERVICE_ACTOR_ID
        system.updated_at = func.now()
    await sess.flush()


async def _count_by_type(
    sess: AsyncSession, sql: TextClause, params: dict
) -> dict[str, int]:
    """分组计数 SQL → {object_type: n}。"""
    return {
        row["object_type"]: row["n"] for row in (await sess.execute(sql, params)).mappings()
    }


# ---- 文件导入（V1.2 T30：Excel/CSV 通道） ----

IMPORT_SOURCE_SYSTEM = "file-import"
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_IMPORT_ROWS = 1000
REQUIRED_COLUMNS = ("object_type", "source_id", "occurred_at")

# 对象类型 → owner_domain 缺省映射（CSV 可经可选列 owner_domain 覆盖）
_DEFAULT_OWNER_DOMAINS = {
    "CUSTOMER": "master",
    "MATERIAL": "master",
    "PRODUCT": "master",
    "SUPPLIER": "procurement",
    "ORDER": "sales",
    "PURCHASE_ORDER": "procurement",
    "SUPPLIER_LEAD_TIME": "procurement",
    "INVENTORY": "delivery",
    "CAPACITY": "delivery",
    "BOM": "rd",
    "PROJECT": "rd",
}


def _coerce_value(raw: str) -> Any:
    """CSV 标量类型推断：int → float → bool → 原串（投影 NUMERIC 列需要数值）。"""
    text_value = raw.strip()
    if not text_value:
        return None
    try:
        return int(text_value)
    except ValueError:
        pass
    try:
        return float(text_value)
    except ValueError:
        pass
    lowered = text_value.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    return raw


async def import_csv(
    sess: AsyncSession, principal: Principal, content: str
) -> ImportStats:
    """CSV 解析 → 逐行 SourceRecord → process_record 管道（同事务）。

    模板校验（缺必需列 → 400）；逐行校验（object_type/source_id 模式、
    occurred_at 解析）失败记 errors 行不阻断整批；行数上限 MAX_IMPORT_ROWS。
    """
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None:
        raise EdpError.validation_error("CSV 无表头行")
    missing = [col for col in REQUIRED_COLUMNS if col not in reader.fieldnames]
    if missing:
        raise EdpError.validation_error(f"缺少必需列：{', '.join(missing)}")
    if len(content.splitlines()) - 1 > MAX_IMPORT_ROWS:
        raise EdpError.validation_error(f"行数超限（上限 {MAX_IMPORT_ROWS}）")

    stats = ImportStats()
    for row_number, row in enumerate(reader, start=2):
        object_type = (row.get("object_type") or "").strip().upper()
        source_id = (row.get("source_id") or "").strip()
        occurred_raw = (row.get("occurred_at") or "").strip()
        if not re.fullmatch(OBJECT_TYPE_PATTERN, object_type):
            stats.failed += 1
            stats.errors.append(
                ImportErrorItem(
                    row=row_number, message=f"object_type 非法：{object_type}"
                )
            )
            continue
        if not re.fullmatch(SOURCE_ID_PATTERN, source_id):
            stats.failed += 1
            stats.errors.append(
                ImportErrorItem(row=row_number, message=f"source_id 非法：{source_id}")
            )
            continue
        try:
            occurred_at = datetime.fromisoformat(occurred_raw)
            if occurred_at.tzinfo is None:
                occurred_at = occurred_at.replace(tzinfo=UTC)
        except ValueError:
            stats.failed += 1
            stats.errors.append(
                ImportErrorItem(
                    row=row_number, message=f"occurred_at 非法：{occurred_raw}"
                )
            )
            continue

        payload = {
            key: coerced
            for key, value in row.items()
            if key not in (*REQUIRED_COLUMNS, "owner_domain")
            and (coerced := _coerce_value(value or "")) is not None
        }
        payload["owner_domain"] = (
            (row.get("owner_domain") or "").strip()
            or _DEFAULT_OWNER_DOMAINS.get(object_type, "master")
        )
        record = SourceRecord(
            source_system=IMPORT_SOURCE_SYSTEM,
            object_type=object_type,
            source_id=source_id,
            occurred_at=occurred_at,
            payload=payload,
        )
        try:
            registered = await process_record(sess, principal.tenant_id, record)
        except Exception:
            stats.failed += 1
            stats.errors.append(ImportErrorItem(row=row_number, message="管道处理失败"))
            logger.warning("文件导入单行失败：%s/%s", object_type, source_id, exc_info=True)
            continue
        if registered:
            stats.registered += 1
        else:
            stats.duplicated += 1

    stats.received = stats.registered + stats.duplicated + stats.failed
    return stats
