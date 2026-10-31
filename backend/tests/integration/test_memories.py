"""T4 Memory 集成测试（EDP-014，B.11）：候选创建 / 过滤 / Human-Only 评审。

覆盖：
1. 主流程（B.11 示例逐字段）：POST 候选 201（status=CANDIDATE）→ 落库字段
   断言（content JSONB/source_type/source_id/created_by=agent-hub）→ 列表
   status/capability_id 过滤 → HUMAN（manager1）评审 APPROVED 200
   （reviewed_by/reviewed_at/review_comment 落库）→ 重复评审 409 CONFLICT；
2. capability_id 校验：不存在（含跨租户）→ 400 VALIDATION_ERROR 且不残留；
   capability_id 缺省（可空）→ 201；
3. Human-Only：SERVICE（dev Key write:memory）PATCH → 403
   GUARD_POLICY_DENIED 且 GUARD_DENIED 审计行存在（独立会话）；
4. JWT 双轨：manager1（memory:review）评审 200 / analyst1（无
   memory:review）评审 403 FORBIDDEN / analyst1 读 200；
5. API Key 轨道：仅 readonly scope 写 403 / 读 200（dev Key write:memory
   写 201 由主流程覆盖）；
6. 跨租户：tenant-memories readonly Key 评审 404 / 列表空（不泄露）。

会话形态：应用引擎 = conftest.app_role_engine（edp_app，FORCE RLS）；断言以
migrator db_session 直查（绕 RLS）。清场：memory 行 + 审计行 + 临时
Key/tenant-memories + capabilities（capability 过滤用例）。
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

NO_SCOPE_KEY = "t4-memories-readonly-key"
NO_SCOPE_PRINCIPAL = "t4-memories-readonly"

TENANT_B_SLUG = "tenant-memories"
TENANT_B_KEY = "t4-memories-tenant-b-key"
TENANT_B_PRINCIPAL = "t4-memories-tenant-b"

CAPABILITY_PAYLOAD = {
    "name": "Delivery.OrderRisk",
    "domain": "delivery",
    "input_schema": {"type": "object"},
    "output_schema": {"type": "object"},
    "risk_level": "L2",
    "permission": "READ_ONLY",
}


def _memory_payload(capability_id: str | None = None) -> dict:
    """B.11 请求示例（逐字段）。"""
    return {
        "capability_id": capability_id,
        "source_type": "decision",
        "source_id": str(uuid4()),
        "content": {"lesson": "VIP客户订单优先保交付，建议默认倾向加急"},
    }


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
        await core_db.dispose_engine()


@pytest.fixture
async def default_tenant_id(db_session: AsyncSession) -> UUID:
    return (
        await db_session.execute(
            text("SELECT tenant_id FROM platform.tenants WHERE slug = 'default'")
        )
    ).scalar_one()


@pytest.fixture(autouse=True)
def _install_aspect() -> None:
    """ORM 写（memory 行）依赖切面落审计——与 create_app 同一装配。"""
    install_audit_aspect()


@pytest.fixture(autouse=True)
async def _clean_memory_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    """每测试后清场：memory 行（default + tenant-memories）+ 审计行 +
    临时 Key + capabilities（capability 过滤用例）+ tenant-memories。"""
    yield
    b_ids = "SELECT tenant_id FROM platform.tenants WHERE slug = 'tenant-memories'"
    await db_session.execute(
        text("DELETE FROM memory.memories WHERE tenant_id = :t"),
        {"t": default_tenant_id},
    )
    await db_session.execute(
        text("DELETE FROM memory.memories WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text(
            "DELETE FROM platform.audit_logs WHERE tenant_id = :t"
            " AND resource_type IN ('memory.memories', 'memories')"
        ),
        {"t": default_tenant_id},
    )
    await db_session.execute(
        text("DELETE FROM platform.api_keys WHERE principal_id = :p"),
        {"p": NO_SCOPE_PRINCIPAL},
    )
    await db_session.execute(
        text("DELETE FROM platform.api_keys WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM platform.capabilities WHERE tenant_id = :t"),
        {"t": default_tenant_id},
    )
    await db_session.execute(
        text(
            "DELETE FROM platform.tenant_usage_daily WHERE tenant_id IN"
            " (SELECT tenant_id FROM platform.tenants WHERE slug = 'tenant-memories')"
        )
    )
    await db_session.execute(
        text("DELETE FROM platform.tenants WHERE slug = 'tenant-memories'")
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


async def _create_capability(client: httpx.AsyncClient) -> str:
    resp = await client.post(
        f"{BASE}/capabilities", headers=DEV_HEADERS, json=CAPABILITY_PAYLOAD
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["capability_id"]


# ---- 1. 主流程：创建 → 过滤 → 人工评审 → 重复评审 409 ----


async def test_memory_create_filter_review_and_conflict(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    capability_id = await _create_capability(client)

    resp = await client.post(
        f"{BASE}/memories", headers=DEV_HEADERS, json=_memory_payload(capability_id)
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    memory_id = UUID(body["memory_id"])
    assert body["status"] == "CANDIDATE"
    assert body["created_at"]

    row = (
        await db_session.execute(
            text(
                "SELECT capability_id, source_type, source_id, content, status,"
                " reviewed_by, reviewed_at, created_by FROM memory.memories"
                " WHERE memory_id = :m"
            ),
            {"m": str(memory_id)},
        )
    ).one()
    assert str(row.capability_id) == capability_id
    assert row.source_type == "decision"
    assert row.content == {"lesson": "VIP客户订单优先保交付，建议默认倾向加急"}
    assert row.status == "CANDIDATE"
    assert row.reviewed_by is None
    assert row.reviewed_at is None
    assert row.created_by == "agent-hub"

    # 列表：status/capability_id 过滤
    resp = await client.get(
        f"{BASE}/memories",
        params={"status": "CANDIDATE", "capability_id": capability_id},
        headers=DEV_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    page = resp.json()
    assert [item["memory_id"] for item in page["items"]] == [str(memory_id)]
    assert page["items"][0]["content"] == row.content

    for params in (
        {"status": "APPROVED"},
        {"capability_id": str(uuid4())},
    ):
        filtered = await client.get(f"{BASE}/memories", params=params, headers=DEV_HEADERS)
        assert filtered.status_code == 200, filtered.text
        assert filtered.json()["items"] == []

    # HUMAN 评审 APPROVED → 200 + 落库
    manager = await _login(client, "manager1")
    resp = await client.patch(
        f"{BASE}/memories/{memory_id}/review",
        headers=manager,
        json={"status": "APPROVED", "comment": "经验有效，纳入知识库"},
    )
    assert resp.status_code == 200, resp.text
    reviewed = resp.json()
    assert reviewed["memory_id"] == str(memory_id)
    assert reviewed["status"] == "APPROVED"
    assert reviewed["reviewed_at"]
    manager1_id = (
        await db_session.execute(
            text("SELECT user_id FROM platform.users WHERE username = 'manager1'")
        )
    ).scalar_one()
    assert reviewed["reviewed_by"] == str(manager1_id)

    row = (
        await db_session.execute(
            text(
                "SELECT status, reviewed_by, reviewed_at, review_comment"
                " FROM memory.memories WHERE memory_id = :m"
            ),
            {"m": str(memory_id)},
        )
    ).one()
    assert row.status == "APPROVED"
    assert row.reviewed_by == str(manager1_id)
    assert row.reviewed_at is not None
    assert row.review_comment == "经验有效，纳入知识库"

    # 重复评审 → 409 CONFLICT
    resp = await client.patch(
        f"{BASE}/memories/{memory_id}/review",
        headers=manager,
        json={"status": "REJECTED"},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "CONFLICT"


# ---- 2. capability_id 校验：不存在 400 / 缺省 201 ----


async def test_memory_capability_validation(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    resp = await client.post(
        f"{BASE}/memories",
        headers=DEV_HEADERS,
        json=_memory_payload(str(uuid4())),
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert (
        await db_session.execute(
            text("SELECT count(*) FROM memory.memories WHERE tenant_id = :t"),
            {"t": default_tenant_id},
        )
    ).scalar_one() == 0

    # capability_id 缺省（DDL 可空）→ 201
    resp = await client.post(
        f"{BASE}/memories", headers=DEV_HEADERS, json=_memory_payload()
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "CANDIDATE"


# ---- 3. Human-Only：SERVICE 评审 403 + 审计行 ----


async def test_service_review_forbidden_and_audited(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    resp = await client.post(
        f"{BASE}/memories", headers=DEV_HEADERS, json=_memory_payload()
    )
    assert resp.status_code == 201, resp.text
    memory_id = resp.json()["memory_id"]

    resp = await client.patch(
        f"{BASE}/memories/{memory_id}/review",
        headers=DEV_HEADERS,
        json={"status": "APPROVED"},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "GUARD_POLICY_DENIED"

    # GUARD_DENIED 审计行（独立会话提交，资源类型 memory.memories）
    audit = (
        await db_session.execute(
            text(
                "SELECT actor_type, actor_id, detail FROM platform.audit_logs"
                " WHERE tenant_id = :t AND action = 'GUARD_DENIED'"
                " AND resource_type = 'memory.memories'"
                " ORDER BY audit_id DESC LIMIT 1"
            ),
            {"t": default_tenant_id},
        )
    ).one()
    assert audit.actor_type == "SERVICE"
    assert audit.actor_id == "agent-hub"
    assert audit.detail["reason"] == "Human-Only"
    assert audit.detail["path"] == f"/api/v1/memories/{memory_id}/review"

    # 案例未被改动
    row = (
        await db_session.execute(
            text("SELECT status FROM memory.memories WHERE memory_id = :m"),
            {"m": memory_id},
        )
    ).one()
    assert row.status == "CANDIDATE"


# ---- 4/5. JWT 双轨 + API Key 轨道 ----


async def test_jwt_and_api_key_tracks(
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

    # 仅 readonly scope：写 403 / 读 200
    resp = await client.post(
        f"{BASE}/memories",
        headers={"X-API-Key": NO_SCOPE_KEY},
        json=_memory_payload(),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    resp = await client.get(f"{BASE}/memories", headers={"X-API-Key": NO_SCOPE_KEY})
    assert resp.status_code == 200, resp.text

    # 造一条候选供 JWT 轨道评审
    resp = await client.post(
        f"{BASE}/memories", headers=DEV_HEADERS, json=_memory_payload()
    )
    assert resp.status_code == 201, resp.text
    memory_id = resp.json()["memory_id"]

    manager = await _login(client, "manager1")
    analyst = await _login(client, "analyst1")

    # analyst 无 memory:review → 403；读 200
    resp = await client.patch(
        f"{BASE}/memories/{memory_id}/review",
        headers=analyst,
        json={"status": "APPROVED"},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    resp = await client.get(f"{BASE}/memories", headers=analyst)
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["items"]) == 1

    # manager 评审 → 200
    resp = await client.patch(
        f"{BASE}/memories/{memory_id}/review",
        headers=manager,
        json={"status": "APPROVED"},
    )
    assert resp.status_code == 200, resp.text


# ---- 6. 跨租户：评审 404 / 列表空 ----


async def test_cross_tenant_not_leaked(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    resp = await client.post(
        f"{BASE}/memories", headers=DEV_HEADERS, json=_memory_payload()
    )
    assert resp.status_code == 201, resp.text
    memory_id = resp.json()["memory_id"]

    tenant_b = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO platform.tenants (tenant_id, slug, name, status)"
            " VALUES (:t, :slug, '租户MemoriesB', 'ACTIVE')"
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

    # SERVICE 评审走 Human-Only 拒绝（403 先于资源存在性——AI 一律 403 语义）
    resp = await client.patch(
        f"{BASE}/memories/{memory_id}/review",
        headers=headers,
        json={"status": "APPROVED"},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "GUARD_POLICY_DENIED"

    resp = await client.get(f"{BASE}/memories", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []
