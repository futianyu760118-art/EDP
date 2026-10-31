"""tenantmgmt 集成测试：GET /api/v1/tenants/current（模块结构补齐项）。

tenant_scoped 链路（认证 → 租户状态 → bind_tenant）后回读控制面租户行：
JWT 与 API Key 双轨均以凭据租户为准；无凭据 → 401；租户 SUSPENDED → 403。
"""

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.main import app
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = [pytest.mark.integration]

CURRENT = "/api/v1/tenants/current"
DEV_API_KEY = "edp-dev-agent-hub-key"


@pytest.fixture
async def client(
    migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端（与 test_auth 同法：monkeypatch core.db.get_engine）。"""
    engine = create_async_engine(migrated_db)
    await core_db.dispose_engine()
    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        await core_db.dispose_engine()
        await engine.dispose()


async def _login_token(client: httpx.AsyncClient) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "Admin@123!"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def test_current_tenant_jwt_full_contract(client: httpx.AsyncClient) -> None:
    resp = await client.get(
        CURRENT, headers={"Authorization": f"Bearer {await _login_token(client)}"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"tenant_id", "slug", "name", "plan", "status"}
    assert body["slug"] == "default"
    assert body["name"] == "默认租户"
    assert body["plan"] == "STANDARD"
    assert body["status"] == "ACTIVE"


async def test_current_tenant_api_key_same_tenant(client: httpx.AsyncClient) -> None:
    """API Key 服务主体：以 Key 绑定租户为准（种子 Key 属 default 租户）。"""
    resp = await client.get(CURRENT, headers={"X-API-Key": DEV_API_KEY})
    assert resp.status_code == 200, resp.text
    assert resp.json()["slug"] == "default"


async def test_current_tenant_unauthenticated(client: httpx.AsyncClient) -> None:
    resp = await client.get(CURRENT)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_current_tenant_suspended_403(
    client: httpx.AsyncClient, db_session
) -> None:
    """租户 SUSPENDED：tenant_scoped 状态守卫 → 403 TENANT_SUSPENDED；后还原。"""
    token = await _login_token(client)
    try:
        await db_session.execute(
            text("UPDATE platform.tenants SET status = 'SUSPENDED' WHERE slug = 'default'")
        )
        await db_session.commit()
        resp = await client.get(
            CURRENT, headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "TENANT_SUSPENDED"
    finally:
        await db_session.execute(
            text("UPDATE platform.tenants SET status = 'ACTIVE' WHERE slug = 'default'")
        )
        await db_session.commit()
