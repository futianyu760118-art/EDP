"""T2 Action 状态机集成测试（EDP-020）：创建/列表/详情/转移全链 + Guard。

覆盖：
1. 创建 201 双轨（dev Key write:action / manager1 JWT action:execute），
   响应 {action_id, status:"PROPOSED", created_at} + DB 落库断言；
2. case_id 不存在 → 400 VALIDATION_ERROR；
3. 列表三过滤（status/owner/case_id）+ 游标翻页 + 简投影 allowed_to；
4. 详情完整对象 + allowed_to（PROPOSED 三项目录序）；
5. 六步全链 PROPOSED→…→VERIFIED（Human-Only 两步由 HUMAN 执行）+ 终态
   无出边 + completion_time/verified_at/verified_by（=principal.id）回填；
6. 非法转移（PROPOSED→VERIFIED）→ 422 INVALID_TRANSITION 且
   extra.allowed_to 正确；
7. from_status 过期 → 409 CONFLICT；
8. SERVICE Key（write:action）做 Human-Only 转移（APPROVED→EXECUTING）→
   403 GUARD_POLICY_DENIED + GUARD_DENIED 审计行（action.actions）且状态
   未变；
9. comment 落证据：PATCH 带 comment → GET /evidence?ref_type=ACTION&ref_id=
   {action_id} 可查（source_system=edp、source_record_id={action_id}#{to}）；
10. 跨租户：tenant-actions 读 default 行动 → 详情 404 / 列表空；
11. ANALYST（仅 action:read）读 200 / PATCH 403 FORBIDDEN。

会话形态：应用引擎 = conftest.app_role_engine（edp_app，FORCE RLS）；断言以
migrator db_session 直查（绕 RLS）。清场：purge_tenant_business_data
（逆依赖序含 action.actions）+ 本模块审计行/临时 Key/tenant-actions。
"""

from uuid import UUID, uuid4

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.core.security.apikey import hash_key
from edp_api.main import create_app
from edp_api.modules.audit.aspect import install_audit_aspect
from edp_api.modules.demo import service as demo_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

BASE = "/api/v1/actions"
EVIDENCE = "/api/v1/evidence"
DEV_KEY = "edp-dev-agent-hub-key"
DEV_HEADERS = {"X-API-Key": DEV_KEY}
LOGIN = "/api/v1/auth/login"
SEED_PASSWORD = "Admin@123!"

# 跨租户用例的 B 租户（migrator 直造；readonly Key）
TENANT_B_SLUG = "tenant-actions"
TENANT_B_KEY = "t2-actions-tenant-b-key"
TENANT_B_PRINCIPAL = "t2-actions-tenant-b"


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS），actions 路由
    随 create_app 装配（含 GUARD_DENIED 独立会话路径）。"""
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
    """ORM 写（行动/证据/links）依赖切面落审计——与 create_app 同一装配。"""
    install_audit_aspect()


@pytest.fixture
async def demo(
    app_role_engine: AsyncEngine, default_tenant_id: UUID
) -> demo_service.SeedStats:
    """default 租户演示数据集（DEMO_CASE + 证据 + 源事件）；清场见
    _clean_actions_rows。"""
    stats = await demo_service.seed(app_role_engine, default_tenant_id)
    assert stats.failed == 0
    return stats


@pytest.fixture(autouse=True)
async def _clean_actions_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    """每测试后清场：default 业务行（含 seed 全量与 action.actions）+ 本模块
    审计行/临时 Key/tenant-actions（migrator 绕 RLS）+ 还原 demo 锚。

    demo 锚必须还原：本文件 demo fixture 经 seed 写入整点锚（tenants.
    attributes.demo_seed），若残留会使 test_adapters_api 的 jsonb_set 直写
    锚（对 NULL attributes 静默无效）变为生效，其硬编码 8:30 锚进而污染
    test_demo_seed 的首跑整点断言（全量顺序 actions < adapters < demo_seed）。
    """
    yield
    await demo_service.purge_tenant_business_data(db_session, default_tenant_id)
    await db_session.execute(
        text(
            "UPDATE platform.tenants SET attributes = attributes - 'demo_seed'"
            " WHERE tenant_id = :t"
        ),
        {"t": default_tenant_id},
    )
    manager1_id = (
        await db_session.execute(
            text("SELECT user_id FROM platform.users WHERE username = 'manager1'")
        )
    ).scalar_one()
    await db_session.execute(
        text(
            "DELETE FROM platform.audit_logs WHERE tenant_id = :t"
            " AND (actor_id IN ('adapter:erp', 'agent-hub', :manager1)"
            "      OR (action = 'GUARD_DENIED'"
            "          AND resource_type = 'action.actions'))"
        ),
        {"t": default_tenant_id, "manager1": str(manager1_id)},
    )
    b_ids = "SELECT tenant_id FROM platform.tenants WHERE slug = 'tenant-actions'"
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
        text(
            "DELETE FROM platform.tenant_usage_daily WHERE tenant_id IN"
            " (SELECT tenant_id FROM platform.tenants WHERE slug = 'tenant-actions')"
        )
    )
    await db_session.execute(
        text("DELETE FROM platform.tenants WHERE slug = 'tenant-actions'")
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
    """直插临时 API Key（照 test_decisions 模式；hash_key 与生产同实现）。"""
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


async def _seed_case_id(db_session: AsyncSession, tenant_id: UUID) -> UUID:
    return (
        await db_session.execute(
            text("SELECT case_id FROM decision.cases WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
    ).scalar_one()


async def _create_action(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    case_id: UUID | None = None,
    title: str = "加急采购物料X 1000 件",
    owner: str | None = "procurement_zhang",
) -> httpx.Response:
    return await client.post(
        BASE,
        headers=headers,
        json={
            "case_id": str(case_id) if case_id else None,
            "title": title,
            "action_type": "expedite_purchase",
            "owner": owner,
            "owner_role": "PROCUREMENT",
        },
    )


async def _transition(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    action_id: str,
    from_status: str,
    to_status: str,
    comment: str | None = None,
) -> httpx.Response:
    payload: dict = {"from_status": from_status, "to_status": to_status}
    if comment is not None:
        payload["comment"] = comment
    return await client.patch(
        f"{BASE}/{action_id}/status", headers=headers, json=payload
    )


# ---- 1. 创建 201 双轨：dev Key（write:action）/ manager1 JWT ----


async def test_create_action_dual_track(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    case_id = await _seed_case_id(db_session, default_tenant_id)

    resp = await _create_action(client, DEV_HEADERS, case_id=case_id)
    assert resp.status_code == 201, resp.text
    key_body = resp.json()
    assert key_body["status"] == "PROPOSED"
    assert key_body["created_at"]
    UUID(key_body["action_id"])

    manager = await _login(client, "manager1")
    resp = await _create_action(client, manager, title="通知客户交期变更")
    assert resp.status_code == 201, resp.text
    jwt_body = resp.json()
    assert jwt_body["status"] == "PROPOSED"

    manager1_id = (
        await db_session.execute(
            text("SELECT user_id FROM platform.users WHERE username = 'manager1'")
        )
    ).scalar_one()
    key_row = (
        await db_session.execute(
            text(
                "SELECT title, action_type, status, owner, owner_role, case_id,"
                " created_by FROM action.actions WHERE action_id = :a"
            ),
            {"a": key_body["action_id"]},
        )
    ).one()
    assert key_row.title == "加急采购物料X 1000 件"
    assert key_row.action_type == "expedite_purchase"
    assert key_row.status == "PROPOSED"
    assert key_row.owner == "procurement_zhang"
    assert key_row.owner_role == "PROCUREMENT"
    assert str(key_row.case_id) == str(case_id)
    assert key_row.created_by == "agent-hub"

    jwt_row = (
        await db_session.execute(
            text("SELECT created_by FROM action.actions WHERE action_id = :a"),
            {"a": jwt_body["action_id"]},
        )
    ).scalar_one()
    assert jwt_row == str(manager1_id)


# ---- 2. case_id 不存在 → 400 ----


async def test_create_action_unknown_case_400(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    resp = await _create_action(client, DEV_HEADERS, case_id=uuid4())
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    # 失败创建无残留（seed 不建 action 行）
    count = (
        await db_session.execute(
            text("SELECT count(*) FROM action.actions WHERE tenant_id = :t"),
            {"t": default_tenant_id},
        )
    ).scalar_one()
    assert count == 0


# ---- 3. 列表三过滤 + 游标 + allowed_to 简投影 ----


async def test_list_three_filters_and_cursor(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    case_id = await _seed_case_id(db_session, default_tenant_id)
    manager = await _login(client, "manager1")

    a1 = (await _create_action(client, DEV_HEADERS, case_id=case_id)).json()
    a2 = (
        await _create_action(client, manager, title="启用替代料方案", owner="plm_li")
    ).json()
    a3 = (await _create_action(client, DEV_HEADERS, title="调整生产计划")).json()
    # a2 走两步到 ACCEPTED，供 status 过滤对照
    assert (
        await _transition(client, manager, a2["action_id"], "PROPOSED", "ASSIGNED")
    ).status_code == 200
    assert (
        await _transition(client, manager, a2["action_id"], "ASSIGNED", "ACCEPTED")
    ).status_code == 200

    resp = await client.get(BASE, params={"status": "PROPOSED"}, headers=DEV_HEADERS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert {item["action_id"] for item in body["items"]} == {
        a1["action_id"],
        a3["action_id"],
    }
    item = body["items"][0]
    # exclude_none：owner 非空在列、due_date 为 None 键缺省
    assert set(item) == {
        "action_id",
        "title",
        "status",
        "owner",
        "allowed_to",
    }
    assert item["allowed_to"] == [
        {"to_status": "ASSIGNED", "human_only": False},
        {"to_status": "CANCELLED", "human_only": False},
        {"to_status": "REJECTED", "human_only": False},
    ]

    resp = await client.get(BASE, params={"owner": "plm_li"}, headers=DEV_HEADERS)
    assert [i["action_id"] for i in resp.json()["items"]] == [a2["action_id"]]
    assert resp.json()["items"][0]["status"] == "ACCEPTED"

    resp = await client.get(
        BASE, params={"case_id": str(case_id)}, headers=DEV_HEADERS
    )
    assert [i["action_id"] for i in resp.json()["items"]] == [a1["action_id"]]

    # 游标：limit=2 翻页不重不漏
    first = await client.get(
        BASE, params={"limit": 2}, headers=DEV_HEADERS
    )
    assert first.status_code == 200
    page1 = first.json()
    assert len(page1["items"]) == 2
    assert page1["next_cursor"]
    second = await client.get(
        BASE, params={"limit": 2, "cursor": page1["next_cursor"]}, headers=DEV_HEADERS
    )
    page2 = second.json()
    assert len(page2["items"]) == 1
    seen = {i["action_id"] for i in page1["items"] + page2["items"]}
    assert seen == {a1["action_id"], a2["action_id"], a3["action_id"]}
    # exclude_none：无更多页时 next_cursor 键缺省（等价 null）
    assert page2.get("next_cursor") is None


# ---- 4. 详情完整对象 + allowed_to ----


async def test_detail_full_object_with_allowed_to(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    case_id = await _seed_case_id(db_session, default_tenant_id)
    created = (await _create_action(client, DEV_HEADERS, case_id=case_id)).json()

    resp = await client.get(f"{BASE}/{created['action_id']}", headers=DEV_HEADERS)
    assert resp.status_code == 200, resp.text
    detail = resp.json()
    assert detail["action_id"] == created["action_id"]
    assert detail["case_id"] == str(case_id)
    assert detail["title"] == "加急采购物料X 1000 件"
    assert detail["action_type"] == "expedite_purchase"
    assert detail["status"] == "PROPOSED"
    assert detail["owner"] == "procurement_zhang"
    assert detail["owner_role"] == "PROCUREMENT"
    assert detail["completion_time"] is None
    assert detail["verified_at"] is None
    assert detail["verified_by"] is None
    assert detail["created_at"]
    assert detail["updated_at"]
    assert detail["allowed_to"] == [
        {"to_status": "ASSIGNED", "human_only": False},
        {"to_status": "CANCELLED", "human_only": False},
        {"to_status": "REJECTED", "human_only": False},
    ]


# ---- 5. 六步全链 PROPOSED→…→VERIFIED（Human-Only 由 HUMAN 执行）----


async def test_full_chain_to_verified(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    manager = await _login(client, "manager1")
    created = (await _create_action(client, manager)).json()
    action_id = created["action_id"]

    chain = [
        ("PROPOSED", "ASSIGNED"),
        ("ASSIGNED", "ACCEPTED"),
        ("ACCEPTED", "APPROVED"),
        ("APPROVED", "EXECUTING"),  # Human-Only
        ("EXECUTING", "COMPLETED"),
        ("COMPLETED", "VERIFIED"),  # Human-Only
    ]
    for from_status, to_status in chain:
        resp = await _transition(client, manager, action_id, from_status, to_status)
        assert resp.status_code == 200, f"{from_status}→{to_status}: {resp.text}"
        body = resp.json()
        assert body["action_id"] == action_id
        assert body["status"] == to_status
        assert body["updated_at"]

    # 终态无出边
    detail = (
        await client.get(f"{BASE}/{action_id}", headers=manager)
    ).json()
    assert detail["allowed_to"] == []

    manager1_id = (
        await db_session.execute(
            text("SELECT user_id FROM platform.users WHERE username = 'manager1'")
        )
    ).scalar_one()
    row = (
        await db_session.execute(
            text(
                "SELECT status, completion_time, verified_at, verified_by"
                " FROM action.actions WHERE action_id = :a"
            ),
            {"a": action_id},
        )
    ).one()
    assert row.status == "VERIFIED"
    assert row.completion_time is not None
    assert row.verified_at is not None
    # verified_by 口径与 memories.reviewed_by 一致：principal.id（用户 UUID）
    assert row.verified_by == str(manager1_id)


# ---- 6. 非法转移 → 422 INVALID_TRANSITION（extra.allowed_to）----


async def test_invalid_transition_422_with_allowed_to(
    client: httpx.AsyncClient,
    demo: demo_service.SeedStats,
) -> None:
    manager = await _login(client, "manager1")
    created = (await _create_action(client, manager)).json()

    resp = await _transition(
        client, manager, created["action_id"], "PROPOSED", "VERIFIED"
    )
    assert resp.status_code == 422, resp.text
    error = resp.json()["error"]
    assert error["code"] == "INVALID_TRANSITION"
    assert error["allowed_to"] == [
        {"to_status": "ASSIGNED", "human_only": False},
        {"to_status": "CANCELLED", "human_only": False},
        {"to_status": "REJECTED", "human_only": False},
    ]

    # 状态未变
    detail = (
        await client.get(f"{BASE}/{created['action_id']}", headers=manager)
    ).json()
    assert detail["status"] == "PROPOSED"


# ---- 7. from_status 过期 → 409 CONFLICT ----


async def test_stale_from_status_409(
    client: httpx.AsyncClient,
    demo: demo_service.SeedStats,
) -> None:
    manager = await _login(client, "manager1")
    created = (await _create_action(client, manager)).json()
    action_id = created["action_id"]

    resp = await _transition(client, manager, action_id, "PROPOSED", "ASSIGNED")
    assert resp.status_code == 200, resp.text

    # from_status 过期（当前 ASSIGNED），但 PROPOSED→REJECTED 本身是合法转移
    resp = await _transition(client, manager, action_id, "PROPOSED", "REJECTED")
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "CONFLICT"

    detail = (await client.get(f"{BASE}/{action_id}", headers=manager)).json()
    assert detail["status"] == "ASSIGNED"


# ---- 8. SERVICE Key 做 Human-Only 转移 → 403 + GUARD_DENIED 审计 ----


async def test_service_human_only_guard_denied_and_audited(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    created = (await _create_action(client, DEV_HEADERS)).json()
    action_id = created["action_id"]

    # SERVICE 可做非 Human-Only 步，走到 APPROVED
    for from_status, to_status in (
        ("PROPOSED", "ASSIGNED"),
        ("ASSIGNED", "ACCEPTED"),
        ("ACCEPTED", "APPROVED"),
    ):
        resp = await _transition(client, DEV_HEADERS, action_id, from_status, to_status)
        assert resp.status_code == 200, resp.text

    # APPROVED→EXECUTING 为 Human-Only：SERVICE → 403 GUARD_POLICY_DENIED
    resp = await _transition(client, DEV_HEADERS, action_id, "APPROVED", "EXECUTING")
    assert resp.status_code == 403, resp.text
    error = resp.json()["error"]
    assert error["code"] == "GUARD_POLICY_DENIED"
    assert error["message"] == "该操作仅限人工执行"

    rows = (
        (
            await db_session.execute(
                text(
                    "SELECT actor_type, actor_id, resource_type, resource_id, detail"
                    " FROM platform.audit_logs"
                    " WHERE action = 'GUARD_DENIED'"
                    " AND resource_type = 'action.actions'"
                    " AND actor_id = 'agent-hub'"
                )
            )
        )
        .mappings()
        .all()
    )
    assert len(rows) == 1
    assert rows[0]["actor_type"] == "SERVICE"
    assert rows[0]["resource_id"] == action_id
    assert rows[0]["detail"]["reason"] == "Human-Only"
    assert rows[0]["detail"]["path"] == f"{BASE}/{action_id}/status"

    # 守卫先于写：状态仍 APPROVED
    detail = (await client.get(f"{BASE}/{action_id}", headers=DEV_HEADERS)).json()
    assert detail["status"] == "APPROVED"


# ---- 9. comment 落证据（GET /evidence?ref_type=ACTION&ref_id= 可查）----


async def test_comment_persisted_as_evidence(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    case_id = await _seed_case_id(db_session, default_tenant_id)
    manager = await _login(client, "manager1")
    created = (await _create_action(client, manager, case_id=case_id)).json()
    action_id = created["action_id"]

    resp = await _transition(
        client,
        manager,
        action_id,
        "PROPOSED",
        "ASSIGNED",
        comment="指派给采购张三，限两日内反馈",
    )
    assert resp.status_code == 200, resp.text

    resp = await client.get(
        EVIDENCE,
        params={"ref_type": "ACTION", "ref_id": action_id},
        headers=DEV_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["source_system"] == "edp"
    assert items[0]["source_record_id"] == f"{action_id}#ASSIGNED"

    evidence_id = items[0]["evidence_id"]
    detail = (await client.get(f"{EVIDENCE}/{evidence_id}", headers=DEV_HEADERS)).json()
    assert detail["snapshot"] == {"comment": "指派给采购张三，限两日内反馈"}
    assert detail["checksum"].startswith("sha256:")


# ---- 10. 跨租户：tenant-actions 读 default 行动 = 404/空 ----


async def test_cross_tenant_not_leaked(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    created = (await _create_action(client, DEV_HEADERS)).json()

    tenant_b = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO platform.tenants (tenant_id, slug, name, status)"
            " VALUES (:t, :slug, '租户ActionsB', 'ACTIVE')"
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

    resp = await client.get(f"{BASE}/{created['action_id']}", headers=headers)
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "NOT_FOUND"

    resp = await client.get(BASE, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []


# ---- 11. ANALYST（仅 action:read）：读 200 / PATCH 403 ----


async def test_analyst_read_ok_but_transition_forbidden(
    client: httpx.AsyncClient,
    demo: demo_service.SeedStats,
) -> None:
    analyst = await _login(client, "analyst1")
    created = (await _create_action(client, DEV_HEADERS)).json()

    resp = await client.get(BASE, headers=analyst)
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["items"]) == 1

    resp = await client.get(f"{BASE}/{created['action_id']}", headers=analyst)
    assert resp.status_code == 200, resp.text

    resp = await _transition(
        client, analyst, created["action_id"], "PROPOSED", "ASSIGNED"
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"
