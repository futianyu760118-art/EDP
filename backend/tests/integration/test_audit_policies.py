"""T4 审计策略集成测试（EDP-032 最小版）：CRUD + 角色矩阵 + 跨租户 + 命中打标。

- CRUD：创建 201（三维数组缺省 [] / status ACTIVE）/ 重名 409 / 局部更新
  （启停 DISABLE）/ 列表 status 过滤 / 删除 204→404；
- 角色矩阵（0012）：audit:policy_read → PA/ADMIN/MANAGER/ANALYST、
  audit:policy_write → 仅 PA/ADMIN——ANALYST 读 200 写 403、MANAGER 写 403、
  ADMIN 写 201；
- 跨租户：tenant-b 直造 ADMIN 用户（过权限关后验 RLS）PATCH/DELETE 统一
  404、清单空；
- 命中打标（audit.aspect 写审计行前 matching 三维匹配）：
  ①fullname 资源策略（['decision.records']）命中决策记录写（DECISION_CREATE
    行 detail.policy_hits 含策略 id）；
  ②action 维通配策略（['ACTION_*']）命中行动创建；
  ③actor 维不匹配（['AI'] vs HUMAN 操作者）不命中；
  ④PATCH DISABLE 后再触发不命中（写路径缓存失效直证）；
  ⑤无策略租户审计行无 policy_hits 键。

收尾清场：audit.policies 全清 + 进程内 ACTIVE 缓存清空（单副本语义，
DB 直删不经写路径失效）+ 本模块痕迹（T4-% 案例/决策记录/行动与对应
审计行、tenant-b）。
"""

from typing import Any
from uuid import uuid4

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.core.security.password import hash_password
from edp_api.main import create_app
from edp_api.modules.audit_policies import service as audit_policies_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

POLICIES = "/api/v1/admin/audit-policies"
CASES = "/api/v1/decisions/cases"
ACTIONS = "/api/v1/actions"
LOGIN = "/api/v1/auth/login"
SEED_PASSWORD = "Admin@123!"

B_PASSWORD = "TenantB@123!"
B_SLUG = "tenant-b"


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS），audit_policies
    路由与审计切面（含命中打标）随 create_app 装配。"""
    await core_db.dispose_engine()
    monkeypatch.setattr(core_db, "get_engine", lambda: app_role_engine)
    transport = httpx.ASGITransport(app=create_app())
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        await core_db.dispose_engine()  # 重置绑定到测试引擎的会话工厂


@pytest.fixture(autouse=True)
async def _clean_policy_rows(db_session: AsyncSession) -> None:
    """每测试后清场：本模块全部痕迹（策略 + 缓存 + T4-% 业务行与审计行 +
    tenant-b），保证用例间独立（migrator 绕 RLS；audit_logs 仅追加约束只
    作用于 edp_app，migrator 不受限）。"""
    yield
    # 进程内 ACTIVE 策略缓存清空（DB 直删不经写路径失效；单副本语义）
    audit_policies_service._ACTIVE_POLICIES.clear()
    # 审计行先清（引用下方业务行的 resource_id 子查询）
    await db_session.execute(
        text(
            """
            DELETE FROM platform.audit_logs WHERE
                action LIKE 'POLICY_%'
                OR detail->'policy_hits' IS NOT NULL
                OR resource_id IN (
                    SELECT case_id::text FROM decision.cases
                    WHERE question LIKE 'T4-%')
                OR resource_id IN (
                    SELECT decision_id::text FROM decision.records r
                    JOIN decision.cases c ON c.case_id = r.case_id
                    WHERE c.question LIKE 'T4-%')
                OR resource_id IN (
                    SELECT action_id::text FROM action.actions
                    WHERE title LIKE 'T4-%')
                OR tenant_id IN (
                    SELECT tenant_id FROM platform.tenants WHERE slug = :b_slug)
            """
        ),
        {"b_slug": B_SLUG},
    )
    await db_session.execute(
        text(
            "DELETE FROM decision.records WHERE case_id IN"
            " (SELECT case_id FROM decision.cases WHERE question LIKE 'T4-%')"
        )
    )
    await db_session.execute(text("DELETE FROM action.actions WHERE title LIKE 'T4-%'"))
    await db_session.execute(
        text("DELETE FROM decision.cases WHERE question LIKE 'T4-%'")
    )
    await db_session.execute(text("DELETE FROM audit.policies"))
    b_ids = "SELECT tenant_id FROM platform.tenants WHERE slug = 'tenant-b'"
    await db_session.execute(
        text("DELETE FROM platform.api_keys WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM platform.tenant_members WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM platform.users WHERE tenant_id IN (" + b_ids + ")")
    )
    # B 侧经 API 的请求会累加 tenant_usage_daily（FK 引用 tenants）
    await db_session.execute(
        text("DELETE FROM platform.tenant_usage_daily WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(text("DELETE FROM platform.tenants WHERE slug = :s"), {"s": B_SLUG})
    await db_session.commit()


async def _login(
    client: httpx.AsyncClient, username: str, tenant_slug: str | None = None
) -> dict[str, str]:
    """JWT 登录 → Authorization headers（跨租户用例经 tenant_slug 指定 B）。"""
    payload: dict[str, str] = {"username": username, "password": SEED_PASSWORD}
    if tenant_slug is not None:
        payload["tenant_slug"] = tenant_slug
        payload["password"] = B_PASSWORD
    resp = await client.post(LOGIN, json=payload)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _create_policy(
    client: httpx.AsyncClient, headers: dict[str, str], payload: dict[str, Any]
) -> httpx.Response:
    return await client.post(POLICIES, json=payload, headers=headers)


async def _create_action(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    """触发一次行动创建（manager1：action:execute）→ 返回 action_id。"""
    resp = await client.post(
        ACTIONS,
        json={"title": "T4-行动任务", "action_type": "MITIGATION"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["action_id"])


async def _audit_detail(
    db_session: AsyncSession, *, action: str, resource_id: str
) -> dict:
    """最新一条 (action, resource_id) 审计行的 detail。"""
    row = (
        await db_session.execute(
            text(
                "SELECT detail FROM platform.audit_logs"
                " WHERE action = :action AND resource_id = :rid"
                " ORDER BY audit_id DESC LIMIT 1"
            ),
            {"action": action, "rid": resource_id},
        )
    ).scalar_one()
    return row


# ---- 1. CRUD：创建默认值 / 重名 409 / 局部更新启停 / status 过滤 / 删除 ----


async def test_policy_crud_lifecycle(client: httpx.AsyncClient) -> None:
    admin = await _login(client, "admin")
    created = await _create_policy(
        client, admin, {"name": "T4-基础策略", "description": "首轮"}
    )
    assert created.status_code == 201, created.text
    body = created.json()
    policy_id = body["policy_id"]
    assert body["name"] == "T4-基础策略"
    assert body["status"] == "ACTIVE"
    assert body["resource_types"] == []
    assert body["actions"] == []
    assert body["actor_types"] == []
    assert body["notify_channel"] is None
    assert body["created_at"] and body["updated_at"]

    # 租户内重名 → 409 CONFLICT
    duplicate = await _create_policy(client, admin, {"name": "T4-基础策略"})
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["error"]["code"] == "CONFLICT"

    # 局部更新：启停 + description（name/三维数组不动）
    patched = await client.patch(
        f"{POLICIES}/{policy_id}",
        json={"status": "DISABLED", "description": "停用"},
        headers=admin,
    )
    assert patched.status_code == 200, patched.text
    updated = patched.json()
    assert updated["status"] == "DISABLED"
    assert updated["description"] == "停用"
    assert updated["name"] == "T4-基础策略"
    assert updated["actions"] == []

    # 列表 status 过滤
    active = await client.get(POLICIES, params={"status": "ACTIVE"}, headers=admin)
    assert active.status_code == 200, active.text
    assert all(item["status"] == "ACTIVE" for item in active.json()["items"])
    assert policy_id not in {
        item["policy_id"] for item in active.json()["items"]
    }
    disabled = await client.get(POLICIES, params={"status": "DISABLED"}, headers=admin)
    assert disabled.status_code == 200, disabled.text
    assert {item["policy_id"] for item in disabled.json()["items"]} == {policy_id}

    # 删除 204 → 再删/PATCH 404
    deleted = await client.delete(f"{POLICIES}/{policy_id}", headers=admin)
    assert deleted.status_code == 204
    assert (await client.delete(f"{POLICIES}/{policy_id}", headers=admin)).status_code == 404
    gone = await client.patch(
        f"{POLICIES}/{policy_id}", json={"status": "ACTIVE"}, headers=admin
    )
    assert gone.status_code == 404
    assert gone.json()["error"]["code"] == "NOT_FOUND"


# ---- 2. 角色矩阵：ANALYST 读 200 写 403 / MANAGER 写 403（0012 矩阵） ----


async def test_role_matrix_read_write(client: httpx.AsyncClient) -> None:
    analyst = await _login(client, "analyst1")
    manager = await _login(client, "manager1")
    admin = await _login(client, "admin")

    read = await client.get(POLICIES, headers=analyst)
    assert read.status_code == 200, read.text

    denied = await _create_policy(client, analyst, {"name": "T4-越权策略"})
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "FORBIDDEN"

    manager_denied = await _create_policy(client, manager, {"name": "T4-越权策略"})
    assert manager_denied.status_code == 403, manager_denied.text
    assert manager_denied.json()["error"]["code"] == "FORBIDDEN"

    allowed = await _create_policy(client, admin, {"name": "T4-管理员策略"})
    assert allowed.status_code == 201, allowed.text


# ---- 3. 跨租户：tenant-b ADMIN（过权限关）PATCH/DELETE 统一 404、清单空 ----


async def test_cross_tenant_unified_404(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _login(client, "admin")
    created = await _create_policy(client, admin, {"name": "T4-跨租户策略"})
    assert created.status_code == 201, created.text
    policy_id = created.json()["policy_id"]

    # tenant-b 直造 ADMIN 用户（migrator 绕 RLS）——权限关通过后 404 只能来自 RLS
    tenant_b, user_b, member_b = (uuid4() for _ in range(3))
    await db_session.execute(
        text(
            "INSERT INTO platform.tenants (tenant_id, slug, name, status)"
            " VALUES (:t, 'tenant-b', '租户B', 'ACTIVE')"
        ),
        {"t": tenant_b},
    )
    await db_session.execute(
        text(
            "INSERT INTO platform.users"
            " (user_id, tenant_id, username, email, password_hash, display_name,"
            "  principal_type, is_platform_admin, status)"
            " VALUES (:u, :t, 'member1b', 'member1b@tenant-b.local', :pw,"
            "         'B租户管理员', 'HUMAN', FALSE, 'ACTIVE')"
        ),
        {"u": user_b, "t": tenant_b, "pw": hash_password(B_PASSWORD)},
    )
    await db_session.execute(
        text(
            "INSERT INTO platform.tenant_members"
            " (member_id, tenant_id, user_id, member_roles, status)"
            " VALUES (:m, :t, :u, ARRAY['ADMIN'], 'ACTIVE')"
        ),
        {"m": member_b, "t": tenant_b, "u": user_b},
    )
    await db_session.commit()

    b_admin = await _login(client, "member1b", tenant_slug=B_SLUG)
    patched = await client.patch(
        f"{POLICIES}/{policy_id}", json={"status": "DISABLED"}, headers=b_admin
    )
    assert patched.status_code == 404, patched.text
    assert patched.json()["error"]["code"] == "NOT_FOUND"
    deleted = await client.delete(f"{POLICIES}/{policy_id}", headers=b_admin)
    assert deleted.status_code == 404, deleted.text
    listed = await client.get(POLICIES, headers=b_admin)
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"] == []


# ---- 4. 命中打标：fullname 资源策略命中决策记录写 ----


async def test_hit_fullname_resource_policy(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _login(client, "admin")
    created = await _create_policy(
        client, admin, {"name": "T4-决策记录策略", "resource_types": ["decision.records"]}
    )
    assert created.status_code == 201, created.text
    policy_id = created.json()["policy_id"]

    manager = await _login(client, "manager1")
    case = await client.post(
        CASES,
        json={
            "question": "T4-策略打标案例",
            "options": [
                {"key": "yes", "label": "同意"},
                {"key": "no", "label": "驳回"},
            ],
            "risk_level": "P2",
        },
        headers=manager,
    )
    assert case.status_code == 201, case.text
    case_id = case.json()["case_id"]
    record = await client.post(
        f"{CASES}/{case_id}/records", json={"chosen_option": "yes"}, headers=manager
    )
    assert record.status_code == 201, record.text
    decision_id = str(record.json()["decision_id"])

    # DECISION_CREATE 行（fullname=decision.records）命中；CASE_CREATE 行不命中
    hit = await _audit_detail(db_session, action="DECISION_CREATE", resource_id=decision_id)
    assert hit["policy_hits"] == [str(policy_id)]
    miss = await _audit_detail(db_session, action="CASE_CREATE", resource_id=str(case_id))
    assert "policy_hits" not in miss


# ---- 5. 命中打标：action 维通配（ACTION_*）命中行动创建 ----


async def test_hit_action_wildcard_policy(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _login(client, "admin")
    created = await _create_policy(
        client, admin, {"name": "T4-行动通配策略", "actions": ["ACTION_*"]}
    )
    assert created.status_code == 201, created.text
    policy_id = created.json()["policy_id"]

    manager = await _login(client, "manager1")
    action_id = await _create_action(client, manager)
    detail = await _audit_detail(
        db_session, action="ACTION_CREATE", resource_id=action_id
    )
    assert detail["policy_hits"] == [str(policy_id)]


# ---- 6. 不匹配维度：actor_types=['AI'] 但操作者 HUMAN → 不命中 ----


async def test_no_hit_actor_mismatch(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _login(client, "admin")
    created = await _create_policy(
        client, admin, {"name": "T4-AI策略", "actor_types": ["AI"]}
    )
    assert created.status_code == 201, created.text

    manager = await _login(client, "manager1")  # HUMAN
    action_id = await _create_action(client, manager)
    detail = await _audit_detail(
        db_session, action="ACTION_CREATE", resource_id=action_id
    )
    assert "policy_hits" not in detail


# ---- 7. PATCH DISABLE 缓存失效：先命中 → 停用 → 再触发不命中 ----


async def test_disable_invalidates_cache(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _login(client, "admin")
    created = await _create_policy(
        client, admin, {"name": "T4-停用策略", "actions": ["ACTION_*"]}
    )
    policy_id = created.json()["policy_id"]

    manager = await _login(client, "manager1")
    first = await _create_action(client, manager)
    detail = await _audit_detail(
        db_session, action="ACTION_CREATE", resource_id=first
    )
    assert detail["policy_hits"] == [str(policy_id)]  # 命中（缓存已填充）

    patched = await client.patch(
        f"{POLICIES}/{policy_id}", json={"status": "DISABLED"}, headers=admin
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["status"] == "DISABLED"

    second = await _create_action(client, manager)
    after = await _audit_detail(
        db_session, action="ACTION_CREATE", resource_id=second
    )
    assert "policy_hits" not in after  # 缓存失效直证：不命中


# ---- 8. 无策略租户：审计行无 policy_hits 键 ----


async def test_no_policy_no_hits_key(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    manager = await _login(client, "manager1")
    action_id = await _create_action(client, manager)
    detail = await _audit_detail(
        db_session, action="ACTION_CREATE", resource_id=action_id
    )
    assert "policy_hits" not in detail
