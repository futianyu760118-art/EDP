"""T14 ingest 管道集成测试（EDP-010）：三元组单事务 / UUIDv5 幂等 / 水位 /
对账 / RLS / 审计覆盖 / 领域投影（T4：投影落表 + 失败隔离 + 切面排除）。

直调 service 层（管道 HTTP 入口归 T16、CLI 归 T15，此处验证落库语义）；
会话形态：app_role_engine（edp_app 角色，受 RLS）+ bind_tenant(default
租户，tenant_id 自 0005 种子解析)。数据痕迹以 erp mock 源 id 前缀识别
（SO-2026-% / C-1__ / M-3__），与兄弟模块（SO-REG-% 等）互不重叠；每测试
后 migrator 清场。

计数口径：objects=实体数、events/evidence=记录数（DELTA 更新推 revision
不新增对象/证据不替换）；reconcile 的 ok 判定为记录级三计数齐等。
"""

import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from edp_adapters import ErpMockAdapter
from edp_adapters.base import SourceRecord
from edp_adapters.erp_mock import UPDATED_ORDER_IDS, WINDOW_END
from edp_api.core.db import bind_tenant
from edp_api.modules.audit.aspect import install_audit_aspect
from edp_api.modules.ingest import service as ingest_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

pytestmark = [pytest.mark.integration]

NEW_ORDER_IDS = ("SO-2026-00241", "SO-2026-00242", "SO-2026-00243")

_BO_SCOPE = "(source_id LIKE 'SO-2026-%' OR source_id LIKE 'C-1%' OR source_id LIKE 'M-3%')"
_EV_SCOPE = (
    "(source_record_id LIKE 'SO-2026-%' OR source_record_id LIKE 'C-1%'"
    " OR source_record_id LIKE 'M-3%')"
)

# 领域投影表（T4 排除清单）：切面不应产生这些表的派生审计行
_DOMAIN_AUDIT_TABLES = [
    "customers",
    "materials",
    "products",
    "suppliers",
    "boms",
    "bom_items",
    "orders",
    "order_lines",
    "inventory",
    "purchase_orders",
    "supplier_lead_times",
    "projects",
    "milestones",
]


@pytest.fixture
async def default_tenant_id(db_session: AsyncSession) -> UUID:
    """default 租户 id（0005 种子；tenants 控制面表，migrator 直查）。"""
    return (
        await db_session.execute(
            text("SELECT tenant_id FROM platform.tenants WHERE slug = 'default'")
        )
    ).scalar_one()


@pytest.fixture(autouse=True)
async def _clean_pipeline_rows(db_session: AsyncSession) -> None:
    """每测试后清场：本模块痕迹（erp mock 对象/快照事件/证据/outbox/审计/
    systems 水位行），保证用例间独立（migrator 绕 RLS；审计删除先于关联行，
    子查询不因先清而失配）。"""
    yield
    await db_session.execute(
        text("""
            DELETE FROM platform.audit_logs WHERE
                detail->'after'->>'source_id' LIKE 'SO-2026-%'
                OR detail->'after'->>'source_id' LIKE 'C-1%'
                OR detail->'after'->>'source_id' LIKE 'M-3%'
                OR detail->>'source_id' LIKE 'SO-2026-%'
                OR detail->>'source_id' LIKE 'C-1%'
                OR detail->>'source_id' LIKE 'M-3%'
                OR detail->'after'->>'source_record_id' LIKE 'SO-2026-%'
                OR detail->'after'->>'source_record_id' LIKE 'C-1%'
                OR detail->'after'->>'source_record_id' LIKE 'M-3%'
                OR resource_id IN (SELECT event_id::text FROM event.events
                                   WHERE event_type LIKE '%\\_SNAPSHOT')
                OR resource_id IN (SELECT system_id::text FROM platform.systems
                                   WHERE name = 'erp')
        """)
    )
    await db_session.execute(
        text(f"""
            DELETE FROM event.outbox WHERE
                aggregate_id IN (SELECT object_id FROM master.business_objects
                                 WHERE {_BO_SCOPE})
                OR aggregate_id IN (SELECT event_id FROM event.events
                                    WHERE event_type LIKE '%\\_SNAPSHOT')
        """)
    )
    await db_session.execute(
        text(f"""
            DELETE FROM evidence.records WHERE {_EV_SCOPE}
        """)
    )
    await db_session.execute(
        text("DELETE FROM event.events WHERE event_type LIKE '%\\_SNAPSHOT'")
    )
    # 领域投影行（T4）：子表先删（FK 指向 business_objects，不先清父行删不掉）
    await db_session.execute(
        text(
            "DELETE FROM sales.order_lines WHERE order_id IN"
            f" (SELECT object_id FROM master.business_objects WHERE {_BO_SCOPE})"
        )
    )
    await db_session.execute(
        text(
            "DELETE FROM sales.orders WHERE order_id IN"
            f" (SELECT object_id FROM master.business_objects WHERE {_BO_SCOPE})"
        )
    )
    await db_session.execute(
        text(
            "DELETE FROM master.customers WHERE customer_id IN"
            f" (SELECT object_id FROM master.business_objects WHERE {_BO_SCOPE})"
        )
    )
    await db_session.execute(
        text(
            "DELETE FROM master.materials WHERE material_id IN"
            f" (SELECT object_id FROM master.business_objects WHERE {_BO_SCOPE})"
        )
    )
    # governance（V1.2 0014）：admission/clean/classification FK 指向
    # business_objects——先清（先子后父：review→admission→classification；
    # clean→raw），否则 business_objects 删除被 FK 阻断
    await db_session.execute(
        text(
            "DELETE FROM governance.review_records WHERE tenant_id ="
            " (SELECT tenant_id FROM platform.tenants WHERE slug = 'default')"
        )
    )
    await db_session.execute(
        text(
            "DELETE FROM governance.admission_records WHERE tenant_id ="
            " (SELECT tenant_id FROM platform.tenants WHERE slug = 'default')"
        )
    )
    await db_session.execute(
        text(
            "DELETE FROM governance.object_classifications WHERE tenant_id ="
            " (SELECT tenant_id FROM platform.tenants WHERE slug = 'default')"
        )
    )
    await db_session.execute(
        text(
            "DELETE FROM governance.clean_records WHERE tenant_id ="
            " (SELECT tenant_id FROM platform.tenants WHERE slug = 'default')"
        )
    )
    await db_session.execute(
        text(
            "DELETE FROM governance.raw_records WHERE tenant_id ="
            " (SELECT tenant_id FROM platform.tenants WHERE slug = 'default')"
        )
    )
    await db_session.execute(
        text(f"DELETE FROM master.business_objects WHERE {_BO_SCOPE}")
    )
    await db_session.execute(text("DELETE FROM platform.systems WHERE name = 'erp'"))
    await db_session.commit()


async def _sync(
    app_role_engine: AsyncEngine, tenant_id: UUID, mode: str
) -> ingest_service.SyncStats:
    """单次同步：独立会话（bind_tenant → run_sync → commit）。"""
    session = async_sessionmaker(app_role_engine, expire_on_commit=False)()
    try:
        await bind_tenant(session, tenant_id)
        stats = await ingest_service.run_sync(
            session, tenant_id, ErpMockAdapter(), mode
        )
        await session.commit()
        return stats
    finally:
        await session.close()


async def _reconcile(
    app_role_engine: AsyncEngine, tenant_id: UUID
) -> dict[str, ingest_service.ReconciliationRow]:
    """对账（只读会话）；结果按 object_type 建查表。"""
    session = async_sessionmaker(app_role_engine, expire_on_commit=False)()
    try:
        await bind_tenant(session, tenant_id)
        rows = await ingest_service.reconcile(session, tenant_id, ErpMockAdapter())
    finally:
        await session.close()
    return {row.object_type: row for row in rows}


async def _scalar(
    db_session: AsyncSession,
    sql: str,
    tenant_id: UUID,
    params: dict | None = None,
) -> int:
    return (
        await db_session.execute(text(sql), {"t": tenant_id, **(params or {})})
    ).scalar_one()


async def _objects_count(db_session: AsyncSession, tenant_id: UUID) -> int:
    return await _scalar(
        db_session,
        f"SELECT count(*) FROM master.business_objects WHERE tenant_id = :t AND {_BO_SCOPE}",
        tenant_id,
    )


async def _snapshot_events_count(db_session: AsyncSession, tenant_id: UUID) -> int:
    return await _scalar(
        db_session,
        "SELECT count(*) FROM event.events"
        " WHERE tenant_id = :t AND event_type LIKE '%\\_SNAPSHOT'",
        tenant_id,
    )


async def _evidence_count(db_session: AsyncSession, tenant_id: UUID) -> int:
    return await _scalar(
        db_session,
        f"SELECT count(*) FROM evidence.records WHERE tenant_id = :t AND {_EV_SCOPE}",
        tenant_id,
    )


async def _evidence_versions(
    db_session: AsyncSession, tenant_id: UUID
) -> dict[str, set[str]]:
    """{source_id: {版本号集合}}（source_record_id 形如 SO-xxx#vN）。"""
    rows = (
        await db_session.execute(
            text(
                "SELECT source_record_id FROM evidence.records"
                " WHERE tenant_id = :t AND source_record_id LIKE 'SO-2026-%#v%'"
            ),
            {"t": tenant_id},
        )
    ).scalars()
    versions: dict[str, set[str]] = {}
    for source_record_id in rows:
        source_id, _, version = source_record_id.rpartition("#")
        versions.setdefault(source_id, set()).add(version)
    return versions


async def _order_revisions(
    db_session: AsyncSession, tenant_id: UUID
) -> dict[str, int]:
    rows = (
        await db_session.execute(
            text(
                "SELECT source_id, revision FROM master.business_objects"
                " WHERE tenant_id = :t AND source_id LIKE 'SO-2026-%'"
            ),
            {"t": tenant_id},
        )
    ).all()
    return {source_id: revision for source_id, revision in rows}


# ---- 1. full：三元组 60 落库 + 证据钉 v1 + 水位推进 + outbox 双写 ----


async def test_full_sync_registers_triple(
    app_role_engine: AsyncEngine, db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    stats = await _sync(app_role_engine, default_tenant_id, "full")
    assert stats == ingest_service.SyncStats(
        fetched=60, registered=60, duplicated=0, failed=0
    )
    assert await _objects_count(db_session, default_tenant_id) == 60
    assert await _snapshot_events_count(db_session, default_tenant_id) == 60
    assert await _evidence_count(db_session, default_tenant_id) == 60

    # 证据全部钉在首版（#v1 结尾）
    v1_rows = await _scalar(
        db_session,
        "SELECT count(*) FROM evidence.records"
        " WHERE tenant_id = :t AND source_record_id LIKE '%#v1'",
        default_tenant_id,
    )
    assert v1_rows == 60

    # 快照事件携带管道标记（SERVICE 主体 + data.via）
    marked = await _scalar(
        db_session,
        "SELECT count(*) FROM event.events WHERE tenant_id = :t"
        " AND event_type LIKE '%\\_SNAPSHOT'"
        " AND actor_type = 'SERVICE' AND actor_id = 'adapter:erp'"
        " AND data->>'via' = 'pipeline'",
        default_tenant_id,
    )
    assert marked == 60

    # outbox：每对象 ≥1（OBJECT_UPSERT + SNAPSHOT 事件双写 ≥ 120）
    outbox_rows = await _scalar(
        db_session,
        "SELECT count(*) FROM event.outbox WHERE aggregate_id IN"
        f" (SELECT object_id FROM master.business_objects WHERE {_BO_SCOPE})",
        default_tenant_id,
    )
    assert outbox_rows >= 60

    # 水位推进 = BASE 最大 occurred_at（严格早于窗口终点）
    watermark = (
        await db_session.execute(
            text(
                "SELECT last_watermark FROM platform.systems"
                " WHERE tenant_id = :t AND name = 'erp'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one()
    expected = max(r.occurred_at for r in ErpMockAdapter().fetch_full([]))
    assert watermark == expected
    assert watermark < WINDOW_END


# ---- 1b. T4 领域投影：管道同事务投影领域快照表 ----


async def test_full_sync_projects_domain_tables(
    app_role_engine: AsyncEngine, db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    """full 后：客户/物料快照行 > 0、sales.orders 行数 == ORDER 对象数
    （ErpMock 订单无 lines，order_lines 不参与断言）。"""
    stats = await _sync(app_role_engine, default_tenant_id, "full")
    assert stats.registered == 60

    order_objects = await _scalar(
        db_session,
        "SELECT count(*) FROM master.business_objects"
        " WHERE tenant_id = :t AND object_type = 'ORDER'",
        default_tenant_id,
    )
    customers = await _scalar(
        db_session,
        "SELECT count(*) FROM master.customers"
        " WHERE tenant_id = :t AND customer_id IN"
        f" (SELECT object_id FROM master.business_objects WHERE {_BO_SCOPE})",
        default_tenant_id,
    )
    materials = await _scalar(
        db_session,
        "SELECT count(*) FROM master.materials"
        " WHERE tenant_id = :t AND material_id IN"
        f" (SELECT object_id FROM master.business_objects WHERE {_BO_SCOPE})",
        default_tenant_id,
    )
    orders = await _scalar(
        db_session,
        "SELECT count(*) FROM sales.orders"
        " WHERE tenant_id = :t AND order_id IN"
        f" (SELECT object_id FROM master.business_objects WHERE {_BO_SCOPE})",
        default_tenant_id,
    )
    assert customers > 0
    assert materials > 0
    assert order_objects == 40
    assert orders == order_objects


# ---- 1c. T4 投影失败隔离：savepoint 回滚投影，三元组照常落库 ----


async def test_projection_failure_does_not_block_pipeline(
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """INVENTORY 引用不存在的物料 → delivery.inventory.material_id NOT NULL
    未命中抛 IntegrityError：savepoint 回滚投影写入，三元组仍完整落库；
    同会话后续记录继续处理成功（PendingRollback 会在该处炸）。"""
    bad = SourceRecord(
        source_system="erp",
        object_type="INVENTORY",
        source_id="M-301:WH-01",
        occurred_at=datetime(2026, 9, 16, 8, 0, tzinfo=UTC),
        payload={
            "owner_domain": "delivery",
            "material_code": "M-999",  # 不存在 → resolve 未命中 → FK NOT NULL
            "warehouse": "WH-01",
            "available": 1,
            "reserved": 0,
        },
    )
    good = SourceRecord(
        source_system="erp",
        object_type="ORDER",
        source_id="SO-2026-00999",
        occurred_at=datetime(2026, 9, 16, 9, 0, tzinfo=UTC),
        payload={
            "owner_domain": "sales",
            "name": "投影失败隔离用例",
            "amount": 100.0,
            "status": "已确认",
        },
    )

    session = async_sessionmaker(app_role_engine, expire_on_commit=False)()
    try:
        await bind_tenant(session, default_tenant_id)
        with caplog.at_level(logging.WARNING):
            assert (
                await ingest_service.process_record(session, default_tenant_id, bad)
                is True
            )
            # 前条投影失败未污染会话：后续记录照常注册
            assert (
                await ingest_service.process_record(session, default_tenant_id, good)
                is True
            )
        await session.commit()
    finally:
        await session.close()
    # 异常路径确实被触发（IntegrityError → savepoint 回滚 → warning 捕获）
    assert any("领域投影失败" in message for message in caplog.messages)

    object_id = (
        await db_session.execute(
            text(
                "SELECT object_id FROM master.business_objects"
                " WHERE tenant_id = :t AND source_id = 'M-301:WH-01'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one()
    # 三元组完整：事件/证据各 1
    assert (
        await _scalar(
            db_session,
            "SELECT count(*) FROM event.events"
            " WHERE tenant_id = :t AND object_id = :oid",
            default_tenant_id,
            {"oid": object_id},
        )
        == 1
    )
    assert (
        await _scalar(
            db_session,
            "SELECT count(*) FROM evidence.records"
            " WHERE tenant_id = :t AND source_record_id LIKE 'M-301:WH-01#v%'",
            default_tenant_id,
        )
        == 1
    )
    # 投影行缺失（savepoint 回滚，无半截行）
    assert (
        await _scalar(
            db_session,
            "SELECT count(*) FROM delivery.inventory"
            " WHERE tenant_id = :t AND inv_id = :oid",
            default_tenant_id,
            {"oid": object_id},
        )
        == 0
    )
    # 后续记录完整落库
    assert (
        await _scalar(
            db_session,
            "SELECT count(*) FROM event.events"
            " WHERE tenant_id = :t AND event_type = 'ORDER_SNAPSHOT'"
            " AND object_id = (SELECT object_id FROM master.business_objects"
            " WHERE tenant_id = :t AND source_id = 'SO-2026-00999')",
            default_tenant_id,
        )
        == 1
    )


# ---- 2. incremental（水位=full 后）：5 更新 revision=2/#v2 + 3 新对象 ----


async def test_incremental_sync_updates_and_inserts(
    app_role_engine: AsyncEngine, db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    await _sync(app_role_engine, default_tenant_id, "full")
    stats = await _sync(app_role_engine, default_tenant_id, "incremental")
    assert stats == ingest_service.SyncStats(
        fetched=8, registered=8, duplicated=0, failed=0
    )

    # 计数：对象 60+3、事件/证据 60+8
    assert await _objects_count(db_session, default_tenant_id) == 63
    assert await _snapshot_events_count(db_session, default_tenant_id) == 68
    assert await _evidence_count(db_session, default_tenant_id) == 68

    # 五更新对象 revision=2，证据出现 #v2（v1 快照保留）
    versions = await _evidence_versions(db_session, default_tenant_id)
    for source_id in UPDATED_ORDER_IDS:
        assert versions[source_id] == {"v1", "v2"}
    # 三新对象 revision=1，证据仅 #v1
    for source_id in NEW_ORDER_IDS:
        assert versions[source_id] == {"v1"}

    revisions = await _order_revisions(db_session, default_tenant_id)
    for source_id in UPDATED_ORDER_IDS:
        assert revisions[source_id] == 2
    for source_id in NEW_ORDER_IDS:
        assert revisions[source_id] == 1


# ---- 3. 重放 full：duplicated=60、计数与 revision 不变（幂等验收核心） ----


async def test_full_replay_is_idempotent(
    app_role_engine: AsyncEngine, db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    await _sync(app_role_engine, default_tenant_id, "full")
    await _sync(app_role_engine, default_tenant_id, "incremental")
    before = (
        await _objects_count(db_session, default_tenant_id),
        await _snapshot_events_count(db_session, default_tenant_id),
        await _evidence_count(db_session, default_tenant_id),
        await _order_revisions(db_session, default_tenant_id),
    )

    stats = await _sync(app_role_engine, default_tenant_id, "full")
    assert stats == ingest_service.SyncStats(
        fetched=60, registered=0, duplicated=60, failed=0
    )

    after = (
        await _objects_count(db_session, default_tenant_id),
        await _snapshot_events_count(db_session, default_tenant_id),
        await _evidence_count(db_session, default_tenant_id),
        await _order_revisions(db_session, default_tenant_id),
    )
    assert after == before  # 计数不变、revision 不动（含 5 个已推 v2 的对象）


# ---- 4. 重放 incremental：源自旧水位重发（at-least-once）→ duplicated=8 ----
#
# 语义说明：水位推进 = max(fetched occurred_at)、fetch 严格大于水位——正常
# 重跑 incremental 只会拉到 0 条（水位已越过 DELTA 末条）。"重放"指源侧自
# 旧检查点重发同一批（at-least-once 投递）：水位回拨到首次 incremental 前
# 的值再同步 → fetch 命中同 8 条 → 事件 UUIDv5 幂等全部收敛为 duplicated。


async def test_incremental_replay_duplicates(
    app_role_engine: AsyncEngine, db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    await _sync(app_role_engine, default_tenant_id, "full")
    watermark_before = (
        await db_session.execute(
            text(
                "SELECT last_watermark FROM platform.systems"
                " WHERE tenant_id = :t AND name = 'erp'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one()
    stats = await _sync(app_role_engine, default_tenant_id, "incremental")
    assert stats == ingest_service.SyncStats(
        fetched=8, registered=8, duplicated=0, failed=0
    )

    # 水位回拨（migrator 绕 RLS）模拟源自旧检查点重发同一批
    await db_session.execute(
        text(
            "UPDATE platform.systems SET last_watermark = :w"
            " WHERE tenant_id = :t AND name = 'erp'"
        ),
        {"w": watermark_before, "t": default_tenant_id},
    )
    await db_session.commit()

    replay = await _sync(app_role_engine, default_tenant_id, "incremental")
    assert replay == ingest_service.SyncStats(
        fetched=8, registered=0, duplicated=8, failed=0
    )
    assert await _evidence_count(db_session, default_tenant_id) == 68


# ---- 5. reconcile：全行 ok；删一条证据 → 该行 ok=False（evidence 少 1） ----


async def test_reconcile_detects_missing_evidence(
    app_role_engine: AsyncEngine, db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    await _sync(app_role_engine, default_tenant_id, "full")
    await _sync(app_role_engine, default_tenant_id, "incremental")

    rows = await _reconcile(app_role_engine, default_tenant_id)
    assert set(rows) == {"ORDER", "CUSTOMER", "MATERIAL"}
    order = rows["ORDER"]
    # 源记录级计数：48 = 40 BASE + 5 更新 + 3 新；objects 43 = 40 + 3（更新不新增）
    assert (order.source_count, order.edp_count_events, order.edp_count_evidence) == (
        48,
        48,
        48,
    )
    assert order.edp_count_objects == 43
    for row in rows.values():
        assert row.ok is True
        assert row.source_system == "erp"

    # migrator 删一行证据（绕 RLS）→ 仅 ORDER 行失配
    deleted = (
        await db_session.execute(
            text(
                "DELETE FROM evidence.records"
                " WHERE tenant_id = :t AND source_record_id = 'SO-2026-00203#v2'"
            ),
            {"t": default_tenant_id},
        )
    ).rowcount
    await db_session.commit()
    assert deleted == 1

    rows_after = await _reconcile(app_role_engine, default_tenant_id)
    assert rows_after["ORDER"].ok is False
    assert rows_after["ORDER"].edp_count_evidence == 47
    assert rows_after["CUSTOMER"].ok is True
    assert rows_after["MATERIAL"].ok is True


# ---- 6. RLS：default 租户管道数据在 tenant-b 会话 0 可见 ----


async def test_rls_isolates_pipeline_data(
    app_role_engine: AsyncEngine, default_tenant_id: UUID
) -> None:
    await _sync(app_role_engine, default_tenant_id, "full")

    session = async_sessionmaker(app_role_engine)()
    try:
        await bind_tenant(session, uuid4())  # 任意非 default 租户上下文
        objects = (
            await session.execute(
                text(
                    "SELECT count(*) FROM master.business_objects"
                    " WHERE source_system = 'erp'"
                )
            )
        ).scalar_one()
        assert objects == 0
        evidence = (
            await session.execute(
                text("SELECT count(*) FROM evidence.records WHERE source_system = 'erp'")
            )
        ).scalar_one()
        assert evidence == 0
        events = (
            await session.execute(
                text("SELECT count(*) FROM event.events WHERE event_type LIKE '%\\_SNAPSHOT'")
            )
        ).scalar_one()
        assert events == 0
    finally:
        await session.close()


# ---- 7. 审计覆盖：装切面后每 registered 记录 3 行（OBJECT/EVENT/EVIDENCE）
# ----    + 每次 sync 1 行 SYSTEMS_*；outbox 派生行被排除 ----
#
# 切面仅由宿主安装（create_app / CLI），直调 service 层的测试须自行
# install_audit_aspect（幂等，Session 类级全局监听）。全量运行时切面已随
# test_audit 的 create_app 装配（此处 no-op）；单文件运行时自此全局生效——
# 本用例置于文件末尾，前序用例保持"未装切面"形态不受影响（EVENT_CREATE
# 为管道显式补点，装否皆在；OBJECT/EVIDENCE/SYSTEMS 行依赖切面）。


async def _audit_count(
    db_session: AsyncSession, tenant_id: UUID, action: str
) -> int:
    return (
        await db_session.execute(
            text(
                "SELECT count(*) FROM platform.audit_logs"
                " WHERE tenant_id = :t AND actor_id = 'adapter:erp' AND action = :a"
            ),
            {"t": tenant_id, "a": action},
        )
    ).scalar_one()


async def test_audit_aspect_covers_pipeline(
    app_role_engine: AsyncEngine, db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    install_audit_aspect()
    stats = await _sync(app_role_engine, default_tenant_id, "full")
    assert stats.registered == 60

    # 每条 registered 记录恰三行：OBJECT_CREATE（切面）+ EVENT_CREATE（显式）
    # + EVIDENCE_CREATE（切面），actor 均收敛为 SERVICE/adapter:erp
    assert await _audit_count(db_session, default_tenant_id, "OBJECT_CREATE") == 60
    assert await _audit_count(db_session, default_tenant_id, "EVENT_CREATE") == 60
    assert await _audit_count(db_session, default_tenant_id, "EVIDENCE_CREATE") == 60
    # 每次 sync 至多一行 SYSTEMS_*（首次同步为水位登记 CREATE）
    assert await _audit_count(db_session, default_tenant_id, "SYSTEMS_CREATE") == 1
    # outbox 为派生行，切面排除
    assert await _scalar(
        db_session,
        "SELECT count(*) FROM platform.audit_logs"
        " WHERE tenant_id = :t AND resource_type = 'outbox'",
        default_tenant_id,
    ) == 0
    # 领域投影行（T4）同样为派生快照 → 13 张领域表零审计行（排除生效直证）
    assert (
        await _scalar(
            db_session,
            "SELECT count(*) FROM platform.audit_logs"
            " WHERE tenant_id = :t AND actor_id = 'adapter:erp'"
            " AND resource_type = ANY(:types)",
            default_tenant_id,
            {"types": _DOMAIN_AUDIT_TABLES},
        )
        == 0
    )
