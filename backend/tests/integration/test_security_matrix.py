"""T6 越权矩阵用例集（EDP-026，CI 常驻）：主体（角色×轨道×租户）× 资源端点
全组合拒绝路径 0 泄露 + RLS 直查双保险。

EDP-026 验收：全部拒绝路径覆盖 0 泄露，用例集进 CI 常驻（随集成套件收集）。

矩阵 A——跨租户资源访问（主体 = 租户 B 的 ADMIN/MANAGER JWT；两角色均持
全部读权限码，404 只能来自 RLS）：对租户 A 显式资源 id 的六个 GET 详情
探针（tools/orders、objects、events、evidence、decisions/cases、actions）
→ 404 NOT_FOUND（error.code 精确断言，不泄露存在性）；策略面无 GET 详情
端点（T4 契约）——B ADMIN 以 no-op PATCH 作 id 寻址探针 → 404，双角色读
清单 → 200 空；
平台面 GET /tenants/{A} 的 require_platform_admin 先于存在性判定 → 403
FORBIDDEN（同为拒绝路径、0 泄露语义不变——任务卡 404 口径与实现授权顺序
的差异在此留痕）；GET /ebms/exceptions（B 身份）→ 200 但 items 为纯 B
数据，不含 A 的任何 event_id/order_no。

矩阵 B——角色不足（主体 = 租户 A 的 ANALYST，全读无写）：六个写端点 → 403
FORBIDDEN（error.code 精确）；全部拒绝后无副作用（行动/策略/案例的计数与
状态不变）。MANAGER 对 POST /admin/audit-policies → 403（audit:policy_write
仅 PA/ADMIN，0012 矩阵）。

矩阵 C——API Key 轨道：readonly-only Key（migrator 直造裁剪 Key）读 200 /
写 403 缺 scope；dev Key（readonly+write 集合，缺 write:evidence /
write:adapters）对应写端点 403，策略端点无 SERVICE scope 轨道 → Key 一律
403；SERVICE Key（非 HUMAN）做 Human-Only：A 侧行动走至 APPROVED 后 PATCH
EXECUTING → 403 GUARD_POLICY_DENIED + GUARD_DENIED 审计行
（resource_type=action.actions）且状态未变；决策记录提交同理
（resource_type=decision.records）。

RLS 直查双保险：B 租户上下文会话（edp_app + bind_tenant SET LOCAL 模式，
复用 test_tenant_isolation 的直证口径）对 A 的五张核心表 count 全 0。

会话形态：应用引擎 = conftest.app_role_engine（edp_app，FORCE RLS）；A 侧
资源经 API（manager1/admin JWT）或 demo seed；B 侧 migrator 直造（绕 RLS）。
清场：purge_tenant_business_data + demo 锚还原 + 本模块审计行/策略缓存/
临时 Key/租户 t6-matrix-b（口径同 test_actions_api/test_audit_policies）。
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.core.db import bind_tenant
from edp_api.core.security.apikey import hash_key
from edp_api.core.security.password import hash_password
from edp_api.main import create_app
from edp_api.modules.audit.aspect import install_audit_aspect
from edp_api.modules.audit_policies import service as audit_policies_service
from edp_api.modules.demo import service as demo_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

LOGIN = "/api/v1/auth/login"
CASES = "/api/v1/decisions/cases"
OBJECTS = "/api/v1/objects"
EVENTS = "/api/v1/events"
EVIDENCE = "/api/v1/evidence"
ACTIONS = "/api/v1/actions"
POLICIES = "/api/v1/admin/audit-policies"
TENANTS = "/api/v1/tenants"
EBMS_EXCEPTIONS = "/api/v1/ebms/exceptions"
SEED_PASSWORD = "Admin@123!"

DEV_KEY = "edp-dev-agent-hub-key"
DEV_HEADERS = {"X-API-Key": DEV_KEY}

# 双租户夹具：A = default（0005 种子 admin/manager1/analyst1 + demo seed）；
# B = t6-matrix-b（migrator 直造：ADMIN/MANAGER 双用户 + 各 1 对象/风险事件）
B_SLUG = "t6-matrix-b"
B_PASSWORD = "TenantB@123!"
B_USERS = {"ADMIN": "admin1b", "MANAGER": "manager1b"}
B_ROLES = ("ADMIN", "MANAGER")
B_ORDER_NO = "SO-T6-B-0001"

# 矩阵 C 的裁剪 Key（readonly-only，default 租户直插）
READONLY_KEY = "t6-matrix-readonly-key"
READONLY_PRINCIPAL = "t6-matrix-readonly"

# A 侧目标订单（demo seed 场景 2：P1 缺料，ebms order_no 口径）
A_ORDER_NO = "SO-2026-00123"

CROSS_READ_ENDPOINTS = (
    "tools-order",
    "object",
    "event",
    "evidence",
    "case",
    "action",
)


@dataclass
class MatrixWorld:
    """双租户矩阵夹具（每测试独立重建；A 侧行动/策略经 API 创建）。"""

    tenant_a: UUID
    tenant_b: UUID
    order_no: str  # A 订单号（seed）
    object_id: str  # A ORDER 对象 id（seed）
    event_id: str  # A 风险事件 id（seed 案例源事件）
    evidence_id: str  # A 证据 id（seed）
    case_id: str  # A 案例 id（seed DEMO_CASE）
    action_id: str  # A 行动 id（manager1 经 API 创建，PROPOSED）
    policy_id: str  # A 审计策略 id（admin 经 API 创建，ACTIVE）
    b_event_id: str  # B 风险事件 id（直插，ebms 纯 B 数据对照）

    def read_probe(self, endpoint: str) -> tuple[str, str, dict[str, Any] | None]:
        """矩阵 A 资源探针 key → (method, url, payload)。

        audit-policy 无 GET 详情端点（T4 契约仅 POST/列表/PATCH/DELETE），且
        audit:policy_write 仅 PA/ADMIN——id 寻址 PATCH 探针（no-op 值，隔离
        失效时亦无实效写）限定 B ADMIN（过权限关后 404 只能来自 RLS）；B
        MANAGER 经清单读（audit:policy_read）断言空。
        """
        probes: dict[str, tuple[str, str, dict[str, Any] | None]] = {
            "tools-order": ("GET", f"/api/v1/tools/orders/{self.order_no}", None),
            "object": ("GET", f"{OBJECTS}/{self.object_id}", None),
            "event": ("GET", f"{EVENTS}/{self.event_id}", None),
            "evidence": ("GET", f"{EVIDENCE}/{self.evidence_id}", None),
            "case": ("GET", f"{CASES}/{self.case_id}", None),
            "action": ("GET", f"{ACTIONS}/{self.action_id}", None),
            "audit-policy": ("PATCH", f"{POLICIES}/{self.policy_id}", {"status": "ACTIVE"}),
        }
        return probes[endpoint]


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS），全路由随
    create_app 装配（含 GUARD_DENIED 独立会话路径）。"""
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
    """ORM 写（行动/证据/策略等）依赖切面落审计——与 create_app 同一装配。"""
    install_audit_aspect()


@pytest.fixture
async def demo(
    app_role_engine: AsyncEngine, default_tenant_id: UUID
) -> demo_service.SeedStats:
    """default 租户演示数据集（订单/对象/风险事件/证据/DEMO_CASE）；清场见
    _clean_matrix_rows。"""
    stats = await demo_service.seed(app_role_engine, default_tenant_id)
    assert stats.failed == 0
    return stats


@pytest.fixture(autouse=True)
async def _clean_matrix_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    """每测试后清场：default 业务行（seed 全量）+ demo 锚还原（口径同
    test_actions_api，残留会污染 test_demo_seed 首跑整点断言）+ 本模块审计
    行/策略行与进程内缓存/临时 Key + 租户 t6-matrix-b 全量痕迹。"""
    yield
    await demo_service.purge_tenant_business_data(db_session, default_tenant_id)
    await db_session.execute(
        text(
            "UPDATE platform.tenants SET attributes = attributes - 'demo_seed'"
            " WHERE tenant_id = :t"
        ),
        {"t": default_tenant_id},
    )
    actors = (
        await db_session.execute(
            text(
                "SELECT user_id::text FROM platform.users"
                " WHERE username IN ('admin', 'manager1', 'analyst1')"
            )
        )
    ).scalars().all()
    marks = ", ".join(["'agent-hub'", ":ro"] + [f":a{i}" for i in range(len(actors))])
    await db_session.execute(
        text(
            "DELETE FROM platform.audit_logs WHERE tenant_id = :t"
            " AND (actor_id IN (" + marks + ")"
            " OR (action = 'GUARD_DENIED' AND resource_type IN"
            " ('decision.records', 'action.actions')))"
        ),
        {
            "t": default_tenant_id,
            "ro": READONLY_PRINCIPAL,
            **{f"a{i}": actor for i, actor in enumerate(actors)},
        },
    )
    await db_session.execute(
        text("DELETE FROM audit.policies WHERE tenant_id = :t"),
        {"t": default_tenant_id},
    )
    # 进程内 ACTIVE 策略缓存清空（DB 直删不经写路径失效；单副本语义）
    audit_policies_service._ACTIVE_POLICIES.clear()
    await db_session.execute(
        text("DELETE FROM platform.api_keys WHERE principal_id = :ro"),
        {"ro": READONLY_PRINCIPAL},
    )
    b_ids = "SELECT tenant_id FROM platform.tenants WHERE slug = 't6-matrix-b'"
    await db_session.execute(
        text("DELETE FROM event.outbox WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM event.events WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM platform.idempotency_keys WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM master.business_objects WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM platform.api_keys WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM platform.tenant_members WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM platform.users WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM platform.tenant_usage_daily WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(text("DELETE FROM platform.tenants WHERE slug = 't6-matrix-b'"))
    await db_session.commit()


@pytest.fixture
async def world(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> MatrixWorld:
    """矩阵世界：B 租户（ADMIN/MANAGER 双用户 + 1 对象/风险事件，migrator
    直造）；A 侧 seed 资源 id 直查 + 行动/策略经 API 创建。"""
    tenant_a = default_tenant_id
    tenant_b = uuid4()
    b_object, b_event = uuid4(), uuid4()

    await db_session.execute(
        text(
            "INSERT INTO platform.tenants (tenant_id, slug, name, status)"
            " VALUES (:t, :slug, '租户T6矩阵B', 'ACTIVE')"
        ),
        {"t": tenant_b, "slug": B_SLUG},
    )
    for username, display, role in (
        ("admin1b", "B租户管理员", "ADMIN"),
        ("manager1b", "B租户经理", "MANAGER"),
    ):
        user_b, member_b = uuid4(), uuid4()
        await db_session.execute(
            text(
                "INSERT INTO platform.users"
                " (user_id, tenant_id, username, email, password_hash, display_name,"
                "  principal_type, is_platform_admin, status)"
                " VALUES (:u, :t, :username, :email, :pw, :display, 'HUMAN', FALSE,"
                "         'ACTIVE')"
            ),
            {
                "u": user_b,
                "t": tenant_b,
                "username": username,
                "email": f"{username}@t6-matrix-b.local",
                "pw": hash_password(B_PASSWORD),
                "display": display,
            },
        )
        await db_session.execute(
            text(
                "INSERT INTO platform.tenant_members"
                " (member_id, tenant_id, user_id, member_roles, status)"
                " VALUES (:m, :t, :u, CAST(:roles AS text[]), 'ACTIVE')"
            ),
            {"m": member_b, "t": tenant_b, "u": user_b, "roles": [role]},
        )
    await db_session.execute(
        text(
            "INSERT INTO master.business_objects"
            " (object_id, tenant_id, object_type, owner_domain, source_system,"
            "  source_id)"
            " VALUES (:o, :t, 'ORDER', 'sales', 't6b-src', :so)"
        ),
        {"o": b_object, "t": tenant_b, "so": B_ORDER_NO},
    )
    await db_session.execute(
        text(
            "INSERT INTO event.events"
            " (event_id, tenant_id, event_type, object_id, source_system,"
            "  risk_level, occurred_at, data)"
            " VALUES (:e, :t, 't6.matrix.b.risk', :o, 't6b-src', 'P2', now(),"
            "         CAST(:data AS JSONB))"
        ),
        {
            "e": b_event,
            "t": tenant_b,
            "o": b_object,
            "data": '{"order_no": "' + B_ORDER_NO + '"}',
        },
    )
    await db_session.commit()

    object_id = (
        await db_session.execute(
            text(
                "SELECT object_id FROM master.business_objects"
                " WHERE tenant_id = :t AND object_type = 'ORDER' AND source_id = :so"
            ),
            {"t": tenant_a, "so": A_ORDER_NO},
        )
    ).scalar_one()
    event_id = (
        await db_session.execute(
            text("SELECT source_id FROM decision.cases WHERE tenant_id = :t"),
            {"t": tenant_a},
        )
    ).scalar_one()
    evidence_id = (
        await db_session.execute(
            text(
                "SELECT evidence_id FROM evidence.records WHERE tenant_id = :t"
                " ORDER BY captured_at DESC LIMIT 1"
            ),
            {"t": tenant_a},
        )
    ).scalar_one()
    case_id = (
        await db_session.execute(
            text("SELECT case_id FROM decision.cases WHERE tenant_id = :t"),
            {"t": tenant_a},
        )
    ).scalar_one()

    manager = await _login(client, "manager1")
    action = await client.post(
        ACTIONS,
        headers=manager,
        json={"title": "T6-矩阵行动", "action_type": "MITIGATION"},
    )
    assert action.status_code == 201, action.text
    admin = await _login(client, "admin")
    policy = await client.post(
        POLICIES,
        headers=admin,
        json={"name": "T6-矩阵策略", "resource_types": ["audit.policies"]},
    )
    assert policy.status_code == 201, policy.text

    return MatrixWorld(
        tenant_a=tenant_a,
        tenant_b=tenant_b,
        order_no=A_ORDER_NO,
        object_id=str(object_id),
        event_id=str(event_id),
        evidence_id=str(evidence_id),
        case_id=str(case_id),
        action_id=action.json()["action_id"],
        policy_id=policy.json()["policy_id"],
        b_event_id=str(b_event),
    )


# ---- 造数与登录辅助 ----


async def _login(client: httpx.AsyncClient, username: str) -> dict[str, str]:
    resp = await client.post(
        LOGIN, json={"username": username, "password": SEED_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _login_b(client: httpx.AsyncClient, role: str) -> dict[str, str]:
    """B 租户 JWT 登录（role ∈ ADMIN/MANAGER，经 tenant_slug 指定）。"""
    resp = await client.post(
        LOGIN,
        json={
            "username": B_USERS[role],
            "password": B_PASSWORD,
            "tenant_slug": B_SLUG,
        },
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _insert_api_key(
    db_session: AsyncSession,
    tenant_id: UUID,
    *,
    key: str,
    principal_id: str,
    scopes: list[str],
) -> None:
    """直插临时 API Key（照 test_actions_api 模式；hash_key 与生产同实现）。"""
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


def _write_target(world: MatrixWorld, endpoint: str) -> tuple[str, str, dict[str, Any]]:
    """矩阵 B/C 写端点 key → (method, path, payload)；403 均先于业务校验。"""
    return {
        "decision-record": (
            "POST",
            f"{CASES}/{world.case_id}/records",
            {"chosen_option": "EXPEDITE"},
        ),
        "action-create": (
            "POST",
            ACTIONS,
            {"title": "T6-越权行动", "action_type": "MITIGATION"},
        ),
        "action-transition": (
            "PATCH",
            f"{ACTIONS}/{world.action_id}/status",
            {"from_status": "PROPOSED", "to_status": "ASSIGNED"},
        ),
        "policy-create": ("POST", POLICIES, {"name": "T6-越权策略"}),
        "policy-update": (
            "PATCH",
            f"{POLICIES}/{world.policy_id}",
            {"status": "DISABLED"},
        ),
        "adapter-sync": (
            "POST",
            "/api/v1/admin/adapters/erp-demo/sync",
            {"mode": "full"},
        ),
        "evidence-create": (
            "POST",
            EVIDENCE,
            {
                "source_system": "t6-src",
                "source_record_id": "t6-evidence-1",
                "object_id": world.object_id,
                "snapshot": {"who": "t6"},
                "captured_at": "2026-09-18T09:00:00Z",
            },
        ),
        "event-batch": (
            "POST",
            f"{EVENTS}/batch",
            {
                "events": [
                    {
                        "event_type": "t6.matrix.key",
                        "object_id": world.object_id,
                        "source_system": "t6-src",
                        "occurred_at": "2026-09-18T09:00:00Z",
                    }
                ]
            },
        ),
    }[endpoint]


# ---- 矩阵 A：跨租户资源访问（B 的 ADMIN/MANAGER → A 显式资源 id） ----


@pytest.mark.parametrize("role", B_ROLES)
@pytest.mark.parametrize("endpoint", CROSS_READ_ENDPOINTS)
async def test_cross_tenant_read_unified_404(
    role: str, endpoint: str, world: MatrixWorld, client: httpx.AsyncClient
) -> None:
    """六个 GET 详情探针对 A 显式资源 id 统一 404 NOT_FOUND（两角色均持
    对应读权限码，404 只能来自 RLS；error.code 精确断言，不泄露存在性）。"""
    headers = await _login_b(client, role)
    method, url, payload = world.read_probe(endpoint)
    resp = await client.request(method, url, json=payload, headers=headers)
    assert resp.status_code == 404, f"{role}×{endpoint}: {resp.text}"
    assert resp.json()["error"]["code"] == "NOT_FOUND"


async def test_cross_tenant_audit_policy_admin_probe_404(
    world: MatrixWorld, client: httpx.AsyncClient
) -> None:
    """策略 id 寻址探针（B ADMIN——唯一过 audit:policy_write 权限关的 B
    角色）：PATCH no-op 值对 A 策略 → 404 只能来自 RLS（404 语义与
    test_audit_policies 跨租户用例一致）。"""
    headers = await _login_b(client, "ADMIN")
    method, url, payload = world.read_probe("audit-policy")
    resp = await client.request(method, url, json=payload, headers=headers)
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize("role", B_ROLES)
async def test_cross_tenant_audit_policy_list_empty(
    role: str, world: MatrixWorld, client: httpx.AsyncClient
) -> None:
    """B 双角色（audit:policy_read 均持有）读策略清单 → 200 且不含 A 策略。"""
    headers = await _login_b(client, role)
    resp = await client.get(POLICIES, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []


@pytest.mark.parametrize("role", B_ROLES)
async def test_cross_tenant_platform_endpoint_forbidden(
    role: str, world: MatrixWorld, client: httpx.AsyncClient
) -> None:
    """平台面 GET /tenants/{A}：require_platform_admin 先于存在性 → 403
    FORBIDDEN（B 的 ADMIN/MANAGER 均非平台管理员；同为拒绝路径 0 泄露）。"""
    headers = await _login_b(client, role)
    resp = await client.get(f"{TENANTS}/{world.tenant_a}", headers=headers)
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize("role", B_ROLES)
async def test_cross_tenant_ebms_exceptions_pure_b(
    role: str, world: MatrixWorld, client: httpx.AsyncClient
) -> None:
    """GET /ebms/exceptions（B 身份）→ 200 但 items 恰为 B 自己的风险事件，
    不含 A 的任何 event_id/order_no（列表过滤而非 404 语义）。"""
    headers = await _login_b(client, role)
    resp = await client.get(EBMS_EXCEPTIONS, headers=headers)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert [item["event_id"] for item in items] == [world.b_event_id]
    assert all(item["event_id"] != world.event_id for item in items)
    assert all(item["order_no"] != world.order_no for item in items)


# ---- 矩阵 B：角色不足（A 的 ANALYST 写 / MANAGER 策略写） ----


ANALYST_WRITE_ENDPOINTS = (
    "decision-record",
    "action-create",
    "action-transition",
    "policy-create",
    "policy-update",
    "adapter-sync",
)


@pytest.mark.parametrize("endpoint", ANALYST_WRITE_ENDPOINTS)
async def test_analyst_write_forbidden(
    endpoint: str, world: MatrixWorld, client: httpx.AsyncClient
) -> None:
    """ANALYST（全读无写）对六个写端点 → 403 FORBIDDEN（error.code 精确）。"""
    analyst = await _login(client, "analyst1")
    method, path, payload = _write_target(world, endpoint)
    resp = await client.request(method, path, json=payload, headers=analyst)
    assert resp.status_code == 403, f"analyst×{endpoint}: {resp.text}"
    assert resp.json()["error"]["code"] == "FORBIDDEN"


async def test_manager_policy_create_forbidden(
    world: MatrixWorld, client: httpx.AsyncClient
) -> None:
    """MANAGER 对 POST /admin/audit-policies → 403（audit:policy_write 仅
    PA/ADMIN，0012 矩阵）。"""
    manager = await _login(client, "manager1")
    resp = await client.post(
        POLICIES, json={"name": "T6-MANAGER策略"}, headers=manager
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"


async def test_denied_writes_leave_no_side_effects(
    world: MatrixWorld,
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    """全部越权写拒绝后零副作用：行动/策略计数与状态、案例状态均不变。"""
    analyst = await _login(client, "analyst1")
    for endpoint in ANALYST_WRITE_ENDPOINTS:
        method, path, payload = _write_target(world, endpoint)
        resp = await client.request(method, path, json=payload, headers=analyst)
        assert resp.status_code == 403, f"analyst×{endpoint}: {resp.text}"
    manager = await _login(client, "manager1")
    denied = await client.post(
        POLICIES, json={"name": "T6-MANAGER策略"}, headers=manager
    )
    assert denied.status_code == 403, denied.text

    row = (
        await db_session.execute(
            text(
                "SELECT (SELECT count(*) FROM action.actions WHERE tenant_id = :t)"
                " AS action_count,"
                " (SELECT status FROM action.actions WHERE action_id = :aid)"
                " AS action_status,"
                " (SELECT status FROM decision.cases WHERE case_id = :cid)"
                " AS case_status,"
                " (SELECT count(*) FROM audit.policies WHERE tenant_id = :t)"
                " AS policy_count,"
                " (SELECT status FROM audit.policies WHERE policy_id = :pid)"
                " AS policy_status"
            ),
            {
                "t": default_tenant_id,
                "aid": world.action_id,
                "cid": world.case_id,
                "pid": world.policy_id,
            },
        )
    ).one()
    assert row.action_count == 1
    assert row.action_status == "PROPOSED"
    assert row.case_status == "OPEN"
    assert row.policy_count == 1
    assert row.policy_status == "ACTIVE"


# ---- 矩阵 C：API Key 轨道（readonly 裁剪 Key / dev Key / Human-Only） ----


READONLY_KEY_WRITE_ENDPOINTS = ("action-create", "evidence-create", "event-batch")
DEV_KEY_WRITE_ENDPOINTS = ("evidence-create", "adapter-sync", "policy-create")


async def test_readonly_key_read_ok(
    world: MatrixWorld,
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    """readonly-only Key 读轨道 200（A 侧行动可见）——写拒绝的对照组。"""
    await _insert_api_key(
        db_session,
        default_tenant_id,
        key=READONLY_KEY,
        principal_id=READONLY_PRINCIPAL,
        scopes=["readonly"],
    )
    resp = await client.get(ACTIONS, headers={"X-API-Key": READONLY_KEY})
    assert resp.status_code == 200, resp.text
    assert [item["action_id"] for item in resp.json()["items"]] == [world.action_id]


@pytest.mark.parametrize("endpoint", READONLY_KEY_WRITE_ENDPOINTS)
async def test_readonly_key_write_forbidden(
    endpoint: str,
    world: MatrixWorld,
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    """readonly-only Key 对写端点 → 403 缺 write scope（403 先于幂等键校验）。"""
    await _insert_api_key(
        db_session,
        default_tenant_id,
        key=READONLY_KEY,
        principal_id=READONLY_PRINCIPAL,
        scopes=["readonly"],
    )
    method, path, payload = _write_target(world, endpoint)
    resp = await client.request(
        method, path, json=payload, headers={"X-API-Key": READONLY_KEY}
    )
    assert resp.status_code == 403, f"readonly-key×{endpoint}: {resp.text}"
    assert resp.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize("endpoint", DEV_KEY_WRITE_ENDPOINTS)
async def test_dev_key_missing_scope_write_forbidden(
    endpoint: str, world: MatrixWorld, client: httpx.AsyncClient
) -> None:
    """dev Key（readonly+write 集合）对缺 scope 的写端点 → 403：缺
    write:evidence / write:adapters；策略端点无 SERVICE scope 轨道（仅人工
    管理）→ Key 一律 403。"""
    method, path, payload = _write_target(world, endpoint)
    resp = await client.request(method, path, json=payload, headers=DEV_HEADERS)
    assert resp.status_code == 403, f"dev-key×{endpoint}: {resp.text}"
    assert resp.json()["error"]["code"] == "FORBIDDEN"


async def test_service_key_human_only_action_transition(
    world: MatrixWorld, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """SERVICE Key 做 Human-Only 转移：A 侧行动走至 APPROVED（非 Human-Only
    步 SERVICE 可做）后 PATCH EXECUTING → 403 GUARD_POLICY_DENIED +
    GUARD_DENIED 审计行（resource_type=action.actions）且状态未变。"""
    for from_status, to_status in (
        ("PROPOSED", "ASSIGNED"),
        ("ASSIGNED", "ACCEPTED"),
        ("ACCEPTED", "APPROVED"),
    ):
        resp = await client.patch(
            f"{ACTIONS}/{world.action_id}/status",
            headers=DEV_HEADERS,
            json={"from_status": from_status, "to_status": to_status},
        )
        assert resp.status_code == 200, resp.text

    denied = await client.patch(
        f"{ACTIONS}/{world.action_id}/status",
        headers=DEV_HEADERS,
        json={"from_status": "APPROVED", "to_status": "EXECUTING"},
    )
    assert denied.status_code == 403, denied.text
    error = denied.json()["error"]
    assert error["code"] == "GUARD_POLICY_DENIED"
    assert error["message"] == "该操作仅限人工执行"

    guard_count = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM platform.audit_logs"
                " WHERE action = 'GUARD_DENIED' AND resource_type = 'action.actions'"
                " AND resource_id = :rid AND actor_id = 'agent-hub'"
            ),
            {"rid": world.action_id},
        )
    ).scalar_one()
    assert guard_count == 1

    detail = await client.get(f"{ACTIONS}/{world.action_id}", headers=DEV_HEADERS)
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "APPROVED"  # 守卫先于写


async def test_service_key_human_only_decision_record(
    world: MatrixWorld, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """SERVICE Key 提交决策记录（Human-Only）→ 403 GUARD_POLICY_DENIED +
    GUARD_DENIED 审计行（resource_type=decision.records），案例仍 OPEN。"""
    denied = await client.post(
        f"{CASES}/{world.case_id}/records",
        headers=DEV_HEADERS,
        json={"chosen_option": "EXPEDITE"},
    )
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "GUARD_POLICY_DENIED"

    guard_count = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM platform.audit_logs"
                " WHERE action = 'GUARD_DENIED' AND resource_type = 'decision.records'"
                " AND resource_id = :rid AND actor_id = 'agent-hub'"
            ),
            {"rid": world.case_id},
        )
    ).scalar_one()
    assert guard_count == 1

    detail = await client.get(f"{CASES}/{world.case_id}", headers=DEV_HEADERS)
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "OPEN"


# ---- RLS 直查双保险：B 租户上下文会话对 A 五表 count 全 0 ----


RLS_TABLES: tuple[tuple[str, str], ...] = (
    ("event.events", "SELECT count(*) FROM event.events WHERE tenant_id = :a"),
    (
        "evidence.records",
        "SELECT count(*) FROM evidence.records WHERE tenant_id = :a",
    ),
    ("decision.cases", "SELECT count(*) FROM decision.cases WHERE tenant_id = :a"),
    ("action.actions", "SELECT count(*) FROM action.actions WHERE tenant_id = :a"),
    ("audit.policies", "SELECT count(*) FROM audit.policies WHERE tenant_id = :a"),
)


@pytest.mark.parametrize(("table", "sql"), RLS_TABLES, ids=[t for t, _ in RLS_TABLES])
async def test_rls_direct_query_zero_leak(
    table: str, sql: str, world: MatrixWorld, app_session: AsyncSession
) -> None:
    """edp_app 会话绑定 B 后直查 A 的行 → 全 0（API 层 404 之外的数据面
    直证；SET LOCAL 模式复用 test_tenant_isolation 口径）。"""
    await bind_tenant(app_session, world.tenant_b)
    count = (
        await app_session.execute(text(sql), {"a": world.tenant_a})
    ).scalar_one()
    assert count == 0, f"{table}: B 会话可见 A 行"
