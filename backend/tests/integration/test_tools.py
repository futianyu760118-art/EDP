"""T8 tools API 集成测试（EDP-015）：六接口 + Read-Only 三层。

覆盖：
1. 种子数据（T7 seed 等价路径：demo_service.seed）就绪后，种子 Key（含
   readonly scope）GET 六接口 200，逐字段对齐 B.8 示例，evidence_hint 指向
   该对象最新 {TYPE}_SNAPSHOT 事件；
2. 非 GET（POST/PUT/DELETE/PATCH）→ 405 且 body 为统一 envelope
   （METHOD_NOT_ALLOWED + 通用文案「方法不允许」，Allow: GET 头保留；无凭据
   也 405——路由先于鉴权）；非 tools 路由（/healthz）同样收敛（全路由行为）；
2b. 认证双轨：无凭据 401；HUMAN（manager1 JWT，MANAGER 角色）tools:read
   轨道 GET 200（修复前 rbac 常量漏同步 tools:read → 全 403）；
3. 无 readonly scope 临时 Key → 403 FORBIDDEN 且 audit_logs 出现
   GUARD_DENIED 行（resource_type=tools，detail 含 path/reason/scopes；
   拒绝审计走独立会话提交，不随请求事务回滚丢弃）；
4. 跨租户：tenant-tools（migrator 直造 + readonly Key）读 default 数据 →
   详情 404 / 列表空，不泄露存在性；
5. 404/空数组分层：订单/客户/BOM/物料/供应商对象不存在 → 404；对象存在但
   无库存行/交期行/快照事件 → 200 空数组 + evidence_hint.event_id=null；
6. SET LOCAL ROLE 直证：tools_service.read_only_session 后 current_user =
   edp_agent_ro 且领域表 INSERT 被拒（T1 角色权限的服务侧落地）。

会话形态：应用引擎 = conftest.app_role_engine（edp_app，FORCE RLS）；断言
以 migrator db_session 直查（绕 RLS）。清场：purge_tenant_business_data
（逆依赖序，与 seed 复位同一实现）+ 本模块审计行/临时 Key/tenant-tools。
"""

from uuid import UUID, uuid4

import httpx
import pytest
from asyncpg.exceptions import InsufficientPrivilegeError
from edp_api.core import db as core_db
from edp_api.core.db import bind_tenant
from edp_api.core.security.apikey import hash_key
from edp_api.main import create_app
from edp_api.modules.demo import service as demo_service
from edp_api.modules.tools import service as tools_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

BASE = "/api/v1/tools"
DEV_KEY = "edp-dev-agent-hub-key"
DEV_HEADERS = {"X-API-Key": DEV_KEY}
LOGIN = "/api/v1/auth/login"
SEED_PASSWORD = "Admin@123!"

# 无 readonly scope 的临时 API Key（403 用例；每测试自行插入/清场）
NO_READONLY_KEY = "t8-tools-no-readonly-key"
NO_READONLY_PRINCIPAL = "t8-tools-no-readonly"

# 跨租户用例的 B 租户（migrator 直造；readonly Key）
TENANT_B_SLUG = "tenant-tools"
TENANT_B_KEY = "t8-tools-tenant-b-key"
TENANT_B_PRINCIPAL = "t8-tools-tenant-b"

PATHS = (
    "/orders",
    "/orders/SO-2026-00123",
    "/inventory",
    "/purchase-orders",
    "/bom",
    "/supplier-lead-times",
    "/customers/C-008",
)


def _root_cause(exc: BaseException) -> BaseException:
    """沿 __cause__ 链下钻取 DBAPI 原生异常。"""
    while exc.__cause__ is not None:
        exc = exc.__cause__
    return exc


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS），tools 路由随
    create_app 装配（错误处理器含 StarletteHTTPException → 405 envelope）。"""
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
    app_role_engine: AsyncEngine, default_tenant_id: UUID, db_session: AsyncSession
) -> demo_service.SeedStats:
    """default 租户演示数据集（T7 seed 等价路径）；清场见 _clean_tools_rows。

    V1.2 T21：tools 缺省 official_only=true（仅 CURATED/ARCHIVED）——种子后
    统一置 CURATED（目标态准入后语义；门禁行为见 test_v12_fact_layer）。
    """
    stats = await demo_service.seed(app_role_engine, default_tenant_id)
    assert stats.failed == 0
    await db_session.execute(
        text(
            "UPDATE master.business_objects SET layer_status = 'CURATED'"
            " WHERE tenant_id = :t"
        ),
        {"t": default_tenant_id},
    )
    await db_session.commit()
    return stats


@pytest.fixture(autouse=True)
async def _clean_tools_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    """每测试后清场：default 业务行（含 seed 全量）+ 本模块审计行/临时 Key/
    tenant-tools（migrator 绕 RLS；audit_logs 仅追加约束只作用于 edp_app）。"""
    yield
    await demo_service.purge_tenant_business_data(db_session, default_tenant_id)
    await db_session.execute(
        text(
            "DELETE FROM platform.audit_logs WHERE tenant_id = :t"
            " AND actor_id = 'adapter:erp'"
        ),
        {"t": default_tenant_id},
    )
    await db_session.execute(
        text(
            "DELETE FROM platform.audit_logs"
            " WHERE action = 'GUARD_DENIED' AND resource_type = 'tools'"
        )
    )
    b_ids = "SELECT tenant_id FROM platform.tenants WHERE slug = 'tenant-tools'"
    await db_session.execute(
        text("DELETE FROM platform.api_keys WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM platform.api_keys WHERE principal_id = :p"),
        {"p": NO_READONLY_PRINCIPAL},
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
            " (SELECT tenant_id FROM platform.tenants WHERE slug = 'tenant-tools')"
        )
    )
    await db_session.execute(
        text("DELETE FROM platform.tenants WHERE slug = 'tenant-tools'")
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
    """直插临时 API Key（照 test_audit 模式；hash_key 与生产同实现）。"""
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


async def _latest_snapshot_event_id(
    db_session: AsyncSession, object_id: str, event_type: str
) -> UUID | None:
    return (
        await db_session.execute(
            text(
                "SELECT event_id FROM event.events"
                " WHERE object_id = :o AND event_type = :et"
                " ORDER BY occurred_at DESC, event_id DESC LIMIT 1"
            ),
            {"o": object_id, "et": event_type},
        )
    ).scalar_one_or_none()


# ---- 1. 六接口 200：B.8 字段 + evidence_hint（种子数据） ----


async def test_six_endpoints_with_seeded_dataset(
    client: httpx.AsyncClient, db_session: AsyncSession, demo: demo_service.SeedStats
) -> None:
    # 订单详情（B.8 示例 SO-2026-00123：C-008/VIP/120000/两行明细）
    resp = await client.get(f"{BASE}/orders/SO-2026-00123", headers=DEV_HEADERS)
    assert resp.status_code == 200, resp.text
    order = resp.json()
    assert order["order_no"] == "SO-2026-00123"
    UUID(order["object_id"])
    assert order["customer"] == {"code": "C-008", "name": "某客户", "level": "VIP"}
    assert order["amount"] == 120000.0
    assert order["currency"] == "CNY"
    assert order["status"] == "已确认"
    assert order["delivery_date"].startswith("2026-10-15")
    lines = {line["product_code"] or line["material_code"]: line for line in order["lines"]}
    assert set(lines) == {"P-F", "X-100"}
    assert lines["P-F"]["quantity"] == 500.0
    assert lines["P-F"]["unit_price"] == 240.0
    assert lines["X-100"]["quantity"] == 1000.0
    assert order["evidence_hint"]["object_id"] == order["object_id"]
    hint_event = await _latest_snapshot_event_id(
        db_session, order["object_id"], "ORDER_SNAPSHOT"
    )
    assert order["evidence_hint"]["event_id"] == str(hint_event)

    # 订单摘要列表（同结构，不含 lines；customer/status/limit 过滤）
    resp = await client.get(
        f"{BASE}/orders", params={"customer": "C-008"}, headers=DEV_HEADERS
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [item["order_no"] for item in body["items"]] == [
        "SO-2026-00123",
        "SO-2026-00128",
    ]
    assert body["next_cursor"] is None
    for item in body["items"]:
        assert "lines" not in item
        assert item["evidence_hint"]["object_id"] == item["object_id"]
        assert item["evidence_hint"]["event_id"]

    listed = await client.get(
        f"{BASE}/orders",
        params={"status": "已确认", "limit": 3},
        headers=DEV_HEADERS,
    )
    assert listed.status_code == 200, listed.text
    assert [item["order_no"] for item in listed.json()["items"]] == [
        "SO-2026-00122",
        "SO-2026-00123",
        "SO-2026-00124",
    ]

    # 库存（X-100 两仓；WH-01 缺口来源）
    resp = await client.get(
        f"{BASE}/inventory", params={"material_code": "X-100"}, headers=DEV_HEADERS
    )
    assert resp.status_code == 200, resp.text
    inventory = resp.json()
    assert inventory["material_code"] == "X-100"
    UUID(inventory["material_id"])
    assert {w["warehouse"] for w in inventory["warehouses"]} == {"WH-01", "WH-02"}
    wh01 = next(w for w in inventory["warehouses"] if w["warehouse"] == "WH-01")
    assert (wh01["available"], wh01["reserved"]) == (0.0, 0.0)
    assert inventory["total_available"] == 3200.0
    assert inventory["snapshot_at"]
    assert inventory["evidence_hint"]["event_id"]
    assert (
        await _latest_snapshot_event_id(
            db_session, inventory["evidence_hint"]["object_id"], "MATERIAL_SNAPSHOT"
        )
        is not None
    )

    # 采购单（在途 X-100：S-021/2000 件）
    resp = await client.get(
        f"{BASE}/purchase-orders",
        params={"material_code": "X-100"},
        headers=DEV_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    purchase = resp.json()
    assert purchase["next_cursor"] is None
    assert len(purchase["items"]) == 1
    po = purchase["items"][0]
    assert po["po_no"] == "PO-2026-00771"
    assert po["supplier_code"] == "S-021"
    assert po["quantity"] == 2000.0
    assert po["status"] == "在途"
    assert po["expected_date"].startswith("2026-10-20")
    assert po["evidence_hint"]["object_id"] == po["object_id"]
    assert po["evidence_hint"]["event_id"]

    # BOM（P-F V3：X-100×2.5 / Y-200×1.0）
    resp = await client.get(
        f"{BASE}/bom", params={"product_code": "P-F"}, headers=DEV_HEADERS
    )
    assert resp.status_code == 200, resp.text
    bom = resp.json()
    assert bom["product_code"] == "P-F"
    assert bom["bom_version"] == "V3"
    assert {item["material_code"]: item["quantity_per"] for item in bom["items"]} == {
        "X-100": 2.5,
        "Y-200": 1.0,
    }
    assert bom["evidence_hint"]["event_id"]

    # 供应商交期（S-021：X-100=10 / Y-200=7）
    resp = await client.get(
        f"{BASE}/supplier-lead-times",
        params={"supplier_code": "S-021"},
        headers=DEV_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    lead_times = resp.json()
    assert lead_times["supplier_code"] == "S-021"
    assert {
        item["material_code"]: item["lead_time_days"]
        for item in lead_times["lead_times"]
    } == {"X-100": 10, "Y-200": 7}
    assert lead_times["updated_at"]
    assert lead_times["evidence_hint"]["event_id"]

    # 客户主数据
    resp = await client.get(f"{BASE}/customers/C-008", headers=DEV_HEADERS)
    assert resp.status_code == 200, resp.text
    customer = resp.json()
    assert customer["customer_code"] == "C-008"
    assert customer["name"] == "某客户"
    assert customer["level"] == "VIP"
    assert customer["attributes"] == {}
    assert customer["evidence_hint"]["event_id"]


# ---- 2. 非 GET → 405 统一 envelope（路由先于鉴权，无需凭据） ----


@pytest.mark.parametrize("path", PATHS)
async def test_non_get_methods_405_envelope(
    client: httpx.AsyncClient, path: str
) -> None:
    resp = await client.post(f"{BASE}{path}", json={})
    assert resp.status_code == 405, resp.text
    assert resp.headers.get("allow") == "GET"
    body = resp.json()["error"]
    assert body["code"] == "METHOD_NOT_ALLOWED"
    assert body["message"] == "方法不允许"
    UUID(body["request_id"])


async def test_put_delete_patch_405(client: httpx.AsyncClient) -> None:
    target = f"{BASE}/orders/SO-2026-00123"
    for method in ("PUT", "DELETE", "PATCH"):
        resp = await client.request(method, target, json={})
        assert resp.status_code == 405, resp.text
        assert resp.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


async def test_non_tools_route_405_generic_message(client: httpx.AsyncClient) -> None:
    """405 统一 envelope 为全路由行为（非 tools 专属）：/healthz 仅 GET。"""
    resp = await client.post("/healthz")
    assert resp.status_code == 405, resp.text
    assert resp.headers.get("allow") == "GET"
    body = resp.json()["error"]
    assert body["code"] == "METHOD_NOT_ALLOWED"
    assert body["message"] == "方法不允许"
    UUID(body["request_id"])


# ---- 2b. 认证语义：无凭据 401 / HUMAN JWT（tools:read 轨道）200 ----


async def test_missing_credentials_401(client: httpx.AsyncClient) -> None:
    resp = await client.get(f"{BASE}/orders")
    assert resp.status_code == 401, resp.text
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_human_jwt_manager_tools_read_200(
    client: httpx.AsyncClient, demo: demo_service.SeedStats
) -> None:
    """HUMAN 轨道：manager1（MANAGER 角色）JWT → tools:read → 200。"""
    login = await client.post(
        LOGIN, json={"username": "manager1", "password": SEED_PASSWORD}
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.get(f"{BASE}/orders/SO-2026-00123", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["order_no"] == "SO-2026-00123"


# ---- 3. 无 readonly scope Key → 403 + GUARD_DENIED 审计 ----


async def test_no_readonly_scope_forbidden_and_audited(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await _insert_api_key(
        db_session,
        default_tenant_id,
        key=NO_READONLY_KEY,
        principal_id=NO_READONLY_PRINCIPAL,
        scopes=["write:event"],
    )

    resp = await client.get(
        f"{BASE}/orders/SO-2026-00123", headers={"X-API-Key": NO_READONLY_KEY}
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    rows = (
        (
            await db_session.execute(
                text(
                    "SELECT actor_type, actor_id, resource_type, resource_id, detail"
                    " FROM platform.audit_logs"
                    " WHERE action = 'GUARD_DENIED' AND resource_type = 'tools'"
                    " AND actor_id = :a"
                ),
                {"a": NO_READONLY_PRINCIPAL},
            )
        )
        .mappings()
        .all()
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["actor_type"] == "SERVICE"
    assert row["resource_id"] is None
    assert row["detail"]["path"] == f"{BASE}/orders/SO-2026-00123"
    assert row["detail"]["reason"] == "缺少 scope：readonly"
    assert row["detail"]["scopes"] == ["write:event"]

    # 对照：种子 Key（readonly）同路径 → 404（认证通过，仅数据不存在）——
    # 证明 403 由 scope 缺失而非路由/租户
    ok = await client.get(f"{BASE}/orders/SO-2026-00123", headers=DEV_HEADERS)
    assert ok.status_code == 404, ok.text
    assert ok.json()["error"]["code"] == "NOT_FOUND"


# ---- 4. 跨租户：tenant-tools 读 default 数据 = 不存在 ----


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
            " VALUES (:t, :slug, '租户ToolsB', 'ACTIVE')"
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
    headers = {"X-API-Key": TENANT_B_KEY}

    # 详情：default 的订单/客户不可见（RLS + 显式租户条件）
    for path in ("/orders/SO-2026-00123", "/customers/C-008"):
        resp = await client.get(f"{BASE}{path}", headers=headers)
        assert resp.status_code == 404, resp.text
        assert resp.json()["error"]["code"] == "NOT_FOUND"
    # 物料/供应商对象在 B 租户不存在
    resp = await client.get(
        f"{BASE}/inventory", params={"material_code": "X-100"}, headers=headers
    )
    assert resp.status_code == 404
    resp = await client.get(
        f"{BASE}/supplier-lead-times",
        params={"supplier_code": "S-021"},
        headers=headers,
    )
    assert resp.status_code == 404
    # 列表：空（不泄露存在性）
    resp = await client.get(f"{BASE}/orders", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []
    resp = await client.get(f"{BASE}/purchase-orders", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []


# ---- 5. 404 / 空数组分层 + event_id=null ----


async def test_not_found_and_empty_layers(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    # 对象不存在 → 404 NOT_FOUND
    for path, params in (
        ("/orders/SO-2026-99999", None),
        ("/customers/C-999", None),
        ("/bom", {"product_code": "P-999"}),
        ("/inventory", {"material_code": "M-999"}),
        ("/supplier-lead-times", {"supplier_code": "S-999"}),
    ):
        resp = await client.get(f"{BASE}{path}", params=params, headers=DEV_HEADERS)
        assert resp.status_code == 404, resp.text
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    # 对象存在但无库存行/无交期行/无快照事件 → 200 空数组 + event_id=null
    material_id = uuid4()
    supplier_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO master.business_objects"
            " (object_id, tenant_id, object_type, owner_domain, source_system, source_id)"
            " VALUES (:o, :t, 'MATERIAL', 'master', 'erp', 'M-EMPTY'),"
            "        (:s, :t, 'SUPPLIER', 'procurement', 'erp', 'S-EMPTY')"
        ),
        {"o": material_id, "s": supplier_id, "t": default_tenant_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO master.materials (material_id, tenant_id, code, name)"
            " VALUES (:o, :t, 'M-EMPTY', '空库存物料')"
        ),
        {"o": material_id, "t": default_tenant_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO master.suppliers (supplier_id, tenant_id, code, name)"
            " VALUES (:s, :t, 'S-EMPTY', '空交期供应商')"
        ),
        {"s": supplier_id, "t": default_tenant_id},
    )
    await db_session.commit()

    resp = await client.get(
        f"{BASE}/inventory",
        params={"material_code": "M-EMPTY", "official_only": "false"},
        headers=DEV_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    empty_inventory = resp.json()
    assert empty_inventory["warehouses"] == []
    assert empty_inventory["total_available"] == 0.0
    assert empty_inventory["snapshot_at"] is None
    assert empty_inventory["evidence_hint"] == {
        "object_id": str(material_id),
        "event_id": None,
    }

    resp = await client.get(
        f"{BASE}/supplier-lead-times",
        params={"supplier_code": "S-EMPTY", "official_only": "false"},
        headers=DEV_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    empty_lead_times = resp.json()
    assert empty_lead_times["lead_times"] == []
    assert empty_lead_times["updated_at"] is None
    assert empty_lead_times["evidence_hint"]["event_id"] is None

    # 列表未命中 → 200 空 items
    resp = await client.get(
        f"{BASE}/purchase-orders",
        params={"material_code": "M-999"},
        headers=DEV_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []


# ---- 6. 只读角色直证：SET LOCAL ROLE 生效（服务侧落地） ----


async def test_read_only_session_switches_role(
    app_session: AsyncSession, default_tenant_id: UUID
) -> None:
    await bind_tenant(app_session, default_tenant_id)
    await tools_service.read_only_session(app_session)

    current = (await app_session.execute(text("SELECT current_user"))).scalar_one()
    assert current == "edp_agent_ro"

    with pytest.raises(Exception) as ei:
        await app_session.execute(
            text(
                "INSERT INTO sales.orders"
                " (order_id, tenant_id, order_no, status, snapshot_at)"
                " VALUES (gen_random_uuid(), :t, 'SO-RO-PROBE', 'NEW', now())"
            ),
            {"t": default_tenant_id},
        )
    assert isinstance(_root_cause(ei.value), InsufficientPrivilegeError)
