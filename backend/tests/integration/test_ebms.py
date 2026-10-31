"""T11 EBMS exceptions 集成测试（EDP-012 子集）：风险事件查询 + case 关联。

覆盖：
1. seed 后默认列表（status=OPEN）：10 条 = 十场景结果事件（P0×1/P1×3/P2×4/P3×2，
   occurred_at DESC）。**偏差记录**：spec §6.1 条件为 ``risk_level IS NOT NULL``，
   故场景 1/6 的 P3 行也在列（真实 10 条 vs MSW mock 8 条）；本轮实现按 spec，
   不额外加 severity 下限，T14 契约偏差清单留痕；
2. severity 过滤：P0→1 条（场景 7）/P1→3 条（场景 2/5/9）/P3→2 条（场景 1/6）；
3. 场景 2 的 case_id 非空且等于 seed 案例；其余行 case_id=null；
4. order_no/summary 回退链（spec §6.1）：order_no = data.order_no → 对象
   source_id；summary = data.summary → data.reason → event_type；
5. 游标分页：limit=3 翻页至尽——10 个 event_id 无重无漏、occurred_at 全局降序；
6. status 切换（真实 join 语义）：HUMAN 决策案例后 RESOLVED 命中场景 2、
   OPEN 不再含它（决策前 RESOLVED 为空）；
7. 跨租户：tenant-ebms（readonly Key）列表为空，不泄露 default 数据；
8. 双轨鉴权：HUMAN（manager1/analyst1，含 ebms:read）200；无 readonly scope
   临时 Key → 403 FORBIDDEN。

会话形态：应用引擎 = conftest.app_role_engine（edp_app，FORCE RLS）；断言以
migrator db_session 直查（绕 RLS）。清场：purge_tenant_business_data（逆依赖
序）+ 本模块审计行/临时 Key/tenant-ebms。
"""

from uuid import UUID, uuid4

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.core.security.apikey import hash_key
from edp_api.main import create_app
from edp_api.modules.demo import service as demo_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

BASE = "/api/v1/ebms/exceptions"
DEV_KEY = "edp-dev-agent-hub-key"
DEV_HEADERS = {"X-API-Key": DEV_KEY}
OBJECTS = "/api/v1/objects"
EVENTS = "/api/v1/events"
LOGIN = "/api/v1/auth/login"
SEED_PASSWORD = "Admin@123!"

# 无 readonly scope 的临时 API Key（403 用例；每测试自行插入/清场）
NO_SCOPE_KEY = "t11-ebms-no-scope-key"
NO_SCOPE_PRINCIPAL = "t11-ebms-no-scope"

# 跨租户用例的 B 租户（migrator 直造；readonly Key）
TENANT_B_SLUG = "tenant-ebms"
TENANT_B_KEY = "t11-ebms-tenant-b-key"
TENANT_B_PRINCIPAL = "t11-ebms-tenant-b"

# 十场景结果事件（occurred_at DESC 序；场景 10 偏移为 -18 分钟、其余为 -N 小时）
EXPECTED_LEVELS = ["P2", "P0", "P1", "P1", "P1", "P2", "P3", "P3", "P2", "P2"]
EXPECTED_ORDER_NOS = [
    "PLM",  # 场景 10（adapter.sync.failed，-18min，最近）
    "SO-2026-00129",  # 场景 7（-3h）
    "SO-2026-00123",  # 场景 2
    "SO-2026-00126",  # 场景 5
    "SO-2026-00131",  # 场景 9
    "SO-2026-00124",  # 场景 3
    "SO-2026-00122",  # 场景 1（P3）
    "SO-2026-00128",  # 场景 6（P3）
    "PRJ-D",  # 场景 4
    "SO-2026-00130",  # 场景 8
]


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS），ebms 路由随
    create_app 装配。"""
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
    """default 租户演示数据集（T7 seed 等价路径）；清场见 _clean_ebms_rows。"""
    stats = await demo_service.seed(app_role_engine, default_tenant_id)
    assert stats.failed == 0
    return stats


@pytest.fixture(autouse=True)
async def _clean_ebms_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    """每测试后清场：default 业务行（含 seed 全量）+ 本模块审计行/临时 Key/
    tenant-ebms（migrator 绕 RLS；audit_logs 仅追加约束只作用于 edp_app）。"""
    yield
    await demo_service.purge_tenant_business_data(db_session, default_tenant_id)
    manager1_id = (
        await db_session.execute(
            text("SELECT user_id FROM platform.users WHERE username = 'manager1'")
        )
    ).scalar_one()
    await db_session.execute(
        text(
            "DELETE FROM platform.audit_logs WHERE tenant_id = :t"
            " AND (actor_id IN ('adapter:erp', 'agent-hub', :manager1)"
            "      OR (action = 'GUARD_DENIED' AND resource_type = 'ebms'))"
        ),
        {"t": default_tenant_id, "manager1": str(manager1_id)},
    )
    b_ids = "SELECT tenant_id FROM platform.tenants WHERE slug = 'tenant-ebms'"
    await db_session.execute(
        text("DELETE FROM platform.api_keys WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM platform.api_keys WHERE principal_id = :p"),
        {"p": NO_SCOPE_PRINCIPAL},
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
            " (SELECT tenant_id FROM platform.tenants WHERE slug = 'tenant-ebms')"
        )
    )
    await db_session.execute(
        text("DELETE FROM platform.tenants WHERE slug = 'tenant-ebms'")
    )
    await db_session.commit()


async def _insert_api_key(
    db_session: AsyncSession,
    tenant_id: UUID,
    *,
    key: str,
    principal_id: str,
    scopes: list[str],
) -> None:
    """直插临时 API Key（照 test_tools 模式；hash_key 与生产同实现）。"""
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
            "key_hash": hash_key(key),
            "t": tenant_id,
            "principal": principal_id,
            "scopes": scopes,
        },
    )
    await db_session.commit()


async def _login(client: httpx.AsyncClient, username: str) -> dict[str, str]:
    resp = await client.post(
        LOGIN, json={"username": username, "password": SEED_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed_case_id(db_session: AsyncSession, tenant_id: UUID) -> UUID:
    return (
        await db_session.execute(
            text("SELECT case_id FROM decision.cases WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
    ).scalar_one()


# ---- 1. seed 后默认 OPEN 列表：十场景结果事件 + 场景 2 case_id ----


async def test_seed_exceptions_default_open(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    resp = await client.get(BASE, headers=DEV_HEADERS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # B.9 形状：items + next_cursor；Page.total 仅 events 填充（本端点剔除）
    assert body.get("next_cursor") is None
    assert "total" not in body

    items = body["items"]
    assert [item["risk_level"] for item in items] == EXPECTED_LEVELS
    assert [item["order_no"] for item in items] == EXPECTED_ORDER_NOS
    assert [item["occurred_at"] for item in items] == sorted(
        (item["occurred_at"] for item in items), reverse=True
    )
    # 偏差：P3（场景 1/6）按 spec「risk_level IS NOT NULL」在列（MSW 8 条不含）
    assert "P3" in {item["risk_level"] for item in items}

    for item in items:
        UUID(item["event_id"])
        UUID(item["object_id"])
        assert item["result_type"]
        assert item["summary"]
        assert item["occurred_at"]

    # 场景 2（SO-2026-00123）关联 seed 案例；其余 OPEN 行 case_id=null
    case_id = await _seed_case_id(db_session, default_tenant_id)
    by_order = {item["order_no"]: item for item in items}
    assert by_order["SO-2026-00123"]["case_id"] == str(case_id)
    assert by_order["SO-2026-00123"]["summary"] == "物料X缺口1000，预计延误5天"
    assert sum(1 for item in items if item["case_id"] is not None) == 1


# ---- 2. severity 过滤 ----


async def test_severity_filter(
    client: httpx.AsyncClient, demo: demo_service.SeedStats
) -> None:
    expected = {
        "P0": {"SO-2026-00129"},
        "P1": {"SO-2026-00123", "SO-2026-00126", "SO-2026-00131"},
        "P2": {"PLM", "SO-2026-00124", "PRJ-D", "SO-2026-00130"},
        "P3": {"SO-2026-00122", "SO-2026-00128"},
    }
    for severity, order_nos in expected.items():
        resp = await client.get(
            BASE, params={"severity": severity}, headers=DEV_HEADERS
        )
        assert resp.status_code == 200, resp.text
        items = resp.json()["items"]
        assert {item["risk_level"] for item in items} == {severity}
        assert {item["order_no"] for item in items} == order_nos


# ---- 3. order_no/summary 回退链 ----


async def test_order_no_summary_fallback_chain(client: httpx.AsyncClient) -> None:
    """order_no：data.order_no → business_objects.source_id；
    summary：data.summary → data.reason → event_type（spec §6.1）。"""
    resp = await client.post(
        OBJECTS,
        json={
            "object_type": "ORDER",
            "owner_domain": "sales",
            "source_system": "erp",
            "source_id": "SO-EBMS-0001",
            "attributes": {},
        },
        headers=DEV_HEADERS,
    )
    assert resp.status_code == 201, resp.text
    object_id = resp.json()["object_id"]

    resp = await client.post(
        EVENTS + "/batch",
        json={
            "events": [
                {
                    "event_type": "capability.result.order_risk",
                    "object_id": object_id,
                    "source_system": "agent-hub",
                    "occurred_at": "2026-09-14T08:00:01Z",
                    "result_type": "ORDER_RISK",
                    "risk_level": "P1",
                    "data": {"order_no": "SO-OVERRIDE-1", "summary": "显式摘要"},
                },
                {
                    "event_type": "capability.result.order_risk",
                    "object_id": object_id,
                    "source_system": "agent-hub",
                    "occurred_at": "2026-09-14T08:00:02Z",
                    "result_type": "ORDER_RISK",
                    "risk_level": "P2",
                    "data": {"reason": "回退到原因"},
                },
                {
                    "event_type": "capability.result.ebms_fallback",
                    "object_id": object_id,
                    "source_system": "agent-hub",
                    "occurred_at": "2026-09-14T08:00:03Z",
                    "result_type": "ORDER_RISK",
                    "risk_level": "P3",
                    "data": {},
                },
            ]
        },
        headers={**DEV_HEADERS, "Idempotency-Key": f"idem-ebms-{uuid4()}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["accepted"] == 3

    resp = await client.get(BASE, headers=DEV_HEADERS)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 3
    by_summary = {item["summary"]: item for item in items}
    # data 显式值优先（order_no 不回退；summary 取 data.summary）
    assert by_summary["显式摘要"]["order_no"] == "SO-OVERRIDE-1"
    # order_no 回退对象 source_id；summary 回退 data.reason
    assert by_summary["回退到原因"]["order_no"] == "SO-EBMS-0001"
    # summary 回退链末端 = event_type
    fallback = by_summary["capability.result.ebms_fallback"]
    assert fallback["order_no"] == "SO-EBMS-0001"
    assert fallback["risk_level"] == "P3"


# ---- 4. 游标分页 ----


async def test_cursor_pagination(
    client: httpx.AsyncClient, demo: demo_service.SeedStats
) -> None:
    seen: list[str] = []
    occurred: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, object] = {"limit": 3}
        if cursor is not None:
            params["cursor"] = cursor
        resp = await client.get(BASE, params=params, headers=DEV_HEADERS)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["items"]) <= 3
        seen.extend(item["event_id"] for item in body["items"])
        occurred.extend(item["occurred_at"] for item in body["items"])
        cursor = body["next_cursor"]
        pages += 1
        assert pages <= 10  # 防御死循环
        if cursor is None:
            break

    assert pages == 4  # 3 + 3 + 3 + 1
    assert len(seen) == 10
    assert len(set(seen)) == 10  # 无重
    assert occurred == sorted(occurred, reverse=True)  # 跨页全局降序


# ---- 5. status 切换：HUMAN 决策后 RESOLVED/OPEN 语义（真实 join） ----


async def test_status_switch_after_human_decision(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    case_id = await _seed_case_id(db_session, default_tenant_id)
    headers = await _login(client, "manager1")

    resp = await client.get(BASE, params={"status": "OPEN"}, headers=headers)
    assert resp.status_code == 200, resp.text
    open_items = resp.json()["items"]
    assert len(open_items) == 10
    # 案例存在但未决策 → 场景 2 仍 OPEN 且 case_id 已派生；其余行 case_id=null
    with_case = [item for item in open_items if item["case_id"] is not None]
    assert [item["order_no"] for item in with_case] == ["SO-2026-00123"]
    assert with_case[0]["case_id"] == str(case_id)

    resp = await client.get(BASE, params={"status": "RESOLVED"}, headers=DEV_HEADERS)
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []

    decided = await client.post(
        f"/api/v1/decisions/cases/{case_id}/records",
        headers=headers,
        json={"chosen_option": "EXPEDITE"},
    )
    assert decided.status_code == 201, decided.text

    resp = await client.get(BASE, params={"status": "RESOLVED"}, headers=headers)
    assert resp.status_code == 200, resp.text
    resolved = resp.json()["items"]
    assert [item["order_no"] for item in resolved] == ["SO-2026-00123"]
    assert resolved[0]["case_id"] == str(case_id)

    resp = await client.get(BASE, params={"status": "OPEN"}, headers=DEV_HEADERS)
    assert resp.status_code == 200, resp.text
    open_items = resp.json()["items"]
    assert len(open_items) == 9
    assert "SO-2026-00123" not in {item["order_no"] for item in open_items}
    assert all(item["case_id"] is None for item in open_items)


# ---- 6. HUMAN JWT 200（ebms:read 轨道） ----


async def test_human_jwt_read_200(
    client: httpx.AsyncClient, demo: demo_service.SeedStats
) -> None:
    for username in ("manager1", "analyst1"):
        headers = await _login(client, username)
        resp = await client.get(BASE, headers=headers)
        assert resp.status_code == 200, resp.text
        assert len(resp.json()["items"]) == 10


# ---- 7. 跨租户：tenant-ebms 读 default 数据 = 空 ----


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
            " VALUES (:t, :slug, '租户EBMSB', 'ACTIVE')"
        ),
        {"t": tenant_b, "slug": TENANT_B_SLUG},
    )
    await db_session.commit()
    await _insert_api_key(
        db_session,
        tenant_b,
        key=TENANT_B_KEY,
        principal_id=TENANT_B_PRINCIPAL,
        scopes=["readonly"],
    )

    resp = await client.get(BASE, headers={"X-API-Key": TENANT_B_KEY})
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []


# ---- 8. SERVICE 无 readonly scope → 403 FORBIDDEN ----


async def test_service_without_readonly_scope_forbidden(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await _insert_api_key(
        db_session,
        default_tenant_id,
        key=NO_SCOPE_KEY,
        principal_id=NO_SCOPE_PRINCIPAL,
        scopes=["write:event"],
    )

    resp = await client.get(BASE, headers={"X-API-Key": NO_SCOPE_KEY})
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"
