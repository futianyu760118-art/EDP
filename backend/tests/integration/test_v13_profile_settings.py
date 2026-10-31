"""V1.3 个人设置后端集成测试：/me 扩展 + PUT /auth/profile + 改密。

app 经 httpx.ASGITransport 直连；引擎注入同 test_auth 惯例（function 级
monkeypatch core.db.get_engine——get_db→get_session_local 不经 DI）。

覆盖：
1. MeResponse 含 display_name / email（种子用户）；
2. PUT /auth/profile：改 display_name/email → /me 返回新值；审计留痕；
3. POST /auth/change-password：旧密错误 401；弱密码 400；成功改密后
   旧密码登录失败、新密码登录成功；审计留痕；改后还原种子密码。
"""

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.main import app
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

LOGIN_URL = "/api/v1/auth/login"
ME_URL = "/api/v1/auth/me"
PROFILE_URL = "/api/v1/auth/profile"
PASSWORD_URL = "/api/v1/auth/change-password"

SEED_PASSWORD = "Admin@123!"
NEW_PASSWORD = "NewPass@2026!"


@pytest.fixture
async def client(migrated_db: str, monkeypatch: pytest.MonkeyPatch) -> httpx.AsyncClient:
    """ASGI 直连客户端：function 级引擎绑定（同 test_auth）。"""
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


async def _login(client: httpx.AsyncClient, username: str, password: str) -> dict:
    resp = await client.post(
        LOGIN_URL,
        json={"username": username, "password": password, "tenant_slug": "default"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_me_includes_display_name_and_email(client: httpx.AsyncClient) -> None:
    tokens = await _login(client, "admin", SEED_PASSWORD)
    resp = await client.get(
        ME_URL, headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "admin"
    assert "display_name" in body
    assert "email" in body


async def test_profile_update_and_restore(client: httpx.AsyncClient) -> None:
    """改 display_name/email → /me 可见 + 审计留痕；测试后还原。"""
    tokens = await _login(client, "admin", SEED_PASSWORD)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    me_before = (await client.get(ME_URL, headers=headers)).json()
    resp = await client.put(
        PROFILE_URL,
        headers=headers,
        json={"display_name": "个人设置测试名", "email": "profile-test@edp.local"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["display_name"] == "个人设置测试名"
    assert resp.json()["email"] == "profile-test@edp.local"

    me_after = (await client.get(ME_URL, headers=headers)).json()
    assert me_after["display_name"] == "个人设置测试名"

    # 还原
    restore_payload = {
        "display_name": me_before["display_name"] or "",
        "email": me_before["email"] or "",
    }
    resp = await client.put(PROFILE_URL, headers=headers, json=restore_payload)
    assert resp.status_code == 200


async def test_profile_audit_logged(
    client: httpx.AsyncClient, migrated_db: str
) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    tokens = await _login(client, "admin", SEED_PASSWORD)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    await client.put(
        PROFILE_URL,
        headers=headers,
        json={"display_name": "审计测试名"},
    )
    engine = create_async_engine(migrated_db)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as sess:
            count = (
                await sess.execute(
                    text("""
                        SELECT count(*) FROM platform.audit_logs
                        WHERE action = 'AUTH_PROFILE_UPDATE'
                    """)
                )
            ).scalar_one()
    finally:
        await engine.dispose()
    assert count >= 1


async def test_change_password_flow(client: httpx.AsyncClient) -> None:
    """旧密错 401 → 弱密 400 → 成功 → 新密登录生效；改后还原。"""
    tokens = await _login(client, "admin", SEED_PASSWORD)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    # 旧密错误（会话内校验语义：400，不触发 401 会话失效流程）
    resp = await client.post(
        PASSWORD_URL,
        headers=headers,
        json={"old_password": "Wrong@123!", "new_password": NEW_PASSWORD},
    )
    assert resp.status_code == 400

    # 弱密码（纯字母）
    resp = await client.post(
        PASSWORD_URL,
        headers=headers,
        json={"old_password": SEED_PASSWORD, "new_password": "alllowercase"},
    )
    assert resp.status_code == 400

    # 与旧密相同
    resp = await client.post(
        PASSWORD_URL,
        headers=headers,
        json={"old_password": SEED_PASSWORD, "new_password": SEED_PASSWORD},
    )
    assert resp.status_code == 400

    # 成功
    resp = await client.post(
        PASSWORD_URL,
        headers=headers,
        json={"old_password": SEED_PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert resp.status_code == 200, resp.text

    # 旧密登录失败 / 新密成功
    fail = await client.post(
        LOGIN_URL,
        json={"username": "admin", "password": SEED_PASSWORD, "tenant_slug": "default"},
    )
    assert fail.status_code == 401
    await _login(client, "admin", NEW_PASSWORD)

    # 还原
    tokens2 = await _login(client, "admin", NEW_PASSWORD)
    resp = await client.post(
        PASSWORD_URL,
        headers={"Authorization": f"Bearer {tokens2['access_token']}"},
        json={"old_password": NEW_PASSWORD, "new_password": SEED_PASSWORD},
    )
    assert resp.status_code == 200


async def test_password_audit_logged(
    client: httpx.AsyncClient, migrated_db: str
) -> None:
    """改密动作审计留痕（AUTH_PASSWORD_CHANGE）。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    tokens = await _login(client, "admin", SEED_PASSWORD)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    resp = await client.post(
        PASSWORD_URL,
        headers=headers,
        json={"old_password": SEED_PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert resp.status_code == 200

    engine = create_async_engine(migrated_db)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as sess:
            count = (
                await sess.execute(
                    text("""
                        SELECT count(*) FROM platform.audit_logs
                        WHERE action = 'AUTH_PASSWORD_CHANGE'
                    """)
                )
            ).scalar_one()
    finally:
        await engine.dispose()
    assert count >= 1

    # 还原
    tokens2 = await _login(client, "admin", NEW_PASSWORD)
    await client.post(
        PASSWORD_URL,
        headers={"Authorization": f"Bearer {tokens2['access_token']}"},
        json={"old_password": NEW_PASSWORD, "new_password": SEED_PASSWORD},
    )
