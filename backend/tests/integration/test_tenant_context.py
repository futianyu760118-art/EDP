"""T10 租户上下文集成测试：tenant_scoped 依赖全链路（全部以 edp_app 角色连接）。

应用引擎 = conftest.app_role_engine（NOBYPASSRLS，与生产 api 同角色）——
这使 RLS 死锁（refresh/me 在绑定前查 FORCE RLS 表恒 0 行）真实暴露，
T9 集成测试用 migrator 超级用户连接看不到该缺陷。

业务探针：测试内定义 `GET /api/v1/_probe/objects`（tenant_scoped + 直查
master.business_objects count），经 create_app(extra_routers=[...]) 注入——
生产代码不含测试面，后续 T11 registry 路由落地后探针可退役。
"""

from time import perf_counter
from typing import Annotated
from uuid import UUID, uuid4

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.core.db import get_db
from edp_api.core.security.principal import Principal
from edp_api.main import create_app
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
ME = "/api/v1/auth/me"
PROBE = "/api/v1/_probe/objects"

DEV_API_KEY = "edp-dev-agent-hub-key"
SEED_PASSWORD = "Admin@123!"


# ---- 业务探针路由（仅测试装配） ----

probe_router = APIRouter(prefix="/api/v1/_probe", tags=["probe"])


@probe_router.get("/objects")
async def probe_objects(
    principal: Annotated[Principal, Depends(tenant_scoped)],
    sess: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, object]:
    """tenant_scoped 依赖 + 直查受 RLS 保护的业务表（master.business_objects）。"""
    count: int = (
        await sess.execute(text("SELECT count(*) FROM master.business_objects"))
    ).scalar_one()
    return {"count": count, "tenant_id": str(principal.tenant_id)}


# ---- fixture：edp_app 引擎 + 探针 app ----


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS），含探针路由。"""
    await core_db.dispose_engine()
    monkeypatch.setattr(core_db, "get_engine", lambda: app_role_engine)
    probe_app = create_app(extra_routers=[probe_router])
    transport = httpx.ASGITransport(app=probe_app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        await core_db.dispose_engine()  # 重置绑定到测试引擎的会话工厂


# ---- 种数辅助（migrator 直插/直改，绕 RLS） ----


async def _default_tenant_id(db_session: AsyncSession) -> UUID:
    return (
        await db_session.execute(
            text("SELECT tenant_id FROM platform.tenants WHERE slug = 'default'")
        )
    ).scalar_one()


async def _insert_probe_object(db_session: AsyncSession, tenant_id: UUID) -> UUID:
    object_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO master.business_objects"
            " (object_id, tenant_id, object_type, owner_domain, source_system, source_id)"
            " VALUES (:oid, :tid, 'customer', 'sales', 'probe-src', 'probe-1')"
        ),
        {"oid": object_id, "tid": tenant_id},
    )
    await db_session.commit()
    return object_id


async def _delete_probe_object(db_session: AsyncSession, object_id: UUID) -> None:
    await db_session.execute(
        text("DELETE FROM master.business_objects WHERE object_id = :oid"),
        {"oid": object_id},
    )
    await db_session.commit()


async def _set_tenant_status(db_session: AsyncSession, tenant_id: UUID, status: str) -> None:
    await db_session.execute(
        text("UPDATE platform.tenants SET status = :status WHERE tenant_id = :tid"),
        {"status": status, "tid": tenant_id},
    )
    await db_session.commit()


async def _manager1_access(client: httpx.AsyncClient) -> str:
    login = await client.post(
        LOGIN, json={"username": "manager1", "password": SEED_PASSWORD}
    )
    assert login.status_code == 200
    return str(login.json()["access_token"])


# ---- 1/2. 认证语义：无凭据 / 伪造 Bearer → 401 ----


async def test_probe_without_credentials_unauthenticated(client: httpx.AsyncClient) -> None:
    resp = await client.get(PROBE)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_probe_garbage_bearer_unauthenticated(client: httpx.AsyncClient) -> None:
    resp = await client.get(PROBE, headers={"Authorization": "Bearer not.a.jwt"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


# ---- 3. API Key：RLS 生效（0 行 → 种子后 1 行） ----


async def test_probe_api_key_rls_zero_then_one(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    tenant_id = await _default_tenant_id(db_session)
    resp = await client.get(PROBE, headers={"X-API-Key": DEV_API_KEY})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0  # RLS 生效：default 租户初始无对象
    assert body["tenant_id"] == str(tenant_id)

    object_id = await _insert_probe_object(db_session, tenant_id)
    try:
        resp = await client.get(PROBE, headers={"X-API-Key": DEV_API_KEY})
        assert resp.status_code == 200
        assert resp.json()["count"] == 1
    finally:
        await _delete_probe_object(db_session, object_id)


# ---- 4. JWT：同租户可见（count=1） ----


async def test_probe_jwt_same_tenant_visible(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    tenant_id = await _default_tenant_id(db_session)
    object_id = await _insert_probe_object(db_session, tenant_id)
    try:
        access = await _manager1_access(client)
        resp = await client.get(PROBE, headers={"Authorization": f"Bearer {access}"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1  # 同租户（default）可见
        assert body["tenant_id"] == str(tenant_id)
    finally:
        await _delete_probe_object(db_session, object_id)


# ---- 5. 租户 SUSPENDED：API Key 与 JWT 均被业务路由拒（403 TENANT_SUSPENDED） ----


async def test_probe_suspended_tenant_rejected_for_both_credentials(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    tenant_id = await _default_tenant_id(db_session)
    access = await _manager1_access(client)  # ACTIVE 时先取有效 JWT
    try:
        await _set_tenant_status(db_session, tenant_id, "SUSPENDED")

        api_resp = await client.get(PROBE, headers={"X-API-Key": DEV_API_KEY})
        assert api_resp.status_code == 403
        assert api_resp.json()["error"]["code"] == "TENANT_SUSPENDED"

        jwt_resp = await client.get(PROBE, headers={"Authorization": f"Bearer {access}"})
        assert jwt_resp.status_code == 403
        assert jwt_resp.json()["error"]["code"] == "TENANT_SUSPENDED"
    finally:
        await _set_tenant_status(db_session, tenant_id, "ACTIVE")


async def test_probe_provisioning_tenant_forbidden(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """非 ACTIVE 亦非暂停态（PROVISIONING）→ 403 TENANT_FORBIDDEN。"""
    tenant_id = await _default_tenant_id(db_session)
    try:
        await _set_tenant_status(db_session, tenant_id, "PROVISIONING")
        resp = await client.get(PROBE, headers={"X-API-Key": DEV_API_KEY})
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "TENANT_FORBIDDEN"
    finally:
        await _set_tenant_status(db_session, tenant_id, "ACTIVE")


# ---- 6. RLS 死锁修复证明：edp_app 引擎下 refresh → me 往返 ----


async def test_refresh_then_me_under_app_role_engine(
    client: httpx.AsyncClient,
) -> None:
    """T9 遗留死锁：refresh/me 查 users（FORCE RLS）前未 bind → edp_app
    连接恒 0 行。修复后 refresh 从 claims.tenant_id 绑定再重查、me 按
    principal.tenant_id 绑定再查——全链 200 且 roles 正确。"""
    login = await client.post(
        LOGIN, json={"username": "manager1", "password": SEED_PASSWORD}
    )
    assert login.status_code == 200
    refresh_token = login.json()["refresh_token"]

    resp = await client.post(REFRESH, json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"access_token", "expires_in"}

    me = await client.get(ME, headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    me_body = me.json()
    assert me_body["username"] == "manager1"
    assert me_body["roles"] == ["MANAGER"]
    assert me_body["is_platform_admin"] is False


# ---- 7. 登录时序硬化：用户不存在 vs 密码错误响应时间差 < 50ms ----


async def _timed_login(client: httpx.AsyncClient, payload: dict) -> float:
    t0 = perf_counter()
    resp = await client.post(LOGIN, json=payload)
    elapsed_ms = (perf_counter() - t0) * 1000
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"
    return elapsed_ms


def _median(samples: list[float]) -> float:
    ordered = sorted(samples)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


async def test_login_timing_user_enumeration_hardened(client: httpx.AsyncClient) -> None:
    """两路径各执行恰好一次 argon2 校验：中位数时间差应显著小于单次 argon2
    校验耗时。阈值动态取 max(30ms, 0.5×t_verify)——若硬化被破坏（缺用户路径
    少跑一次 argon2），差值 ≈ t_verify 必然超阈；满载噪声由 5 样本中位数吸收。"""
    from edp_api.core.security.password import hash_password, verify_password

    # 预热：首请求含引擎连接建立/JIT 等一次性开销
    warm = await client.post(
        LOGIN, json={"username": "admin", "password": SEED_PASSWORD}
    )
    assert warm.status_code == 200

    # 实测本机单次 argon2 verify 耗时（与登录路径同一哈希器配置）
    probe_hash = hash_password("timing-probe")
    t0 = perf_counter()
    assert verify_password("timing-probe", probe_hash)
    t_verify_ms = (perf_counter() - t0) * 1000

    missing_samples = [
        await _timed_login(client, {"username": "no-such-user", "password": "x"})
        for _ in range(5)
    ]
    wrong_pw_samples = [
        await _timed_login(client, {"username": "manager1", "password": "x"})
        for _ in range(5)
    ]
    missing = _median(missing_samples)
    wrong_pw = _median(wrong_pw_samples)
    threshold = max(30.0, 0.5 * t_verify_ms)
    assert abs(missing - wrong_pw) < threshold, (
        f"timing delta {abs(missing - wrong_pw):.1f}ms >= threshold {threshold:.1f}ms "
        f"(t_verify={t_verify_ms:.1f}ms) — 用户枚举时序硬化疑似失效"
    )
