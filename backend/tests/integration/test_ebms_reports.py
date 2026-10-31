"""T3 EBMS 查询补齐集成测试（EDP-012 残余）：summary/pending/todos/objectives。

覆盖：
1. seed 后 summary 三段：objectives（period 缺省 = 锚当月、status=ACTIVE）、
   kpis（每 code 最近值 = 锚 ISO 当周）、recent_changes_summary（风险事件
   最近 5 条 ``订单 {order_no} {summary}`` 文案，最近一条为场景 10）；
2. pending：默认 5 条 + total_pending 全量计数；risk（P0→P3）+ created_at
   排序（额外造 6 条 OPEN 案例，实测 7 全量）；limit 边界（0/21 → 422）；
3. todos 三段计数与构造一致：pending_decisions（OPEN top 5）、
   pending_actions（非终态行动，due_date 升序空值在后，VERIFIED 终态排除）、
   exceptions_to_confirm（10 风险事件 − 场景 2 有案例 = 9）；
4. objectives 完整列表（含非 ACTIVE；与 summary 的 ACTIVE 过滤互补）；
5. ANALYST JWT 200（ebms:read 四角色轨道）；
6. 跨租户隔离：B 租户（readonly Key）经 RLS 查不到 A 的 management/案例/
   事件数据（四端点全空）。

会话形态：应用引擎 = conftest.app_role_engine（edp_app，FORCE RLS）；断言以
migrator db_session 直查（绕 RLS）。清场：purge_tenant_business_data（含
management 段）+ 本模块审计行/临时 Key/tenant-ebms-r。
"""

import re
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.core.security.apikey import hash_key
from edp_api.main import create_app
from edp_api.modules.demo import service as demo_service
from edp_api.modules.tenantmgmt import service as tenantmgmt_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

SUMMARY = "/api/v1/ebms/reports/summary"
PENDING = "/api/v1/ebms/decisions/pending"
TODOS = "/api/v1/ebms/todos"
OBJECTIVES = "/api/v1/ebms/objectives"
DEV_KEY = "edp-dev-agent-hub-key"
DEV_HEADERS = {"X-API-Key": DEV_KEY}
LOGIN = "/api/v1/auth/login"
SEED_PASSWORD = "Admin@123!"

# 跨租户用例的 B 租户（migrator 直造；readonly Key）
TENANT_B_SLUG = "tenant-ebms-r"
TENANT_B_KEY = "t3-ebms-tenant-b-key"
TENANT_B_PRINCIPAL = "t3-ebms-tenant-b"


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS）。"""
    await core_db.dispose_engine()
    monkeypatch.setattr(core_db, "get_engine", lambda: app_role_engine)
    transport = httpx.ASGITransport(app=create_app())
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        await core_db.dispose_engine()  # 重置绑定到测试引擎的会话工厂


@pytest.fixture
async def default_tenant_id(db_session: AsyncSession) -> UUID:
    """default 租户 id（0005 种子；tenants 控制面表，migrator 直查）。"""
    return (
        await db_session.execute(
            text("SELECT tenant_id FROM platform.tenants WHERE slug = 'default'")
        )
    ).scalar_one()


@pytest.fixture
async def demo(
    app_role_engine: AsyncEngine, default_tenant_id: UUID
) -> demo_service.SeedStats:
    """default 租户演示数据集（含 W4 management 段）；清场见 _clean_rows。"""
    stats = await demo_service.seed(app_role_engine, default_tenant_id)
    assert stats.failed == 0
    assert stats.mgmt_inserted == 12
    return stats


@pytest.fixture(autouse=True)
async def _clean_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    """每测试后清场：default 业务行（含 management）+ 本模块审计行/tenant-B
    （migrator 绕 RLS）。"""
    yield
    await demo_service.purge_tenant_business_data(db_session, default_tenant_id)
    await db_session.execute(
        text(
            "DELETE FROM platform.audit_logs WHERE tenant_id = :t"
            " AND actor_id IN ('adapter:erp', 'agent-hub')"
        ),
        {"t": default_tenant_id},
    )
    b_ids = "SELECT tenant_id FROM platform.tenants WHERE slug = 'tenant-ebms-r'"
    await db_session.execute(
        text("DELETE FROM platform.api_keys WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM platform.tenant_members WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM platform.users WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text(
            "DELETE FROM platform.tenant_usage_daily WHERE tenant_id IN"
            " (" + b_ids + ")"
        )
    )
    await db_session.execute(
        text("DELETE FROM platform.tenants WHERE slug = 'tenant-ebms-r'")
    )
    await db_session.commit()


async def _login(client: httpx.AsyncClient, username: str) -> dict[str, str]:
    resp = await client.post(
        LOGIN, json={"username": username, "password": SEED_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _insert_open_case(
    db_session: AsyncSession,
    tenant_id: UUID,
    *,
    case_no: str,
    question: str,
    risk_level: str,
    created_at,
) -> UUID:
    """直造一条 OPEN 案例（raw SQL 绕 ORM 审计；source_id 留空不挂事件）。"""
    case_id = uuid4()
    await db_session.execute(
        text(
            """
            INSERT INTO decision.cases
                (case_id, tenant_id, case_no, question, context, options,
                 risk_level, status, created_at)
            VALUES
                (:case_id, :t, :case_no, :question, '{}'::jsonb,
                 CAST(:options AS jsonb), :risk, 'OPEN', :created_at)
            """
        ),
        {
            "case_id": case_id,
            "t": tenant_id,
            "case_no": case_no,
            "question": question,
            "options": '[{"key": "HOLD", "label": "暂缓"}]',
            "risk": risk_level,
            "created_at": created_at,
        },
    )
    await db_session.commit()
    return case_id


async def _insert_action(
    db_session: AsyncSession,
    tenant_id: UUID,
    *,
    title: str,
    status: str,
    due_date,
) -> UUID:
    """直造一条行动（raw SQL；状态/due_date 由用例指定）。"""
    action_id = uuid4()
    await db_session.execute(
        text(
            """
            INSERT INTO action.actions
                (action_id, tenant_id, title, action_type, status, due_date)
            VALUES
                (:action_id, :t, :title, 'MITIGATION', :status, :due_date)
            """
        ),
        {
            "action_id": action_id,
            "t": tenant_id,
            "title": title,
            "status": status,
            "due_date": due_date,
        },
    )
    await db_session.commit()
    return action_id


async def _seed_case_row(db_session: AsyncSession, tenant_id: UUID):
    """seed 场景 2 案例（case_id, created_at）——排序基准。"""
    return (
        await db_session.execute(
            text(
                "SELECT case_id, created_at FROM decision.cases"
                " WHERE tenant_id = :t AND source_type = 'capability.result'"
            ),
            {"t": tenant_id},
        )
    ).one()


# ---- 1. summary 三段 ----


async def test_summary_three_segments_after_seed(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    anchor = await tenantmgmt_service.get_demo_anchor(db_session, default_tenant_id)
    assert anchor is not None
    month = f"{anchor.year:04d}-{anchor.month:02d}"
    iso = anchor.isocalendar()
    week = f"{iso.year:04d}-W{iso.week:02d}"

    resp = await client.get(SUMMARY, headers=DEV_HEADERS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["period"] == month

    # objectives：3 条 ACTIVE 目标（period 缺省 = 锚当月）
    objectives = body["objectives"]
    assert len(objectives) == 3
    by_title = {item["title"]: item for item in objectives}
    q4 = by_title["Q4 准时交付率"]
    assert q4["target_value"] == 95.0
    assert q4["current_value"] == 91.2
    assert q4["status"] == "ACTIVE"
    UUID(q4["objective_id"])
    assert {item["current_value"] for item in objectives} == {91.2, 7.2, 86.5}

    # kpis：每 code 最近值（锚当周）
    kpis = {item["code"]: item for item in body["kpis"]}
    assert set(kpis) == {"on_time_delivery", "inventory_turnover", "risk_closure_rate"}
    assert kpis["on_time_delivery"]["name"] == "准时交付率"
    assert kpis["on_time_delivery"]["value"] == 91.2
    assert kpis["on_time_delivery"]["unit"] == "%"
    assert kpis["on_time_delivery"]["period"] == week
    assert kpis["inventory_turnover"]["value"] == 7.2

    # recent_changes_summary：最近 5 条「订单 {order_no} {summary}」
    changes = body["recent_changes_summary"]
    assert len(changes) == 5
    assert all(item.startswith("订单 ") for item in changes)
    # 最近风险事件 = 场景 10（anchor - 18min，order_no=PLM）
    assert changes[0] == "订单 PLM PLM 同步失败（工具调用故障），里程碑数据待更新"

    # 显式 period 无匹配：objectives 空、kpis 不受 period 参数影响
    resp = await client.get(
        SUMMARY, params={"period": "2099-01"}, headers=DEV_HEADERS
    )
    assert resp.status_code == 200, resp.text
    empty = resp.json()
    assert empty["period"] == "2099-01"
    assert empty["objectives"] == []
    assert len(empty["kpis"]) == 3
    assert len(empty["recent_changes_summary"]) == 5


# ---- 2. pending：排序 + limit + total_pending ----


async def test_pending_limit_ordering_and_total(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    seed_case = await _seed_case_row(db_session, default_tenant_id)
    base = seed_case.created_at
    # 6 条额外 OPEN 案例（risk × created_at 组合覆盖排序维度；seed 1 条 → 7 全量）
    specs = [("P0", 1), ("P2", 2), ("P1", 3), ("P2", 4), ("P3", 5), ("P2", 6)]
    extras = [
        await _insert_open_case(
            db_session,
            default_tenant_id,
            case_no=f"DC-T3-E{idx:03d}",
            question=f"额外待决案例 {idx}",
            risk_level=risk,
            created_at=base + timedelta(minutes=offset),
        )
        for idx, (risk, offset) in enumerate(specs, start=1)
    ]

    resp = await client.get(PENDING, headers=DEV_HEADERS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_pending"] == 7
    items = body["items"]
    assert len(items) == 5
    # 期望序：P0 extra1 → P1 seed(最早) → P1 extra3 → P2 extra2 → P2 extra4
    assert [item["case_id"] for item in items] == [
        str(extras[0]),
        str(seed_case.case_id),
        str(extras[2]),
        str(extras[1]),
        str(extras[3]),
    ]
    rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    ranks = [rank[item["risk_level"]] for item in items]
    assert ranks == sorted(ranks)

    # seed 案例字段透传（case_no/question/options）
    seed_item = items[1]
    assert re.fullmatch(r"DC-\d{8}-\d{3}", seed_item["case_no"])
    assert seed_item["question"].startswith("订单 SO-2026-00123")
    assert {option["key"] for option in seed_item["options"]} == {
        "EXPEDITE",
        "SUBSTITUTE",
        "REJECT",
    }
    assert seed_item["created_at"]

    resp = await client.get(PENDING, params={"limit": 2}, headers=DEV_HEADERS)
    assert resp.status_code == 200, resp.text
    assert resp.json()["total_pending"] == 7
    assert len(resp.json()["items"]) == 2

    # limit 边界（1..20 外）→ 400 VALIDATION_ERROR（app 级 Query 校验映射）
    for bad_limit in (0, 21):
        resp = await client.get(
            PENDING, params={"limit": bad_limit}, headers=DEV_HEADERS
        )
        assert resp.status_code == 400, resp.text
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


# ---- 3. todos 三段 ----


async def test_todos_three_segments_counts(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    seed_case = await _seed_case_row(db_session, default_tenant_id)
    base = seed_case.created_at
    # OPEN 案例 7 条（seed + 6 extra）→ pending_decisions top 5
    for idx in range(6):
        await _insert_open_case(
            db_session,
            default_tenant_id,
            case_no=f"DC-T3-T{idx:03d}",
            question=f"待办案例 {idx}",
            risk_level="P2",
            created_at=base + timedelta(minutes=idx + 1),
        )
    # 行动：EXECUTING（有 due）+ ACCEPTED（无 due，空值在后）+ VERIFIED（终态排除）
    executing_id = await _insert_action(
        db_session,
        default_tenant_id,
        title="加急采购物料X",
        status="EXECUTING",
        due_date=base + timedelta(days=2),
    )
    accepted_id = await _insert_action(
        db_session,
        default_tenant_id,
        title="替代料验证",
        status="ACCEPTED",
        due_date=None,
    )
    await _insert_action(
        db_session,
        default_tenant_id,
        title="已验证行动（不在待办）",
        status="VERIFIED",
        due_date=base + timedelta(days=3),
    )

    resp = await client.get(TODOS, headers=DEV_HEADERS)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # pending_decisions：OPEN top 5（risk + created_at 序）
    decisions = body["pending_decisions"]
    assert len(decisions) == 5
    for item in decisions:
        UUID(item["case_id"])
        assert item["risk_level"]
        assert item["created_at"]
    assert str(seed_case.case_id) in {item["case_id"] for item in decisions}

    # pending_actions：非终态、due_date 升序空值在后；VERIFIED 不在列
    actions = body["pending_actions"]
    assert [item["action_id"] for item in actions] == [
        str(executing_id),
        str(accepted_id),
    ]
    assert actions[0]["title"] == "加急采购物料X"
    assert actions[0]["status"] == "EXECUTING"
    assert actions[0]["due_date"]
    assert actions[1]["due_date"] is None

    # exceptions_to_confirm：10 风险事件 − 场景 2（有案例）= 9
    exceptions = body["exceptions_to_confirm"]
    assert len(exceptions) == 9
    for item in exceptions:
        UUID(item["event_id"])
        assert item["risk_level"] in {"P0", "P1", "P2", "P3"}


# ---- 4. objectives 完整列表（与 summary ACTIVE 过滤互补） ----


async def test_objectives_full_list_vs_summary_active_filter(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    anchor = await tenantmgmt_service.get_demo_anchor(db_session, default_tenant_id)
    month = f"{anchor.year:04d}-{anchor.month:02d}"
    await db_session.execute(
        text(
            """
            INSERT INTO management.objectives
                (objective_id, tenant_id, title, metric_type, target_value,
                 current_value, period, status)
            VALUES
                (:objective_id, :t, '已取消目标', 'legacy', 1.0, 0.5,
                 :period, 'CANCELLED')
            """
        ),
        {
            "objective_id": uuid4(),
            "t": default_tenant_id,
            "period": month,
        },
    )
    await db_session.commit()

    resp = await client.get(OBJECTIVES, headers=DEV_HEADERS)
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) == 4  # 全量：3 ACTIVE seed + 1 CANCELLED
    by_title = {item["title"]: item for item in items}
    assert by_title["已取消目标"]["status"] == "CANCELLED"
    assert by_title["Q4 准时交付率"]["target_value"] == 95.0

    resp = await client.get(SUMMARY, headers=DEV_HEADERS)
    assert resp.status_code == 200, resp.text
    summary_titles = {item["title"] for item in resp.json()["objectives"]}
    assert summary_titles == {"Q4 准时交付率", "库存周转率", "新品按时量产率"}


# ---- 5. ANALYST JWT 200（四端点） ----


async def test_analyst_reads_all_four_endpoints(
    client: httpx.AsyncClient, demo: demo_service.SeedStats
) -> None:
    headers = await _login(client, "analyst1")
    for path in (SUMMARY, PENDING, TODOS, OBJECTIVES):
        resp = await client.get(path, headers=headers)
        assert resp.status_code == 200, (path, resp.text)


# ---- 6. 跨租户隔离：B 租户四端点全空（RLS） ----


async def test_cross_tenant_not_leaked(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    tenant_b = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO platform.tenants (tenant_id, slug, name, status)"
            " VALUES (:t, :slug, '租户EBMSR', 'ACTIVE')"
        ),
        {"t": tenant_b, "slug": TENANT_B_SLUG},
    )
    await db_session.commit()
    await db_session.execute(
        text(
            """
            INSERT INTO platform.api_keys
                (key_id, key_hash, tenant_id, principal_type, principal_id,
                 scopes, status)
            VALUES (:key_id, :key_hash, :t, 'SERVICE', :principal,
                    CAST(:scopes AS text[]), 'ACTIVE')
            """
        ),
        {
            "key_id": uuid4(),
            "key_hash": hash_key(TENANT_B_KEY),
            "t": tenant_b,
            "principal": TENANT_B_PRINCIPAL,
            "scopes": ["readonly"],
        },
    )
    await db_session.commit()
    headers = {"X-API-Key": TENANT_B_KEY}

    resp = await client.get(SUMMARY, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["period"] is None
    assert body["objectives"] == []
    assert body["kpis"] == []
    assert body["recent_changes_summary"] == []

    resp = await client.get(PENDING, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"items": [], "total_pending": 0}

    resp = await client.get(TODOS, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "pending_decisions": [],
        "pending_actions": [],
        "exceptions_to_confirm": [],
    }

    resp = await client.get(OBJECTIVES, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == []
