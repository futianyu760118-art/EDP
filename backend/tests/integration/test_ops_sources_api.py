"""T2 运营数据源批集成测试（W6）：GET /admin/outbox/status（W5-05）+
GET /admin/users（W5-11）。

- outbox status：空表两态（pending 0 / null）+ 造数（PENDING×2 /
  PUBLISHED×2（近 1h 内外各一）/ FAILED×1）五字段精确断言 + 鉴权矩阵
  （ANALYST 200——quality:read 含 ANALYST；SERVICE readonly Key 无
  quality scope → 403；匿名 401）；
- admin users：username ASC 游标顺序 / next_cursor 串联翻页 / 非平台
  ADMIN 403（default 租户 MANAGER + 租户 ADMIN（acme 管理员）双轨）。

造数：outbox / users 行经 migrator db_session 直插（绕 RLS）；acme 租户
经 API 开通（platform admin）后以其初始管理员登录构造「租户 ADMIN 非
平台 ADMIN」主体。清场：本模块 outbox 行 + 临时用户（t2ops- 前缀）+
临时 readonly Key + acme 租户全量。
"""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.core.security.apikey import hash_key
from edp_api.main import create_app
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

OUTBOX_STATUS = "/api/v1/admin/outbox/status"
ADMIN_USERS = "/api/v1/admin/users"
LOGIN = "/api/v1/auth/login"
SEED_PASSWORD = "Admin@123!"

READONLY_KEY = "t2-ops-readonly-key"
READONLY_PRINCIPAL = "t2-ops-readonly"

ACME = {
    "name": "Acme 运营数据源测试租户",
    "plan": "TRIAL",
    "admin": {
        "username": "acme-ops-admin",
        "email": "admin@acme-ops.example.com",
        "display_name": "Acme 运营管理员",
    },
}

_TEMP_USER_PREFIX = "t2ops-"

_INSERT_OUTBOX_SQL = text(
    """
    INSERT INTO event.outbox
        (tenant_id, aggregate_type, aggregate_id, event_type, payload,
         status, retry_count, published_at, created_at, created_by, updated_by)
    VALUES (:t, 'EVENT', :agg, 'evt.ops-test', CAST(:payload AS jsonb),
            :status, 0, :published_at, :created_at, 'test:ops-sources',
            'test:ops-sources')
    """
)


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS），outbox /
    admin users 路由随 create_app 装配。"""
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
async def _clean_ops_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> AsyncIterator[None]:
    """每测试前后清场：本模块 outbox 行 + 临时用户（前清防他模块残留
    outbox 行破坏空表基线）+ 临时 readonly Key；收尾另清 acme 租户。"""
    await _purge_module_rows(db_session, default_tenant_id)
    yield
    await _purge_module_rows(db_session, default_tenant_id)
    await _purge_tenants_of_admin(db_session, ACME["admin"]["username"])
    await db_session.commit()


async def _purge_module_rows(db_session: AsyncSession, tenant_id: UUID) -> None:
    await db_session.execute(
        text("DELETE FROM event.outbox WHERE tenant_id = :t"),
        {"t": tenant_id},
    )
    await db_session.execute(
        text(
            "DELETE FROM platform.users WHERE tenant_id = :t"
            " AND username LIKE :prefix"
        ),
        {"t": tenant_id, "prefix": f"{_TEMP_USER_PREFIX}%"},
    )
    await db_session.execute(
        text("DELETE FROM platform.api_keys WHERE principal_id = :p"),
        {"p": READONLY_PRINCIPAL},
    )
    await db_session.commit()


async def _purge_tenants_of_admin(
    db_session: AsyncSession, admin_username: str
) -> None:
    """按初始管理员用户名解析租户清场（migrator 绕 RLS；slug 由服务端
    自动生成不可预知、name 可被改写，均不可作清场键）。"""
    tids = (
        await db_session.execute(
            text(
                "SELECT DISTINCT tenant_id FROM platform.users WHERE username = :u"
            ),
            {"u": admin_username},
        )
    ).scalars()
    for tid in tids:
        for table in (
            "tenant_members",
            "users",
            "tenant_quotas",
            "tenant_usage_daily",
        ):
            await db_session.execute(
                text(f"DELETE FROM platform.{table} WHERE tenant_id = :tid"),  # noqa: S608
                {"tid": str(tid)},
            )
        await db_session.execute(
            text("DELETE FROM platform.tenants WHERE tenant_id = :tid"),
            {"tid": str(tid)},
        )
    await db_session.commit()


async def _login(
    client: httpx.AsyncClient, username: str, *, tenant_slug: str | None = None
) -> dict[str, str]:
    payload = {"username": username, "password": SEED_PASSWORD}
    if tenant_slug is not None:
        payload["tenant_slug"] = tenant_slug
    resp = await client.post(LOGIN, json=payload)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _insert_readonly_key(
    db_session: AsyncSession, tenant_id: UUID
) -> None:
    """直插仅 readonly scope 的 SERVICE Key（照 test_quality_api 模式）。"""
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
            "key_hash": hash_key(READONLY_KEY),
            "t": tenant_id,
            "principal": READONLY_PRINCIPAL,
            "scopes": ["readonly"],
        },
    )
    await db_session.commit()


async def _insert_outbox(
    db_session: AsyncSession,
    tenant_id: UUID,
    *,
    status: str,
    created_at: datetime,
    published_at: datetime | None = None,
) -> None:
    await db_session.execute(
        _INSERT_OUTBOX_SQL,
        {
            "t": tenant_id,
            "agg": uuid4(),
            "status": status,
            "published_at": published_at,
            "created_at": created_at,
            "payload": json.dumps({"seq": str(uuid4())}),
        },
    )


async def _insert_user(
    db_session: AsyncSession,
    tenant_id: UUID,
    *,
    username: str,
    display_name: str,
) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO platform.users
                (user_id, tenant_id, username, email, password_hash,
                 display_name, principal_type, is_platform_admin, status)
            VALUES (:u, :t, :username, :email, 'not-a-real-hash',
                    :display_name, 'HUMAN', FALSE, 'ACTIVE')
            """
        ),
        {
            "u": uuid4(),
            "t": tenant_id,
            "username": username,
            "email": f"{username}@ops-test.local",
            "display_name": display_name,
        },
    )


# ---- 1. outbox status：空表两态 ----


async def test_outbox_status_empty_table(
    client: httpx.AsyncClient, default_tenant_id: UUID
) -> None:
    analyst = await _login(client, "analyst1")
    resp = await client.get(OUTBOX_STATUS, headers=analyst)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "pending_count": 0,
        "oldest_pending_age_seconds": None,
        "published_last_hour": 0,
        "dlq_count": 0,
        "last_published_at": None,
    }


# ---- 2. outbox status：造数五字段 ----


async def test_outbox_status_seeded_five_fields(
    client: httpx.AsyncClient, db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    now = datetime.now(UTC)
    oldest_pending_at = now - timedelta(seconds=120)
    recent_published_at = now - timedelta(minutes=5)
    await _insert_outbox(
        db_session, default_tenant_id, status="PENDING", created_at=oldest_pending_at
    )
    await _insert_outbox(
        db_session,
        default_tenant_id,
        status="PENDING",
        created_at=now - timedelta(seconds=30),
    )
    await _insert_outbox(
        db_session,
        default_tenant_id,
        status="PUBLISHED",
        created_at=now - timedelta(minutes=6),
        published_at=recent_published_at,
    )
    await _insert_outbox(
        db_session,
        default_tenant_id,
        status="PUBLISHED",
        created_at=now - timedelta(hours=3),
        published_at=now - timedelta(hours=2),  # 1h 窗外不计
    )
    await _insert_outbox(
        db_session,
        default_tenant_id,
        status="FAILED",
        created_at=now - timedelta(hours=4),
        published_at=now - timedelta(hours=4),
    )
    await db_session.commit()

    analyst = await _login(client, "analyst1")
    resp = await client.get(OUTBOX_STATUS, headers=analyst)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pending_count"] == 2
    # 最老 PENDING created 120s 前 → 积压龄 ≈120（容忍插桩耗时）
    assert 110 <= body["oldest_pending_age_seconds"] <= 135
    assert body["published_last_hour"] == 1
    assert body["dlq_count"] == 1
    assert body["last_published_at"] is not None
    got = datetime.fromisoformat(body["last_published_at"])
    assert abs((got - recent_published_at).total_seconds()) < 10


# ---- 3. outbox status 鉴权矩阵 ----


async def test_outbox_status_auth_matrix(
    client: httpx.AsyncClient, db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    # ANALYST 200（quality:read 角色集含 ANALYST）——空表用例已覆盖，
    # 此处补 MANAGER 同放行
    manager = await _login(client, "manager1")
    assert (await client.get(OUTBOX_STATUS, headers=manager)).status_code == 200

    # SERVICE readonly Key：quality 无 scope 轨道 → 403 FORBIDDEN
    await _insert_readonly_key(db_session, default_tenant_id)
    denied = await client.get(OUTBOX_STATUS, headers={"X-API-Key": READONLY_KEY})
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "FORBIDDEN"

    # 匿名 → 401
    assert (await client.get(OUTBOX_STATUS)).status_code == 401


# ---- 4. admin users：username ASC 游标顺序 + 翻页 ----


async def test_admin_users_cursor_order_and_pagination(
    client: httpx.AsyncClient, db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    for name, display in (
        ("t2ops-gamma", "伽马"),
        ("t2ops-alpha", "阿尔法"),
        ("t2ops-beta", "贝塔"),
    ):
        await _insert_user(
            db_session, default_tenant_id, username=name, display_name=display
        )
    await db_session.commit()

    admin = await _login(client, "admin")
    first = await client.get(ADMIN_USERS, params={"limit": 4}, headers=admin)
    assert first.status_code == 200, first.text
    body = first.json()
    assert set(body) == {"items", "next_cursor", "total"}
    usernames = [item["username"] for item in body["items"]]
    # 种子三户 admin/analyst1/manager1 + t2ops-alpha（username ASC 首页）
    assert usernames == ["admin", "analyst1", "manager1", "t2ops-alpha"]
    assert all(
        set(item) == {"user_id", "username", "display_name"} for item in body["items"]
    )
    assert body["items"][0]["display_name"] == "平台管理员"
    assert body["next_cursor"] is not None

    second = await client.get(
        ADMIN_USERS,
        params={"limit": 4, "cursor": body["next_cursor"]},
        headers=admin,
    )
    assert second.status_code == 200, second.text
    tail = second.json()
    assert [item["username"] for item in tail["items"]] == ["t2ops-beta", "t2ops-gamma"]
    assert tail["next_cursor"] is None  # 尾页

    # 游标串联全量顺序 = username 全序
    walked = usernames + [item["username"] for item in tail["items"]]
    assert walked == sorted(walked)

    # 非法 cursor 视为首页（口径同既有游标端点）
    bogus = await client.get(
        ADMIN_USERS, params={"limit": 2, "cursor": "not-a-cursor"}, headers=admin
    )
    assert bogus.status_code == 200, bogus.text
    assert [item["username"] for item in bogus.json()["items"]] == ["admin", "analyst1"]


# ---- 5. admin users 鉴权：非平台 ADMIN 403（租户内 MANAGER / 他租户 ADMIN） ----


async def test_admin_users_requires_platform_admin(client: httpx.AsyncClient) -> None:
    # default 租户 MANAGER（is_platform_admin=False）→ 403
    manager = await _login(client, "manager1")
    denied = await client.get(ADMIN_USERS, headers=manager)
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "FORBIDDEN"

    # 匿名 → 401
    assert (await client.get(ADMIN_USERS)).status_code == 401


async def test_admin_users_tenant_admin_forbidden(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """租户 ADMIN（acme 初始管理员，ADMIN 角色但非平台 ADMIN）→ 403。"""
    platform_admin = await _login(client, "admin")
    created = await client.post(
        "/api/v1/tenants", json=ACME, headers=platform_admin
    )
    assert created.status_code == 201, created.text
    temporary_password = created.json()["temporary_password"]

    resp = await client.post(
        LOGIN,
        json={
            "tenant_slug": created.json()["slug"],  # 服务端自动生成编码
            "username": ACME["admin"]["username"],
            "password": temporary_password,
        },
    )
    assert resp.status_code == 200, resp.text
    acme_admin = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    denied = await client.get(ADMIN_USERS, headers=acme_admin)
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "FORBIDDEN"
