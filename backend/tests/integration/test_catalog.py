"""T2 注册中心集成测试（EDP-011，B.7）：systems/capabilities/skills。

覆盖：
1. 能力主流程（B.7 示例逐字段）：注册 ``Delivery.OrderRisk`` 201 →
   列表（domain/status 过滤）→ 详情（含 input/output_schema）→ PUT 局部
   更新（endpoint 生效、未传字段不动）→ RETIRED 下线 → 重名 409 CONFLICT；
2. systems：创建 201（B.7 示例 erp）+ 落库字段/同名 409/status 过滤列表；
3. skills：创建 201（B.7 示例）→ capability_id/status 过滤 → capability
   不存在 400 VALIDATION_ERROR；
4. JWT 双轨：manager1（MANAGER 含 registry:write）写 201 / analyst1 写 403
   FORBIDDEN、读 200；
5. API Key 轨道：仅 readonly scope 的 Key 写 403 / 读 200（dev Key
   write:registry 写 201 由主流程覆盖）；
6. 跨租户：tenant-catalog readonly Key 读 default 能力详情 404 / 列表空
   （systems 与 capabilities）。

会话形态：应用引擎 = conftest.app_role_engine（edp_app，FORCE RLS）；断言以
migrator db_session 直查（绕 RLS）。清场：本模块三表行 + 切面审计行 +
临时 Key/tenant-catalog（migrator 绕 RLS）。
"""

from uuid import UUID, uuid4

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.core.security.apikey import hash_key
from edp_api.main import create_app
from edp_api.modules.audit.aspect import install_audit_aspect
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

BASE = "/api/v1"
DEV_KEY = "edp-dev-agent-hub-key"
DEV_HEADERS = {"X-API-Key": DEV_KEY}
LOGIN = "/api/v1/auth/login"
SEED_PASSWORD = "Admin@123!"

# 仅 readonly scope 的临时 API Key（403 用例；每测试自行插入/清场）
NO_SCOPE_KEY = "t2-catalog-readonly-key"
NO_SCOPE_PRINCIPAL = "t2-catalog-readonly"

# 跨租户用例的 B 租户（migrator 直造；readonly Key）
TENANT_B_SLUG = "tenant-catalog"
TENANT_B_KEY = "t2-catalog-tenant-b-key"
TENANT_B_PRINCIPAL = "t2-catalog-tenant-b"

# B.7 请求示例（逐字段）
SYSTEM_PAYLOAD = {
    "name": "erp",
    "type": "SOURCE",
    "endpoint": "https://erp.internal/api",
    "auth_config": {"kind": "apikey", "secret_ref": "ENV:ERP_API_KEY"},
}
CAPABILITY_PAYLOAD = {
    "name": "Delivery.OrderRisk",
    "domain": "delivery",
    "input_schema": {
        "type": "object",
        "properties": {"order_id": {"type": "string"}},
    },
    "output_schema": {
        "type": "object",
        "properties": {
            "risk_level": {"type": "string"},
            "evidence_refs": {"type": "array"},
        },
    },
    "risk_level": "L2",
    "permission": "READ_ONLY",
    "endpoint": "agent-hub://capabilities/delivery-order-risk",
    "owner": "wuyangpeng",
}
SKILL_PAYLOAD = {
    "capability_id": None,  # 测试内填
    "prompt": "评估订单交付风险并给出建议",
    "model_version": "glm-4.7",
    "status": "DRAFT",
}


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS），catalog 路由
    随 create_app 装配。"""
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


@pytest.fixture(autouse=True)
def _install_aspect() -> None:
    """ORM 写（systems/capabilities/skills）依赖切面落审计——与 create_app
    同一装配。"""
    install_audit_aspect()


@pytest.fixture(autouse=True)
async def _clean_catalog_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    """每测试后清场：本模块三表行（skills → capabilities → systems，FK 序）
    + 切面审计行（resource_type=三表名）+ 临时 Key/tenant-catalog
    （migrator 绕 RLS）。"""
    yield
    await db_session.execute(
        text("DELETE FROM platform.skills WHERE tenant_id = :t"),
        {"t": default_tenant_id},
    )
    await db_session.execute(
        text("DELETE FROM platform.capabilities WHERE tenant_id = :t"),
        {"t": default_tenant_id},
    )
    await db_session.execute(
        text("DELETE FROM platform.systems WHERE tenant_id = :t"),
        {"t": default_tenant_id},
    )
    await db_session.execute(
        text(
            "DELETE FROM platform.audit_logs WHERE tenant_id = :t"
            " AND resource_type IN ('systems', 'capabilities', 'skills')"
        ),
        {"t": default_tenant_id},
    )
    await db_session.execute(
        text("DELETE FROM platform.api_keys WHERE principal_id = :p"),
        {"p": NO_SCOPE_PRINCIPAL},
    )
    b_ids = "SELECT tenant_id FROM platform.tenants WHERE slug = 'tenant-catalog'"
    await db_session.execute(
        text("DELETE FROM platform.api_keys WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM platform.skills WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM platform.capabilities WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM platform.systems WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text(
            "DELETE FROM platform.tenant_usage_daily WHERE tenant_id IN"
            " (SELECT tenant_id FROM platform.tenants WHERE slug = 'tenant-catalog')"
        )
    )
    await db_session.execute(
        text("DELETE FROM platform.tenants WHERE slug = 'tenant-catalog'")
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
    """直插临时 API Key（照 test_decisions 模式；hash_key 与生产同实现）。"""
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


# ---- 1. 能力主流程：注册 → 列表/详情 → PUT → 重名 409 ----


async def test_capability_register_list_detail_put_and_conflict(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    resp = await client.post(
        f"{BASE}/capabilities", headers=DEV_HEADERS, json=CAPABILITY_PAYLOAD
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    capability_id = UUID(body["capability_id"])
    assert body["name"] == "Delivery.OrderRisk"
    assert body["status"] == "ACTIVE"
    assert body["created_at"]

    row = (
        await db_session.execute(
            text(
                "SELECT domain, input_schema, output_schema, risk_level,"
                " permission, endpoint, owner, status, created_by"
                " FROM platform.capabilities WHERE capability_id = :c"
            ),
            {"c": str(capability_id)},
        )
    ).one()
    assert row.domain == "delivery"
    assert row.input_schema == CAPABILITY_PAYLOAD["input_schema"]
    assert row.output_schema == CAPABILITY_PAYLOAD["output_schema"]
    assert row.risk_level == "L2"
    assert row.permission == "READ_ONLY"
    assert row.endpoint == "agent-hub://capabilities/delivery-order-risk"
    assert row.owner == "wuyangpeng"
    assert row.status == "ACTIVE"
    assert row.created_by == "agent-hub"

    # 列表：domain/status 过滤（简投影不含 schema）
    resp = await client.get(
        f"{BASE}/capabilities",
        params={"domain": "delivery", "status": "ACTIVE"},
        headers=DEV_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    page = resp.json()
    assert page.get("next_cursor") is None
    assert [item["capability_id"] for item in page["items"]] == [str(capability_id)]
    item = page["items"][0]
    assert item["name"] == "Delivery.OrderRisk"
    assert item["risk_level"] == "L2"
    assert "input_schema" not in item

    for params in ({"domain": "planning"}, {"status": "RETIRED"}):
        filtered = await client.get(
            f"{BASE}/capabilities", params=params, headers=DEV_HEADERS
        )
        assert filtered.status_code == 200, filtered.text
        assert filtered.json()["items"] == []

    # 详情：含 input/output_schema
    resp = await client.get(
        f"{BASE}/capabilities/{capability_id}", headers=DEV_HEADERS
    )
    assert resp.status_code == 200, resp.text
    detail = resp.json()
    assert detail["capability_id"] == str(capability_id)
    assert detail["input_schema"] == CAPABILITY_PAYLOAD["input_schema"]
    assert detail["output_schema"] == CAPABILITY_PAYLOAD["output_schema"]
    assert detail["endpoint"] == "agent-hub://capabilities/delivery-order-risk"
    assert detail["status"] == "ACTIVE"

    # PUT 局部更新：仅 endpoint 传入 → schema/状态不动
    resp = await client.put(
        f"{BASE}/capabilities/{capability_id}",
        headers=DEV_HEADERS,
        json={"endpoint": "agent-hub://capabilities/delivery-order-risk/v2"},
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["endpoint"] == "agent-hub://capabilities/delivery-order-risk/v2"
    assert updated["input_schema"] == CAPABILITY_PAYLOAD["input_schema"]
    assert updated["status"] == "ACTIVE"

    # PUT RETIRED 下线 → 200 完整对象
    resp = await client.put(
        f"{BASE}/capabilities/{capability_id}",
        headers=DEV_HEADERS,
        json={"status": "RETIRED"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "RETIRED"
    assert (
        await db_session.execute(
            text(
                "SELECT status, endpoint FROM platform.capabilities"
                " WHERE capability_id = :c"
            ),
            {"c": str(capability_id)},
        )
    ).one() == ("RETIRED", "agent-hub://capabilities/delivery-order-risk/v2")

    # 重名（uq_capability_name）→ 409 CONFLICT
    resp = await client.post(
        f"{BASE}/capabilities", headers=DEV_HEADERS, json=CAPABILITY_PAYLOAD
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "CONFLICT"


# ---- 2. systems：创建 201 + 同名 409 + status 过滤 ----


async def test_systems_create_conflict_and_list(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    resp = await client.post(f"{BASE}/systems", headers=DEV_HEADERS, json=SYSTEM_PAYLOAD)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    system_id = UUID(body["system_id"])
    assert body["name"] == "erp"
    assert body["status"] == "ACTIVE"
    assert body["created_at"]

    row = (
        await db_session.execute(
            text(
                "SELECT type, endpoint, auth_config, status, adapter_mode,"
                " last_watermark, created_by FROM platform.systems"
                " WHERE system_id = :s"
            ),
            {"s": str(system_id)},
        )
    ).one()
    assert row.type == "SOURCE"
    assert row.endpoint == "https://erp.internal/api"
    assert row.auth_config == SYSTEM_PAYLOAD["auth_config"]
    assert row.status == "ACTIVE"
    # 水位字段归 ingest（DDL 默认；catalog 不写）
    assert row.adapter_mode == "mock"
    assert row.last_watermark is None
    assert row.created_by == "agent-hub"

    # 同名 → 409 CONFLICT（uq_systems_name）
    resp = await client.post(f"{BASE}/systems", headers=DEV_HEADERS, json=SYSTEM_PAYLOAD)
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "CONFLICT"
    # 冲突不残留新行
    assert (
        await db_session.execute(
            text("SELECT count(*) FROM platform.systems WHERE tenant_id = :t"),
            {"t": default_tenant_id},
        )
    ).scalar_one() == 1

    # status 过滤列表
    resp = await client.get(
        f"{BASE}/systems", params={"status": "ACTIVE"}, headers=DEV_HEADERS
    )
    assert resp.status_code == 200, resp.text
    assert [item["system_id"] for item in resp.json()["items"]] == [str(system_id)]
    assert resp.json()["items"][0]["type"] == "SOURCE"

    resp = await client.get(
        f"{BASE}/systems", params={"status": "DISABLED"}, headers=DEV_HEADERS
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []


# ---- 3. skills：创建 + capability 过滤 + capability 不存在 400 ----


async def test_skills_create_filter_and_missing_capability(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    resp = await client.post(
        f"{BASE}/capabilities", headers=DEV_HEADERS, json=CAPABILITY_PAYLOAD
    )
    assert resp.status_code == 201, resp.text
    capability_id = resp.json()["capability_id"]

    payload = {**SKILL_PAYLOAD, "capability_id": capability_id}
    resp = await client.post(f"{BASE}/skills", headers=DEV_HEADERS, json=payload)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    UUID(body["skill_id"])
    assert body["capability_id"] == capability_id
    assert body["status"] == "DRAFT"
    assert body["created_at"]

    row = (
        await db_session.execute(
            text(
                "SELECT prompt, model_version, status, created_by"
                " FROM platform.skills WHERE skill_id = :s"
            ),
            {"s": body["skill_id"]},
        )
    ).one()
    assert row.prompt == payload["prompt"]
    assert row.model_version == "glm-4.7"
    assert row.status == "DRAFT"
    assert row.created_by == "agent-hub"

    # capability_id 过滤命中；其他 capability / ACTIVE 状态为空
    resp = await client.get(
        f"{BASE}/skills", params={"capability_id": capability_id}, headers=DEV_HEADERS
    )
    assert resp.status_code == 200, resp.text
    assert [item["skill_id"] for item in resp.json()["items"]] == [body["skill_id"]]

    for params in (
        {"capability_id": str(uuid4())},
        {"status": "ACTIVE"},
    ):
        filtered = await client.get(
            f"{BASE}/skills", params=params, headers=DEV_HEADERS
        )
        assert filtered.status_code == 200, filtered.text
        assert filtered.json()["items"] == []

    # capability 不存在 → 400 VALIDATION_ERROR
    resp = await client.post(
        f"{BASE}/skills",
        headers=DEV_HEADERS,
        json={**SKILL_PAYLOAD, "capability_id": str(uuid4())},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    # 失败不残留
    assert (
        await db_session.execute(
            text("SELECT count(*) FROM platform.skills WHERE tenant_id = :t"),
            {"t": default_tenant_id},
        )
    ).scalar_one() == 1


# ---- 4. JWT 双轨：manager1 写 201 / analyst1 写 403、读 200 ----


async def test_jwt_dual_track(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    manager = await _login(client, "manager1")
    analyst = await _login(client, "analyst1")

    # MANAGER 含 registry:write（JWT 轨道）
    resp = await client.post(
        f"{BASE}/capabilities", headers=manager, json=CAPABILITY_PAYLOAD
    )
    assert resp.status_code == 201, resp.text
    capability_id = resp.json()["capability_id"]
    created_by = (
        await db_session.execute(
            text(
                "SELECT created_by FROM platform.capabilities"
                " WHERE capability_id = :c"
            ),
            {"c": capability_id},
        )
    ).scalar_one()
    manager1_id = (
        await db_session.execute(
            text("SELECT user_id FROM platform.users WHERE username = 'manager1'")
        )
    ).scalar_one()
    assert created_by == str(manager1_id)

    # ANALYST 无 registry:write → 403 FORBIDDEN；registry:read 读 200
    resp = await client.post(
        f"{BASE}/capabilities",
        headers=analyst,
        json={**CAPABILITY_PAYLOAD, "name": "Delivery.OrderRisk.Analyst"},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    resp = await client.get(f"{BASE}/capabilities", headers=analyst)
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["items"]) == 1

    resp = await client.get(
        f"{BASE}/capabilities/{capability_id}", headers=analyst
    )
    assert resp.status_code == 200, resp.text

    # systems 同一双轨（ANALYST 写 403）
    resp = await client.post(f"{BASE}/systems", headers=analyst, json=SYSTEM_PAYLOAD)
    assert resp.status_code == 403, resp.text


# ---- 5. API Key 轨道：仅 readonly scope 写 403 / 读 200 ----


async def test_api_key_scope_track(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await _insert_api_key(
        db_session,
        default_tenant_id,
        key=NO_SCOPE_KEY,
        principal_id=NO_SCOPE_PRINCIPAL,
        scopes=["readonly"],
    )
    headers = {"X-API-Key": NO_SCOPE_KEY}

    resp = await client.post(
        f"{BASE}/capabilities", headers=headers, json=CAPABILITY_PAYLOAD
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    resp = await client.post(f"{BASE}/systems", headers=headers, json=SYSTEM_PAYLOAD)
    assert resp.status_code == 403, resp.text

    resp = await client.post(
        f"{BASE}/skills",
        headers=headers,
        json={**SKILL_PAYLOAD, "capability_id": str(uuid4())},
    )
    assert resp.status_code == 403, resp.text

    # readonly scope 读全通
    for path in ("/capabilities", "/systems", "/skills"):
        resp = await client.get(f"{BASE}{path}", headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["items"] == []


# ---- 6. 跨租户：详情 404 / 列表空（不泄露存在性） ----


async def test_cross_tenant_not_leaked(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    resp = await client.post(
        f"{BASE}/capabilities", headers=DEV_HEADERS, json=CAPABILITY_PAYLOAD
    )
    assert resp.status_code == 201, resp.text
    capability_id = resp.json()["capability_id"]

    tenant_b = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO platform.tenants (tenant_id, slug, name, status)"
            " VALUES (:t, :slug, '租户CatalogB', 'ACTIVE')"
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

    resp = await client.get(f"{BASE}/capabilities/{capability_id}", headers=headers)
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "NOT_FOUND"

    for path in ("/capabilities", "/systems", "/skills"):
        resp = await client.get(f"{BASE}{path}", headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["items"] == []
