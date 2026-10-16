"""auth 集成测试（T9）：login / refresh / me + 租户状态守卫 + API Key me 拒绝。

app 经 httpx.ASGITransport 直连（无网络栈）。引擎注入说明：get_db →
get_session_local → get_engine 的内部调用链不经 FastAPI 依赖注入，
app.dependency_overrides 拦截不到——故用 monkeypatch 替换 core.db.get_engine
模块属性（function 级，自动还原）。应用无 lifespan 钩子，无需 asgi-lifespan。
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import jwt as pyjwt
import pytest
from edp_api.core import db as core_db
from edp_api.core.config import get_settings
from edp_api.core.security.rbac import ALL_PERMISSIONS, ROLE_PERMISSIONS
from edp_api.main import app
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
ME = "/api/v1/auth/me"


@pytest.fixture
async def client(
    migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：function 级引擎绑定到迁移后的 testcontainers 库。"""
    engine = create_async_engine(migrated_db)
    await core_db.dispose_engine()  # 清掉既有全局引擎/会话工厂缓存
    monkeypatch.setattr(core_db, "get_engine", lambda: engine)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        await core_db.dispose_engine()  # 重置绑定到测试引擎的会话工厂
        await engine.dispose()


async def _login(
    client: httpx.AsyncClient,
    username: str = "admin",
    password: str = "Admin@123!",
    tenant_slug: str | None = None,
) -> httpx.Response:
    payload: dict = {"username": username, "password": password}
    if tenant_slug is not None:
        payload["tenant_slug"] = tenant_slug
    return await client.post(LOGIN, json=payload)


async def test_login_admin_success_full_contract(client: httpx.AsyncClient) -> None:
    resp = await _login(client)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"access_token", "refresh_token", "expires_in", "tenant", "user"}
    assert body["expires_in"] == 7200
    assert body["access_token"] and body["refresh_token"]
    assert body["tenant"]["slug"] == "default"
    assert body["tenant"]["name"] == "默认租户"
    assert body["tenant"]["status"] == "ACTIVE"
    UUID(body["tenant"]["tenant_id"])
    assert body["user"]["username"] == "admin"
    assert "ADMIN" in body["user"]["roles"]
    assert body["user"]["is_platform_admin"] is True
    UUID(body["user"]["user_id"])


async def test_login_wrong_password_unauthenticated(client: httpx.AsyncClient) -> None:
    resp = await _login(client, password="wrong-password")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_login_unknown_tenant_not_leaked(client: httpx.AsyncClient) -> None:
    """租户不存在与凭据错误同响应：401 UNAUTHENTICATED，不泄露存在性。"""
    resp = await _login(client, tenant_slug="no-such-tenant")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_refresh_roundtrip_new_access_calls_me(
    client: httpx.AsyncClient,
) -> None:
    login = await _login(client, username="manager1")
    refresh_token = login.json()["refresh_token"]

    resp = await client.post(REFRESH, json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"access_token", "expires_in"}
    assert body["expires_in"] == 7200

    me = await client.get(ME, headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["username"] == "manager1"


async def test_refresh_rejects_access_token(client: httpx.AsyncClient) -> None:
    """typ 混用：access token 不能当 refresh token 用。"""
    login = await _login(client)
    resp = await client.post(REFRESH, json={"refresh_token": login.json()["access_token"]})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_me_admin_roles_and_wildcard_permissions(
    client: httpx.AsyncClient,
) -> None:
    login = await _login(client)
    resp = await client.get(
        ME, headers={"Authorization": f"Bearer {login.json()['access_token']}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {
        "user_id", "username", "display_name", "email", "org_id", "tenant_id",
        "is_platform_admin", "roles", "permissions",
    }
    assert body["username"] == "admin"
    assert body["roles"] == ["ADMIN"]
    assert body["is_platform_admin"] is True
    assert body["org_id"] is None
    # admin 是平台管理员：权限码通配展开为全部 23 项
    # （0005 基线 + 0008 adapters 两码 + 0010 tools:read/ebms:read
    #  + 0011 trace:read/memory:read/memory:review
    #  + 0012 audit:policy_read/audit:policy_write
    #  + 0013 quality:read/quality:run）
    assert set(body["permissions"]) == ALL_PERMISSIONS
    assert len(body["permissions"]) == 30


async def test_me_manager_roles_and_permissions(client: httpx.AsyncClient) -> None:
    login = await _login(client, username="manager1")
    resp = await client.get(
        ME, headers={"Authorization": f"Bearer {login.json()['access_token']}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["roles"] == ["MANAGER"]
    assert body["is_platform_admin"] is False
    assert set(body["permissions"]) == ROLE_PERMISSIONS["MANAGER"]


async def test_me_rejects_api_key(client: httpx.AsyncClient) -> None:
    """me 仅 JWT（B.1）：API Key 服务主体无用户语义 → 401。"""
    resp = await client.get(ME, headers={"X-API-Key": "edp-dev-agent-hub-key"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_login_suspended_tenant_rejected(
    client: httpx.AsyncClient, db_session
) -> None:
    """租户 SUSPENDED：登录即时 403 TENANT_SUSPENDED；测试后还原。"""
    try:
        await db_session.execute(
            text("UPDATE platform.tenants SET status = 'SUSPENDED' WHERE slug = 'default'")
        )
        await db_session.commit()
        resp = await _login(client)
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "TENANT_SUSPENDED"
    finally:
        await db_session.execute(
            text("UPDATE platform.tenants SET status = 'ACTIVE' WHERE slug = 'default'")
        )
        await db_session.commit()


async def test_me_bad_and_expired_token_unauthenticated(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get(ME, headers={"Authorization": "Bearer garbage.token.here"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"

    settings = get_settings()
    now = datetime.now(UTC)
    expired = pyjwt.encode(
        {
            "sub": str(uuid4()),
            "tenant_id": str(uuid4()),
            "roles": [],
            "principal_type": "HUMAN",
            "is_platform_admin": False,
            "typ": "access",
            "iat": now - timedelta(hours=3),
            "exp": now - timedelta(hours=1),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_alg,
    )
    resp = await client.get(ME, headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"
