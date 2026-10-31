"""W5 B.14 租户 API 补齐集成测试（EDP-501 后端，T2）。

覆盖：PATCH 更新（plan 仅记录不调配额）/ context 切换（新 token RLS 落在
目标租户 + SUSPENDED 403 + 审计行）/ members CRUD（重复 409 + 空角色 400 +
最后 ACTIVE ADMIN 保护 400 + 租户 ADMIN 双轨：本租户 200 / 他租户 404）/
quotas（GET 七字段 + PATCH 留痕 + reason 缺失 400）/ current/usage 双轨
（租户 ADMIN 200 / ANALYST 403）。

组织方式沿 test_tenant_lifecycle：app_role_engine（edp_app，受 RLS）+
平台 admin 开通独立 slug 租户（acme-w5）+ migrator 直插造数（绕 RLS），
前后双清场。
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.core.security.password import hash_password
from edp_api.main import create_app
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

TENANTS = "/api/v1/tenants"
LOGIN = "/api/v1/auth/login"
OBJECTS = "/api/v1/objects"
SEED_PASSWORD = "Admin@123!"
TENANT_NAME = "Acme W5 租户"
EMAIL_DOMAIN = "acme-w5.example.com"

ACME = {
    "name": TENANT_NAME,
    "plan": "TRIAL",
    "admin": {
        "username": "acme-w5-admin",
        "email": "admin@acme-w5.example.com",
        "display_name": "Acme W5 管理员",
    },
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


async def _purge_tenant_by_id(
    db_session: AsyncSession, tenant_id: UUID | str
) -> None:
    """删除租户全部数据行（子先父后；migrator 绕 RLS；审计行按仅追加
    语义保留）。按 tenant_id 定位——slug 由服务端自动生成、name 可被
    PATCH 改写，均不可作清场键。"""
    tid = str(tenant_id)
    for table in (
        "tenant_members",
        "users",
        "tenant_quotas",
        "tenant_usage_daily",
    ):
        await db_session.execute(
            text(f"DELETE FROM platform.{table} WHERE tenant_id = :tid"),  # noqa: S608
            {"tid": tid},
        )
    await db_session.execute(
        text("DELETE FROM platform.tenants WHERE tenant_id = :tid"), {"tid": tid}
    )
    await db_session.commit()


async def _purge_tenants_of_admin(
    db_session: AsyncSession, admin_username: str
) -> None:
    """按初始管理员用户名解析租户清场（防改名残留：PATCH 可改 name，
    admin username 在本模块用例中不可变）。"""
    tids = (
        await db_session.execute(
            text(
                "SELECT DISTINCT tenant_id FROM platform.users WHERE username = :u"
            ),
            {"u": admin_username},
        )
    ).scalars()
    for tid in tids:
        await _purge_tenant_by_id(db_session, tid)


async def _login(
    client: httpx.AsyncClient, username: str, *, tenant_slug: str | None = None
) -> dict[str, str]:
    payload = {"username": username, "password": SEED_PASSWORD}
    if tenant_slug is not None:
        payload["tenant_slug"] = tenant_slug
    resp = await client.post(LOGIN, json=payload)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
async def acme(client: httpx.AsyncClient, db_session: AsyncSession) -> dict:
    """开通 acme-w5 租户（平台 admin）供各用例复用；前后双清场（前清按
    初始管理员用户名防上次改名残留，后清按 tenant_id 精确）。"""
    await _purge_tenants_of_admin(db_session, ACME["admin"]["username"])
    resp = await client.post(TENANTS, json=ACME, headers=await _login(client, "admin"))
    assert resp.status_code == 201, resp.text
    yield resp.json()
    await _purge_tenant_by_id(db_session, resp.json()["tenant_id"])


async def _acme_admin_headers(client: httpx.AsyncClient, acme: dict) -> dict[str, str]:
    """以开通响应的临时口令登录 acme-w5 管理员（tenant_slug 取响应回传
    的自动生成编码，绑定新租户）。"""
    resp = await client.post(
        LOGIN,
        json={
            "tenant_slug": acme["slug"],
            "username": ACME["admin"]["username"],
            "password": acme["temporary_password"],
        },
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _default_tenant_id(db_session: AsyncSession) -> UUID:
    return (
        await db_session.execute(
            text("SELECT tenant_id FROM platform.tenants WHERE slug = 'default'")
        )
    ).scalar_one()


async def _insert_user(
    db_session: AsyncSession, tenant_id: UUID, username: str, display_name: str
) -> UUID:
    """migrator 直插租户内用户（users FORCE RLS，绕行造数）。"""
    user_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO platform.users"
            " (user_id, tenant_id, username, email, password_hash, display_name,"
            "  principal_type, is_platform_admin, status)"
            " VALUES (:u, :t, :n, :e, :pw, :d, 'HUMAN', FALSE, 'ACTIVE')"
        ),
        {
            "u": user_id,
            "t": tenant_id,
            "n": username,
            "e": f"{username}@{EMAIL_DOMAIN}",
            "pw": hash_password(SEED_PASSWORD),
            "d": display_name,
        },
    )
    await db_session.commit()
    return user_id


async def _insert_object(
    db_session: AsyncSession, tenant_id: UUID, source_id: str
) -> None:
    await db_session.execute(
        text(
            "INSERT INTO master.business_objects"
            " (object_id, tenant_id, object_type, owner_domain, source_system, source_id)"
            " VALUES (:o, :t, 'customer', 'sales', 'ctx-src', :s)"
        ),
        {"o": uuid4(), "t": tenant_id, "s": source_id},
    )
    await db_session.commit()


async def _delete_ctx_objects(db_session: AsyncSession) -> None:
    await db_session.execute(
        text("DELETE FROM master.business_objects WHERE source_system = 'ctx-src'")
    )
    await db_session.commit()


# ---- 1. PATCH：更新生效 + plan 仅记录不调配额 + 404 / 403 ----


async def test_patch_tenant_update_and_not_found(
    client: httpx.AsyncClient, acme: dict
) -> None:
    admin = await _login(client, "admin")
    tenant_id = acme["tenant_id"]

    patched = await client.patch(
        f"{TENANTS}/{tenant_id}",
        json={"name": "Acme 制造集团", "plan": "PREMIUM"},
        headers=admin,
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["name"] == "Acme 制造集团"
    assert body["plan"] == "PREMIUM"

    # plan 变更仅记录不调配额：quotas 仍为 TRIAL 开通默认值
    assert body["quotas"]["storage_gb"] == 10
    assert body["quotas"]["events_per_month"] == 50_000
    assert body["quotas"]["api_rate_limit"] == 50

    missing = await client.patch(
        f"{TENANTS}/{uuid4()}", json={"name": "不存在"}, headers=admin
    )
    assert missing.status_code == 404, missing.text

    forbidden = await client.patch(
        f"{TENANTS}/{tenant_id}",
        json={"name": "越权改名"},
        headers=await _login(client, "manager1"),
    )
    assert forbidden.status_code == 403, forbidden.text
    assert forbidden.json()["error"]["code"] == "FORBIDDEN"


# ---- 2. context 切换：新 token RLS 落目标租户 + SUSPENDED 墙 + 审计行 ----


async def test_context_switch_rls_and_audit(
    client: httpx.AsyncClient, db_session: AsyncSession, acme: dict
) -> None:
    tenant_id = acme["tenant_id"]
    default_id = await _default_tenant_id(db_session)
    await _insert_object(db_session, default_id, "CTX-DEFAULT-0001")
    await _insert_object(db_session, UUID(tenant_id), "CTX-ACME-0001")

    admin = await _login(client, "admin")
    try:
        # 非 405/404 冒烟：平台 ADMIN 之外禁用（manager1 → 403）
        denied = await client.post(
            f"{TENANTS}/{tenant_id}/context", headers=await _login(client, "manager1")
        )
        assert denied.status_code == 403, denied.text

        switched = await client.post(f"{TENANTS}/{tenant_id}/context", headers=admin)
        assert switched.status_code == 200, switched.text
        body = switched.json()
        assert set(body) == {"tenant_id", "switched_at", "note", "access_token"}
        assert body["tenant_id"] == tenant_id
        assert body["switched_at"]
        assert body["note"] == "所有后续请求将以该租户执行，操作全程审计"
        assert body["access_token"]

        # 审计行：平台面 TENANT_CONTEXT_SWITCH，detail 含 from/to
        audit = (
            await db_session.execute(
                text(
                    "SELECT detail FROM platform.audit_logs"
                    " WHERE action = 'TENANT_CONTEXT_SWITCH'"
                    " AND resource_id = :tid ORDER BY audit_id"
                ),
                {"tid": tenant_id},
            )
        ).mappings().all()
        assert audit, "context 切换审计行缺失"
        assert audit[-1]["detail"]["from_tenant"] == str(default_id)
        assert audit[-1]["detail"]["to_tenant"] == tenant_id

        # 新 token 调业务端点：RLS 断言——目标租户可见、原租户不可见
        ctx_headers = {"Authorization": f"Bearer {body['access_token']}"}
        current = await client.get(f"{TENANTS}/current", headers=ctx_headers)
        assert current.status_code == 200, current.text
        assert current.json()["slug"] == acme["slug"]  # 自动生成编码

        target = await client.get(
            OBJECTS, headers=ctx_headers, params={"source_id": "CTX-ACME-0001"}
        )
        assert target.status_code == 200, target.text
        assert len(target.json()["items"]) == 1

        origin = await client.get(
            OBJECTS, headers=ctx_headers, params={"source_id": "CTX-DEFAULT-0001"}
        )
        assert origin.status_code == 200, origin.text
        assert origin.json()["items"] == []

        # SUSPENDED：切换被拒 + 已切 token 的后续请求被状态墙拦截
        suspended = await client.post(f"{TENANTS}/{tenant_id}/suspend", headers=admin)
        assert suspended.status_code == 202, suspended.text

        blocked_switch = await client.post(
            f"{TENANTS}/{tenant_id}/context", headers=admin
        )
        assert blocked_switch.status_code == 403, blocked_switch.text
        assert blocked_switch.json()["error"]["code"] == "TENANT_SUSPENDED"

        blocked_request = await client.get(OBJECTS, headers=ctx_headers)
        assert blocked_request.status_code == 403, blocked_request.text
        assert blocked_request.json()["error"]["code"] == "TENANT_SUSPENDED"

        resumed = await client.post(f"{TENANTS}/{tenant_id}/resume", headers=admin)
        assert resumed.status_code == 202, resumed.text
        recovered = await client.get(OBJECTS, headers=ctx_headers)
        assert recovered.status_code == 200, recovered.text

        # 目标租户不存在 → 404
        missing = await client.post(f"{TENANTS}/{uuid4()}/context", headers=admin)
        assert missing.status_code == 404, missing.text
    finally:
        await _delete_ctx_objects(db_session)


# ---- 3. members：CRUD 规则 + 双轨判定 ----


async def test_members_crud_and_rules(
    client: httpx.AsyncClient, db_session: AsyncSession, acme: dict
) -> None:
    tenant_id = acme["tenant_id"]
    admin = await _login(client, "admin")

    listed = await client.get(f"{TENANTS}/{tenant_id}/members", headers=admin)
    assert listed.status_code == 200, listed.text
    page = listed.json()
    assert page["next_cursor"] is None
    assert len(page["items"]) == 1  # 初始管理员
    initial = page["items"][0]
    assert set(initial) == {
        "member_id",
        "user_id",
        "display_name",
        "member_roles",
        "status",
        "joined_at",
    }
    assert initial["display_name"] == ACME["admin"]["display_name"]
    assert initial["member_roles"] == ["ADMIN"]
    assert initial["status"] == "ACTIVE"
    assert initial["joined_at"]

    # 添加成员：migrator 直插用户 → POST members 201
    user2 = await _insert_user(db_session, UUID(tenant_id), "member2", "第二成员")
    created = await client.post(
        f"{TENANTS}/{tenant_id}/members",
        json={"user_id": str(user2), "member_roles": ["MANAGER"]},
        headers=admin,
    )
    assert created.status_code == 201, created.text
    member2 = created.json()
    assert member2["member_roles"] == ["MANAGER"]
    assert member2["status"] == "ACTIVE"
    assert member2["display_name"] == "第二成员"
    assert member2["user_id"] == str(user2)

    # 重复添加 → 409；member_roles 空数组 → 400 VALIDATION_ERROR；未知用户 → 404
    duplicate = await client.post(
        f"{TENANTS}/{tenant_id}/members",
        json={"user_id": str(user2), "member_roles": ["MANAGER"]},
        headers=admin,
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["error"]["code"] == "CONFLICT"

    empty_roles = await client.post(
        f"{TENANTS}/{tenant_id}/members",
        json={"user_id": str(user2), "member_roles": []},
        headers=admin,
    )
    assert empty_roles.status_code == 400, empty_roles.text
    assert empty_roles.json()["error"]["code"] == "VALIDATION_ERROR"

    unknown_user = await client.post(
        f"{TENANTS}/{tenant_id}/members",
        json={"user_id": str(uuid4()), "member_roles": ["ANALYST"]},
        headers=admin,
    )
    assert unknown_user.status_code == 404, unknown_user.text

    # PATCH 改角色 → 200
    updated = await client.patch(
        f"{TENANTS}/{tenant_id}/members/{member2['member_id']}",
        json={"member_roles": ["ANALYST"]},
        headers=admin,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["member_roles"] == ["ANALYST"]

    # 最后 ACTIVE ADMIN 保护：禁用唯一 ADMIN → 400 VALIDATION_ERROR
    last_admin = await client.patch(
        f"{TENANTS}/{tenant_id}/members/{initial['member_id']}",
        json={"status": "DISABLED"},
        headers=admin,
    )
    assert last_admin.status_code == 400, last_admin.text
    assert last_admin.json()["error"]["code"] == "VALIDATION_ERROR"

    # 降级唯一 ADMIN 同样被拦（member_roles 去掉 ADMIN）
    demoted = await client.patch(
        f"{TENANTS}/{tenant_id}/members/{initial['member_id']}",
        json={"member_roles": ["MANAGER"]},
        headers=admin,
    )
    assert demoted.status_code == 400, demoted.text

    # 补位第二个 ADMIN 后即可禁用原 ADMIN → 200
    promoted = await client.patch(
        f"{TENANTS}/{tenant_id}/members/{member2['member_id']}",
        json={"member_roles": ["ADMIN"]},
        headers=admin,
    )
    assert promoted.status_code == 200, promoted.text
    disabled = await client.patch(
        f"{TENANTS}/{tenant_id}/members/{initial['member_id']}",
        json={"status": "DISABLED"},
        headers=admin,
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["status"] == "DISABLED"

    # 跨租户 / 不存在 member → 404（RLS 收敛，不泄露存在性）
    default_id = await _default_tenant_id(db_session)
    default_admin_member = (
        await db_session.execute(
            text(
                "SELECT tm.member_id FROM platform.tenant_members tm"
                " JOIN platform.users u ON u.user_id = tm.user_id"
                " WHERE tm.tenant_id = :t AND u.username = 'admin'"
            ),
            {"t": default_id},
        )
    ).scalar_one()
    cross = await client.patch(
        f"{TENANTS}/{tenant_id}/members/{default_admin_member}",
        json={"status": "DISABLED"},
        headers=admin,
    )
    assert cross.status_code == 404, cross.text

    missing_member = await client.patch(
        f"{TENANTS}/{tenant_id}/members/{uuid4()}",
        json={"member_roles": ["MANAGER"]},
        headers=admin,
    )
    assert missing_member.status_code == 404, missing_member.text

    # 双轨判定：租户 ADMIN 可读本租户；他租户 404；本租户非 ADMIN 403；
    # 租户 ADMIN 不可写（POST 403）
    acme_admin = await _acme_admin_headers(client, acme)
    own = await client.get(f"{TENANTS}/{tenant_id}/members", headers=acme_admin)
    assert own.status_code == 200, own.text
    assert len(own.json()["items"]) == 2

    other = await client.get(f"{TENANTS}/{default_id}/members", headers=acme_admin)
    assert other.status_code == 404, other.text

    manager = await _login(client, "manager1")
    same_tenant_non_admin = await client.get(
        f"{TENANTS}/{default_id}/members", headers=manager
    )
    assert same_tenant_non_admin.status_code == 403, same_tenant_non_admin.text

    tenant_admin_write = await client.post(
        f"{TENANTS}/{tenant_id}/members",
        json={"user_id": str(user2), "member_roles": ["ANALYST"]},
        headers=acme_admin,
    )
    assert tenant_admin_write.status_code == 403, tenant_admin_write.text


# ---- 4. quotas：GET 七字段 + PATCH 留痕 + reason 必填 ----


async def test_quotas_get_patch_and_reason(
    client: httpx.AsyncClient, db_session: AsyncSession, acme: dict
) -> None:
    tenant_id = acme["tenant_id"]
    admin = await _login(client, "admin")

    quotas = await client.get(f"{TENANTS}/{tenant_id}/quotas", headers=admin)
    assert quotas.status_code == 200, quotas.text
    body = quotas.json()
    assert set(body) == {
        "tenant_id",
        "api_rate_limit",
        "batch_max_events",
        "query_timeout_ms",
        "pool_share",
        "storage_gb",
        "events_per_month",
        "updated_at",
    }
    assert body["tenant_id"] == tenant_id
    assert body["api_rate_limit"] == 50  # TRIAL 默认
    assert body["batch_max_events"] == 500
    assert body["query_timeout_ms"] == 5000
    assert float(body["pool_share"]) == 1.0
    assert body["storage_gb"] == 10
    assert body["events_per_month"] == 50_000
    assert body["updated_at"]

    patched = await client.patch(
        f"{TENANTS}/{tenant_id}/quotas",
        json={
            "api_rate_limit": 300,
            "storage_gb": 100,
            "reason": "月末对账高峰",
        },
        headers=admin,
    )
    assert patched.status_code == 200, patched.text
    updated = patched.json()
    assert updated["api_rate_limit"] == 300
    assert updated["storage_gb"] == 100
    assert updated["events_per_month"] == 50_000  # 未提交字段不变
    assert updated["batch_max_events"] == 500

    # 留痕：TENANT_QUOTAS_ADJUST 审计行携带 reason 与变更清单
    audit = (
        await db_session.execute(
            text(
                "SELECT detail FROM platform.audit_logs"
                " WHERE action = 'TENANT_QUOTAS_ADJUST'"
                " AND resource_id = :tid ORDER BY audit_id"
            ),
            {"tid": tenant_id},
        )
    ).mappings().all()
    assert audit, "配额调整审计行缺失"
    detail = audit[-1]["detail"]
    assert detail["reason"] == "月末对账高峰"
    assert detail["changes"]["api_rate_limit"] == {"before": 50, "after": 300}

    # reason 缺失 / 空白 → 400 VALIDATION_ERROR；未知租户 → 404；非平台管理员 → 403
    no_reason = await client.patch(
        f"{TENANTS}/{tenant_id}/quotas",
        json={"api_rate_limit": 400},
        headers=admin,
    )
    assert no_reason.status_code == 400, no_reason.text
    assert no_reason.json()["error"]["code"] == "VALIDATION_ERROR"

    blank_reason = await client.patch(
        f"{TENANTS}/{tenant_id}/quotas",
        json={"api_rate_limit": 400, "reason": "  "},
        headers=admin,
    )
    assert blank_reason.status_code == 400, blank_reason.text
    assert blank_reason.json()["error"]["code"] == "VALIDATION_ERROR"

    missing_tenant = await client.patch(
        f"{TENANTS}/{uuid4()}/quotas",
        json={"api_rate_limit": 400, "reason": "不存在"},
        headers=admin,
    )
    assert missing_tenant.status_code == 404, missing_tenant.text

    forbidden = await client.get(
        f"{TENANTS}/{tenant_id}/quotas", headers=await _login(client, "manager1")
    )
    assert forbidden.status_code == 403, forbidden.text


# ---- 5. current/usage 双轨：租户 ADMIN 200 / ANALYST 与 MANAGER 403 ----


async def test_current_usage_dual_track(
    client: httpx.AsyncClient, db_session: AsyncSession, acme: dict
) -> None:
    tenant_id = acme["tenant_id"]
    today = datetime.now(UTC).date()
    await db_session.execute(
        text(
            "INSERT INTO platform.tenant_usage_daily"
            " (id, tenant_id, usage_date, api_calls, events_in, events_duplicated,"
            "  storage_gb, throttled_429)"
            " VALUES (:id, :t, :d, 42, 7, 1, 0, 0)"
        ),
        {"id": uuid4(), "t": tenant_id, "d": today},
    )
    await db_session.commit()

    acme_admin = await _acme_admin_headers(client, acme)
    usage = await client.get(f"{TENANTS}/current/usage", headers=acme_admin)
    assert usage.status_code == 200, usage.text
    items = usage.json()["items"]
    assert [item["usage_date"] for item in items] == [today.isoformat()]
    # tenant_scoped 每请求 api_calls +1（本请求亦计入）→ 断言下界
    assert items[0]["api_calls"] >= 42

    analyst = await _login(client, "analyst1")
    denied = await client.get(f"{TENANTS}/current/usage", headers=analyst)
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "FORBIDDEN"

    manager = await _login(client, "manager1")
    manager_denied = await client.get(f"{TENANTS}/current/usage", headers=manager)
    assert manager_denied.status_code == 403, manager_denied.text

    # 平台 ADMIN context 切换后经 tenant_scoped 轨道读本租户（act_tenant 生效）
    admin = await _login(client, "admin")
    switched = await client.post(f"{TENANTS}/{tenant_id}/context", headers=admin)
    assert switched.status_code == 200, switched.text
    ctx_headers = {"Authorization": f"Bearer {switched.json()['access_token']}"}
    ctx_usage = await client.get(f"{TENANTS}/current/usage", headers=ctx_headers)
    assert ctx_usage.status_code == 200, ctx_usage.text
    assert items[0]["api_calls"] >= 42
    assert ctx_usage.json()["items"][0]["api_calls"] >= items[0]["api_calls"]

    # 平台面端点契约不变（回归）：GET /tenants/{id}/usage 仍 200
    platform_face = await client.get(f"{TENANTS}/{tenant_id}/usage", headers=admin)
    assert platform_face.status_code == 200, platform_face.text
    assert platform_face.json()["items"][0]["api_calls"] >= 42
