"""T5 seed 放大（--scale N）集成测试（W6/EDP-033 压测前置）：三类计数公式 /
幂等重跑 / RESET 回基线 / 活动事件风险分布 / 十类场景基线不受放大影响。

计数公式（与 demo.service 放大段实现同口径——常数与 risk 派生引自
dataset 单一实现，防测试口径漂移）：
- 对象 = SNAPSHOT_COUNT × scale（每单元 43 个后缀副本对象）；
- 事件 = 基线（SNAPSHOT_COUNT + RESULT_COUNT）+ (scale-1) × SNAPSHOT_COUNT
  × (1 + SCALE_ACTIVITY_PER_OBJECT)（快照事件 + 活动事件）；
- 证据 = 基线（SNAPSHOT_COUNT + RESULT_COUNT）+ (scale-1) × SNAPSHOT_COUNT
  × 2（快照证据 + k=0 checksum 证据）+ 活动事件 P0/P1 数（结果证据）。

放大实体后缀约定（dataset 尾段）：source_id 六位数字尾缀
（'-[0-9]{6}$'）——基线 ORDER/PO 尾段为 5 位数字，模式不误伤；T12 运营
报告按此模式在 SQL 侧排除放大实体。

会话形态与清场同 test_demo_seed：seed 以 app_role_engine（edp_app，FORCE
RLS）运行；断言以 migrator db_session 直查；每测试后清业务行 + 本模块
审计行（actor=adapter:erp）。
"""

from uuid import UUID

import pytest
from edp_adapters.demo_dataset import SNAPSHOT_RECORDS
from edp_api.modules.audit.aspect import install_audit_aspect
from edp_api.modules.demo import service as demo_service
from edp_api.modules.demo.dataset import (
    RESULT_EVENTS,
    SCALE_ACTIVITY_PER_OBJECT,
    scaled_risk_level,
)
from edp_api.modules.evidence import service as evidence_service
from edp_api.modules.tenantmgmt import service as tenantmgmt_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [pytest.mark.integration]

SNAPSHOT_COUNT = len(SNAPSHOT_RECORDS)
RESULT_COUNT = len(RESULT_EVENTS)
# 基线事件/证据：43 快照 + 10 结果事件（结果证据 = risk_level 非空全 10 条）
BASELINE_EVENTS = SNAPSHOT_COUNT + RESULT_COUNT
SCALE_SUFFIX_PATTERN = r"-[0-9]{6}$"


def _expected_activity(scale: int) -> int:
    return (scale - 1) * SNAPSHOT_COUNT * SCALE_ACTIVITY_PER_OBJECT


def _expected_risky(scale: int) -> int:
    return sum(
        1
        for seq in range(_expected_activity(scale))
        if scaled_risk_level(seq) is not None
    )


def _expected_counts(scale: int) -> dict[str, int]:
    appended_units = scale - 1
    return {
        "objects": SNAPSHOT_COUNT * scale,
        "events": BASELINE_EVENTS
        + appended_units * SNAPSHOT_COUNT * (1 + SCALE_ACTIVITY_PER_OBJECT),
        "evidence": BASELINE_EVENTS
        + appended_units * SNAPSHOT_COUNT * 2
        + _expected_risky(scale),
    }


@pytest.fixture
async def default_tenant_id(db_session: AsyncSession) -> UUID:
    """default 租户 id（0005 种子；tenants 控制面表，migrator 直查）。"""
    return (
        await db_session.execute(
            text("SELECT tenant_id FROM platform.tenants WHERE slug = 'default'")
        )
    ).scalar_one()


@pytest.fixture(autouse=True)
def _install_aspect() -> None:
    """seed 的 ORM 写（对象/证据/水位）依赖切面落审计——与 CLI 同一装配。"""
    install_audit_aspect()


@pytest.fixture(autouse=True)
async def _clean_demo_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    """每测试后清场：逆依赖序业务行 + 本模块审计行（actor=adapter:erp）。"""
    yield
    await demo_service.purge_tenant_business_data(db_session, default_tenant_id)
    await db_session.execute(
        text(
            "DELETE FROM platform.audit_logs"
            " WHERE tenant_id = :t AND actor_id = 'adapter:erp'"
        ),
        {"t": default_tenant_id},
    )
    await db_session.commit()


async def _count(
    db_session: AsyncSession, tenant_id: UUID, sql: str, **params: object
) -> int:
    return (await db_session.execute(text(sql), {"t": tenant_id, **params})).scalar_one()


async def _trio_counts(
    db_session: AsyncSession, tenant_id: UUID
) -> dict[str, int]:
    """幂等断言用的三类计数快照（对象/事件/证据）。"""
    return {
        name: await _count(db_session, tenant_id, sql)
        for name, sql in (
            (
                "objects",
                "SELECT count(*) FROM master.business_objects WHERE tenant_id = :t",
            ),
            ("events", "SELECT count(*) FROM event.events WHERE tenant_id = :t"),
            (
                "evidence",
                "SELECT count(*) FROM evidence.records WHERE tenant_id = :t",
            ),
        )
    }


async def test_scale_3_counts_match_formula(
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    stats = await demo_service.seed(app_role_engine, default_tenant_id, scale=3)

    assert stats.failed == 0
    assert stats.fetched == SNAPSHOT_COUNT * 3
    assert stats.registered == SNAPSHOT_COUNT * 3
    assert stats.duplicated == 0
    assert stats.events_accepted == RESULT_COUNT + _expected_activity(3)
    assert await _trio_counts(db_session, default_tenant_id) == _expected_counts(3)

    # 后缀圈定：放大对象恰 (scale-1)×43，基线对象全集不受影响
    # （基线 ORDER/PO 尾段 5 位数字——六位模式不误伤，T12 排除约定）
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM master.business_objects"
            f" WHERE tenant_id = :t AND source_id ~ '{SCALE_SUFFIX_PATTERN}'",
        )
        == (3 - 1) * SNAPSHOT_COUNT
    )
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM master.business_objects"
            f" WHERE tenant_id = :t AND source_id !~ '{SCALE_SUFFIX_PATTERN}'",
        )
        == SNAPSHOT_COUNT
    )

    # 活动事件类型区隔十类场景本体
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM event.events"
            " WHERE tenant_id = :t AND event_type LIKE '%.activity'",
        )
        == _expected_activity(3)
    )

    # 领域投影随单元放大（真实数据形状）：订单/行/交期/产能 = 基线 ×3
    for table, baseline in (
        ("sales.orders", 10),
        ("sales.order_lines", 11),
        ("delivery.supplier_lead_times", 6),
        ("delivery.capacity", 3),
        ("master.customers", 7),
    ):
        assert (
            await _count(
                db_session,
                default_tenant_id,
                f"SELECT count(*) FROM {table} WHERE tenant_id = :t",
            )
            == baseline * 3
        )

    # 单元内自洽引用图：放大订单行 FK 全解析（无 NULL 产品/物料的放大行）
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM sales.order_lines ol"
            " JOIN sales.orders o ON o.order_id = ol.order_id AND o.tenant_id = ol.tenant_id"
            " WHERE ol.tenant_id = :t AND o.order_no ~"
            f" '{SCALE_SUFFIX_PATTERN}'"
            " AND ol.product_id IS NULL AND ol.material_id IS NULL",
        )
        == 0
    )


async def test_scale_rerun_same_scale_is_idempotent(
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await demo_service.seed(app_role_engine, default_tenant_id, scale=3)
    counts_before = await _trio_counts(db_session, default_tenant_id)
    anchor_before = await tenantmgmt_service.get_demo_anchor(
        db_session, default_tenant_id
    )

    second = await demo_service.seed(app_role_engine, default_tenant_id, scale=3)

    assert second.failed == 0
    assert second.fetched == SNAPSHOT_COUNT * 3
    assert second.registered == 0
    assert second.duplicated == SNAPSHOT_COUNT * 3
    assert second.events_accepted == 0
    assert second.events_duplicated == RESULT_COUNT + _expected_activity(3)
    assert await _trio_counts(db_session, default_tenant_id) == counts_before
    assert (
        await tenantmgmt_service.get_demo_anchor(db_session, default_tenant_id)
        == anchor_before
    )


async def test_scale_reset_returns_to_baseline(
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await demo_service.seed(app_role_engine, default_tenant_id, scale=3)

    reset = await demo_service.seed(app_role_engine, default_tenant_id, reset=True)

    assert reset.failed == 0
    assert reset.registered == SNAPSHOT_COUNT
    assert reset.events_accepted == RESULT_COUNT
    assert await _trio_counts(db_session, default_tenant_id) == _expected_counts(1)
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM master.business_objects"
            f" WHERE tenant_id = :t AND source_id ~ '{SCALE_SUFFIX_PATTERN}'",
        )
        == 0
    )
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM event.events"
            " WHERE tenant_id = :t AND event_type LIKE '%.activity'",
        )
        == 0
    )


async def test_scale_activity_risk_distribution(
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    """放大活动事件：稀疏 P0/P1 存在、NONE（risk 为空）占多数；风险事件
    恒带结果证据（RESULT link）、每放大对象恒带 k=0 checksum 证据（verify
    可复算）。"""
    await demo_service.seed(app_role_engine, default_tenant_id, scale=3)

    rows = (
        await db_session.execute(
            text(
                "SELECT risk_level, count(*) AS n FROM event.events"
                " WHERE tenant_id = :t AND event_type LIKE '%.activity'"
                " GROUP BY risk_level"
            ),
            {"t": default_tenant_id},
        )
    ).all()
    by_risk = {row.risk_level: row.n for row in rows}

    expected_p0 = sum(
        1
        for seq in range(_expected_activity(3))
        if scaled_risk_level(seq) == "P0"
    )
    expected_p1 = sum(
        1
        for seq in range(_expected_activity(3))
        if scaled_risk_level(seq) == "P1"
    )
    assert expected_p0 >= 1 and expected_p1 >= 1
    assert by_risk.get("P0") == expected_p0
    assert by_risk.get("P1") == expected_p1
    none_count = by_risk.get(None, 0)
    assert none_count == _expected_activity(3) - expected_p0 - expected_p1
    assert none_count > expected_p0 + expected_p1

    # 每个风险活动事件恰一条结果证据（RESULT link 指向该事件）
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM evidence.links l"
            " JOIN event.events e ON e.event_id = l.ref_id AND e.tenant_id = l.tenant_id"
            " WHERE l.tenant_id = :t AND l.ref_type = 'RESULT'"
            "  AND e.event_type LIKE '%.activity'"
            "  AND e.risk_level IN ('P0', 'P1')",
        )
        == expected_p0 + expected_p1
    )

    # 每放大对象一条 k=0 checksum 证据，checksum 可按单一实现复算
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM evidence.records"
            " WHERE tenant_id = :t AND source_record_id LIKE '%#activity'",
        )
        == (3 - 1) * SNAPSHOT_COUNT
    )
    evidence = (
        await db_session.execute(
            text(
                "SELECT checksum, snapshot FROM evidence.records"
                " WHERE tenant_id = :t AND source_record_id LIKE '%#activity'"
                " LIMIT 1"
            ),
            {"t": default_tenant_id},
        )
    ).one()
    assert evidence_service.compute_checksum(evidence.snapshot) == evidence.checksum


async def test_scale_keeps_baseline_scenarios_intact(
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    """十类场景本体不放大：结果事件/案例/场景 2 关键料缺失实体恒为基线。"""
    await demo_service.seed(app_role_engine, default_tenant_id, scale=3)

    # 场景本体事件恒基线计数（capability.result.* 9 + adapter.sync.failed 1）
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM event.events"
            " WHERE tenant_id = :t AND event_type LIKE 'capability.result.%'",
        )
        == 9
    )
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM event.events"
            " WHERE tenant_id = :t AND event_type = 'adapter.sync.failed'",
        )
        == 1
    )

    # 场景 2 关键料缺失实体：订单对象 / P1 结果事件 / X-100@WH-01 缺口库存
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM master.business_objects"
            " WHERE tenant_id = :t AND object_type = 'ORDER'"
            "  AND source_id = 'SO-2026-00123'",
        )
        == 1
    )
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM event.events e"
            " JOIN master.business_objects bo"
            "   ON bo.object_id = e.object_id AND bo.tenant_id = e.tenant_id"
            " WHERE e.tenant_id = :t AND e.event_type = 'capability.result.order_risk'"
            "  AND e.risk_level = 'P1' AND bo.source_id = 'SO-2026-00123'",
        )
        == 1
    )
    assert (
        await _count(
            db_session,
            default_tenant_id,
            """
            SELECT count(*) FROM delivery.inventory i
            JOIN master.materials m ON m.material_id = i.material_id
              AND m.tenant_id = i.tenant_id
            WHERE i.tenant_id = :t AND m.code = 'X-100' AND i.warehouse = 'WH-01'
              AND i.quantity_available = 0
            """,
        )
        == 1
    )

    # 场景 2 决策案例唯一，CASE 证据链 3 条
    case = (
        await db_session.execute(
            text(
                "SELECT case_id, risk_level, source_type FROM decision.cases"
                " WHERE tenant_id = :t"
            ),
            {"t": default_tenant_id},
        )
    ).one()
    assert case.risk_level == "P1"
    assert case.source_type == "capability.result"
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM evidence.links"
            " WHERE tenant_id = :t AND ref_type = 'CASE' AND ref_id = :case_id",
            case_id=case.case_id,
        )
        == 3
    )
