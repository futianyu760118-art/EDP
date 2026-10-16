"""T17 租户生命周期集成测试（EDP-024）：开通原子 / 暂停恢复墙 / 强确认注销。

叙事主线（M2 演示序列）：平台 admin 开通 acme（TRIAL + 初始管理员临时
口令）→ 新管理员登录拿到独立租户上下文 → suspend 状态墙（业务 API 403
TENANT_SUSPENDED）→ resume 复通 → cancel 强确认（confirm+reason）→
重复注销 422；非平台管理员 403；编码自动生成（ten-YYYY-NNNN，序号
递增不撞号，设计 2026-10-16-tenant-code-autogen）；生命周期审计行
（T11 切面：ORM 属性赋值 → TENANTS_UPDATE）。

登录租户解析：POST /auth/login 的 tenant_slug 参数（缺省 default）——
B.1 既有机制，新租户管理员以开通响应回传的 slug 登录绑定新租户上下文。
清场按租户 name 定位（slug 已由服务端自动生成，测试不可预知）。
"""

import re

import httpx
import pytest
from edp_api.core import db as core_db
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
TENANT_CODE_PATTERN = r"ten-\d{4}-\d{4,}"

ACME = {
    "name": "Acme 示例租户",
    "plan": "TRIAL",
    "admin": {
        "username": "acme-admin",
        "email": "admin@acme.example.com",
        "display_name": "Acme 管理员",
    },
}


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS），租户路由与
    审计切面随 create_app 装配（install_audit_aspect 幂等）。"""
    await core_db.dispose_engine()
    monkeypatch.setattr(core_db, "get_engine", lambda: app_role_engine)
    transport = httpx.ASGITransport(app=create_app())
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        await core_db.dispose_engine()  # 重置绑定到测试引擎的会话工厂


async def _purge_tenant_by_id(
    db_session: AsyncSession, tenant_id: str
) -> None:
    """删除租户全部数据行（子先父后；migrator 绕 RLS。审计行按仅追加
    语义保留——resource_id 指向已删租户不构成外键。slug 由服务端自动
    生成、name 可被改写，均不可作清场键，按 tenant_id 定位）。"""
    for table in (
        "tenant_members",
        "users",
        "tenant_quotas",
        "tenant_usage_daily",
    ):
        await db_session.execute(
            text(f"DELETE FROM platform.{table} WHERE tenant_id = :tid"),  # noqa: S608
            {"tid": tenant_id},
        )
    await db_session.execute(
        text("DELETE FROM platform.tenants WHERE tenant_id = :tid"),
        {"tid": tenant_id},
    )
    await db_session.commit()


async def _purge_tenants_of_admin(
    db_session: AsyncSession, admin_username: str
) -> None:
    """按初始管理员用户名解析租户清场（本模块全部租户共用 acme-admin，
    一次清掉主租户与审计/序号用例的残留）。"""
    tids = (
        await db_session.execute(
            text(
                "SELECT DISTINCT tenant_id FROM platform.users WHERE username = :u"
            ),
            {"u": admin_username},
        )
    ).scalars()
    for tid in tids:
        await _purge_tenant_by_id(db_session, str(tid))


async def _login(
    client: httpx.AsyncClient, username: str, *, tenant_slug: str | None = None
) -> dict[str, str]:
    """登录 → Authorization 头（admin/manager1 为 default 租户种子账号）。"""
    payload = {"username": username, "password": SEED_PASSWORD}
    if tenant_slug is not None:
        payload["tenant_slug"] = tenant_slug
    resp = await client.post(LOGIN, json=payload)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
async def acme(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> dict:
    """开通 acme 租户（平台 admin）供各用例复用；前后双清场（前清按
    初始管理员用户名防残留，后清按 tenant_id 精确）。"""
    await _purge_tenants_of_admin(db_session, ACME["admin"]["username"])
    resp = await client.post(TENANTS, json=ACME, headers=await _login(client, "admin"))
    assert resp.status_code == 201, resp.text
    yield resp.json()
    await _purge_tenant_by_id(db_session, resp.json()["tenant_id"])


async def _acme_admin_headers(client: httpx.AsyncClient, acme: dict) -> dict[str, str]:
    """用开通响应的临时口令以 acme 管理员身份登录（tenant_slug 绑定
    新租户——slug 取开通响应回传的自动生成编码）。"""
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


# ---- 1. 开通：201 + 自动编码 + 临时口令 + 新管理员登录拿到独立租户上下文 ----


async def test_provision_and_initial_admin_login(
    client: httpx.AsyncClient, acme: dict
) -> None:
    assert re.fullmatch(TENANT_CODE_PATTERN, acme["slug"])  # 自动生成 ten-YYYY-NNNN
    assert acme["status"] == "ACTIVE"
    assert acme["temporary_password"]  # 未携带密码 → B.14 临时口令回传一次

    headers = await _acme_admin_headers(client, acme)
    current = await client.get(f"{TENANTS}/current", headers=headers)
    assert current.status_code == 200, current.text
    assert current.json()["slug"] == acme["slug"]

    # 配额行按 TRIAL 计划落库；usage MVP 为空字段
    detail = await client.get(
        f"{TENANTS}/{acme['tenant_id']}", headers=await _login(client, "admin")
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["plan"] == "TRIAL"
    assert body["quotas"]["storage_gb"] == 10
    assert body["quotas"]["events_per_month"] == 50_000
    assert body["usage"]["storage_used_gb"] is None


# ---- 2. 暂停/恢复墙：suspend → 业务 API 403 TENANT_SUSPENDED；resume 复通 ----


async def test_suspend_resume_wall(client: httpx.AsyncClient, acme: dict) -> None:
    admin = await _login(client, "admin")
    acme_headers = await _acme_admin_headers(client, acme)
    before = await client.get(OBJECTS, headers=acme_headers)
    assert before.status_code == 200, before.text

    suspended = await client.post(
        f"{TENANTS}/{acme['tenant_id']}/suspend", headers=admin
    )
    assert suspended.status_code == 202, suspended.text
    assert suspended.json()["status"] == "SUSPENDED"
    assert suspended.json()["operation"] == "suspend"

    blocked = await client.get(OBJECTS, headers=acme_headers)
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "TENANT_SUSPENDED"

    resumed = await client.post(f"{TENANTS}/{acme['tenant_id']}/resume", headers=admin)
    assert resumed.status_code == 202, resumed.text
    assert resumed.json()["status"] == "ACTIVE"

    after = await client.get(OBJECTS, headers=acme_headers)
    assert after.status_code == 200, after.text


# ---- 3. 注销强确认：缺 confirm → 400；confirm+reason → 202 + 保留窗口；重复 → 422 ----


async def test_cancel_confirm_flow(client: httpx.AsyncClient, acme: dict) -> None:
    admin = await _login(client, "admin")
    tenant_id = acme["tenant_id"]

    refused = await client.post(
        f"{TENANTS}/{tenant_id}/cancel",
        json={"confirm": False, "reason": "试点结束"},
        headers=admin,
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["code"] == "VALIDATION_ERROR"

    cancelled = await client.post(
        f"{TENANTS}/{tenant_id}/cancel",
        json={"confirm": True, "reason": "试点结束"},
        headers=admin,
    )
    assert cancelled.status_code == 202, cancelled.text
    assert cancelled.json()["status"] == "CANCELLED"

    detail = await client.get(f"{TENANTS}/{tenant_id}", headers=admin)
    assert detail.status_code == 200, detail.text
    assert detail.json()["cancel_scheduled_at"] is not None  # now + 30d

    repeat = await client.post(
        f"{TENANTS}/{tenant_id}/cancel",
        json={"confirm": True, "reason": "再次注销"},
        headers=admin,
    )
    assert repeat.status_code == 422, repeat.text
    assert repeat.json()["error"]["code"] == "INVALID_TRANSITION"


# ---- 4. 非平台管理员（manager1，is_platform_admin=False）→ 403 ----


async def test_non_platform_admin_forbidden(
    client: httpx.AsyncClient, acme: dict
) -> None:
    resp = await client.post(
        TENANTS,
        json=ACME,
        headers=await _login(client, "manager1"),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"


# ---- 5. 编码自动生成：新格式 + 序号递增不撞号（请求体无 slug 字段） ----


async def test_code_autogen_format_and_sequence(
    client: httpx.AsyncClient, db_session: AsyncSession, acme: dict
) -> None:
    # 请求体传入 slug 亦被忽略（完全自动，不支持自定义）
    resp = await client.post(
        TENANTS,
        json={**ACME, "name": "Acme 序号租户", "slug": "hand-picked"},
        headers=await _login(client, "admin"),
    )
    assert resp.status_code == 201, resp.text
    second = resp.json()
    assert re.fullmatch(TENANT_CODE_PATTERN, second["slug"])
    assert second["slug"] != "hand-picked"
    assert second["slug"] != acme["slug"]  # 同年序号递增 → 必不相同
    await _purge_tenant_by_id(db_session, second["tenant_id"])


# ---- 6. 生命周期审计：suspend/resume/cancel 各产生一条 TENANTS_UPDATE ----
# （独立租户"Acme 审计租户"，避免与其他用例的状态变更互相干扰）


async def test_lifecycle_audited(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _purge_tenants_of_admin(db_session, ACME["admin"]["username"])
    admin = await _login(client, "admin")
    login_body = await client.post(
        LOGIN, json={"username": "admin", "password": SEED_PASSWORD}
    )
    assert login_body.status_code == 200, login_body.text
    admin_user_id = str(login_body.json()["user"]["user_id"])
    created_tenant_id = ""
    try:
        created = await client.post(
            TENANTS,
            json={**ACME, "name": "Acme 审计租户"},
            headers=admin,
        )
        assert created.status_code == 201, created.text
        tenant_id = created.json()["tenant_id"]
        created_tenant_id = tenant_id

        for operation in ("suspend", "resume", "cancel"):
            body = (
                {"confirm": True, "reason": "试点结束"}
                if operation == "cancel"
                else None
            )
            resp = await client.post(
                f"{TENANTS}/{tenant_id}/{operation}", json=body, headers=admin
            )
            assert resp.status_code == 202, resp.text

        rows = (
            await db_session.execute(
                text(
                    "SELECT action, actor_type, actor_id, detail"
                    " FROM platform.audit_logs"
                    " WHERE action = 'TENANTS_UPDATE' AND resource_id = :tid"
                    " ORDER BY audit_id"
                ),
                {"tid": str(tenant_id)},
            )
        ).mappings().all()
        assert len(rows) == 3
        transitions = [
            (row["detail"]["before"]["status"], row["detail"]["after"]["status"])
            for row in rows
        ]
        assert transitions == [
            ("ACTIVE", "SUSPENDED"),
            ("SUSPENDED", "ACTIVE"),
            ("ACTIVE", "CANCELLED"),
        ]
        # 平台级路由 actor 归因：require_platform_admin 写 current_principal
        assert all(row["actor_type"] == "HUMAN" for row in rows)
        assert all(row["actor_id"] == admin_user_id for row in rows)
    finally:
        if created_tenant_id:
            await _purge_tenant_by_id(db_session, created_tenant_id)
        else:  # 创建中断残留 → 按管理员用户名兜底
            await _purge_tenants_of_admin(db_session, ACME["admin"]["username"])
