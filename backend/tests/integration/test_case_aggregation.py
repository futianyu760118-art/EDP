"""T5 闭环案例聚合集成测试（EDP-028，W4）：case detail 扩展 + ebms 标量子查询。

覆盖：
1. seed → 提交决策记录（manager1，Human）→ 建两个 action（其一走两步
   PROPOSED→ASSIGNED→ACCEPTED）→ case detail 断言：
   - event 非空（event_id=source 事件、risk_level=P1、summary=场景 2 文案）；
   - steps ≥ 6 且时间升序：EVENT/CASE_CREATED/DECISION/每行动两个 ACTION
     节点（创建 + 当前状态快照）；DECISION 节点 human_only=True 且 title 含
     chosen_option；快照节点 human_only 按当前 status 出边（ACCEPTED/
     PROPOSED → False）；
   - actions[] 全量（allowed_to 非空；ACCEPTED 行动目录 = APPROVED/CANCELLED）；
   - evidence_chain 四层各 ≥ 1（RESULT=seed 回流结果证据 result:{event_id}；
     DECISION=测试补建的决策记录证据；EVIDENCE=seed CASE links；SOURCE=投影
     去重且无 evidence_id 键）；
2. 同 source_id 二次 POST /decisions/cases → 409 CONFLICT（uq_cases_tenant_source）；
3. ebms exceptions：案例决策后 RESOLVED 单行命中该事件且 case_id 正确
   （标量子查询无 join 倍增）、OPEN 不再含它；
4. 无 source_id 案例：event/steps 最小形态（event 键缺省、仅 CASE_CREATED）；
5. 跨租户：tenant-case-agg 读 default 案例 detail → 404。

会话形态：应用引擎 = conftest.app_role_engine（edp_app，FORCE RLS）；断言以
migrator db_session 直查（绕 RLS）。清场：purge_tenant_business_data（逆依赖
序）+ demo 锚还原 + 本模块审计行/临时 Key/tenant-case-agg（口径同
test_decisions/test_actions）。
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

BASE = "/api/v1/decisions"
ACTIONS = "/api/v1/actions"
EVIDENCE = "/api/v1/evidence"
EBMS = "/api/v1/ebms/exceptions"
DEV_KEY = "edp-dev-agent-hub-key"
DEV_HEADERS = {"X-API-Key": DEV_KEY}
LOGIN = "/api/v1/auth/login"
SEED_PASSWORD = "Admin@123!"

# 跨租户用例的 B 租户（migrator 直造；readonly Key）
TENANT_B_SLUG = "tenant-case-agg"
TENANT_B_KEY = "t5-case-agg-tenant-b-key"
TENANT_B_PRINCIPAL = "t5-case-agg-tenant-b"


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS），decisions 路由
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
    """ORM 写（案例/记录/行动/证据/links）依赖切面落审计——与 create_app
    同一装配。"""
    install_audit_aspect()


@pytest.fixture
async def demo(
    app_role_engine: AsyncEngine, default_tenant_id: UUID
) -> demo_service.SeedStats:
    """default 租户演示数据集（T7 seed 等价路径）；清场见 _clean_case_agg_rows。"""
    stats = await demo_service.seed(app_role_engine, default_tenant_id)
    assert stats.failed == 0
    return stats


@pytest.fixture(autouse=True)
async def _clean_case_agg_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    """每测试后清场：default 业务行（含 seed 全量与 action.actions）+ demo 锚
    还原 + 本模块审计行/tenant-case-agg（migrator 绕 RLS）。

    demo 锚必须还原（口径同 test_actions_api）：残留会使 test_adapters_api
    的 jsonbs_set 直写锚变为生效，进而污染 test_demo_seed 的首跑整点断言
    （全量顺序 case_aggregation < adapters < demo_seed）。
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
            "          AND resource_type IN ('decision.records', 'action.actions')))"
        ),
        {"t": default_tenant_id, "manager1": str(manager1_id)},
    )
    b_ids = "SELECT tenant_id FROM platform.tenants WHERE slug = 'tenant-case-agg'"
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
            " (SELECT tenant_id FROM platform.tenants WHERE slug = 'tenant-case-agg')"
        )
    )
    await db_session.execute(
        text("DELETE FROM platform.tenants WHERE slug = 'tenant-case-agg'")
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


async def _seed_case_source_id(
    db_session: AsyncSession, tenant_id: UUID
) -> str:
    return (
        await db_session.execute(
            text("SELECT source_id FROM decision.cases WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
    ).scalar_one()


async def _event_object_id(
    db_session: AsyncSession, tenant_id: UUID, event_id: str
) -> UUID:
    return (
        await db_session.execute(
            text(
                "SELECT object_id FROM event.events"
                " WHERE tenant_id = :t AND event_id = :e"
            ),
            {"t": tenant_id, "e": event_id},
        )
    ).scalar_one()


async def _create_action(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    case_id: UUID,
    title: str,
) -> dict:
    resp = await client.post(
        ACTIONS,
        headers=headers,
        json={
            "case_id": str(case_id),
            "title": title,
            "action_type": "PROCUREMENT",
            "owner": "manager1",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _transition(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    action_id: str,
    from_status: str,
    to_status: str,
) -> dict:
    resp = await client.patch(
        f"{ACTIONS}/{action_id}/status",
        headers=headers,
        json={"from_status": from_status, "to_status": to_status},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---- 1. 闭环聚合：event/steps/actions/evidence_chain ----


async def test_case_detail_full_closed_loop_aggregation(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    case_id = await _seed_case_id(db_session, default_tenant_id)
    source_id = await _seed_case_source_id(db_session, default_tenant_id)
    manager = await _login(client, "manager1")

    # 决策记录（Human）→ 案例 DECIDED
    decided = await client.post(
        f"{BASE}/cases/{case_id}/records",
        headers=manager,
        json={
            "chosen_option": "EXPEDITE",
            "decision_type": "HUMAN",
            "comment": "同意加急采购，优先保交付",
        },
    )
    assert decided.status_code == 201, decided.text

    # 决策记录证据（ref_type=DECISION、ref_id=case；决策意见落链最小补建）
    object_id = await _event_object_id(db_session, default_tenant_id, source_id)
    evidence = await client.post(
        EVIDENCE,
        headers=manager,
        json={
            "source_system": "ebms",
            "source_record_id": f"decision:{case_id}",
            "object_id": str(object_id),
            "snapshot": {"comment": "同意加急采购，优先保交付"},
            "captured_at": "2026-09-18T02:00:00Z",
            "links": [{"ref_type": "DECISION", "ref_id": str(case_id)}],
        },
    )
    assert evidence.status_code == 201, evidence.text

    # 行动一：创建 + 走两步（PROPOSED→ASSIGNED→ACCEPTED）
    a1 = await _create_action(client, manager, case_id, "加急采购物料X")
    await _transition(client, manager, a1["action_id"], "PROPOSED", "ASSIGNED")
    await _transition(client, manager, a1["action_id"], "ASSIGNED", "ACCEPTED")
    # 行动二：仅创建（PROPOSED 快照）
    a2 = await _create_action(client, manager, case_id, "通知客户预计交期")

    detail = await client.get(f"{BASE}/cases/{case_id}", headers=manager)
    assert detail.status_code == 200, detail.text
    body = detail.json()

    # 既有字段不动（向后兼容回归）
    assert body["case_id"] == str(case_id)
    assert body["status"] == "DECIDED"
    assert body["risk_level"] == "P1"
    assert len(body["evidence_refs"]) == 3
    assert len(body["decisions"]) == 1

    # event：source 事件摘要
    event = body["event"]
    assert event["event_id"] == source_id
    assert event["event_type"] == "capability.result.order_risk"
    assert event["risk_level"] == "P1"
    assert event["summary"] == "物料X缺口1000，预计延误5天"
    assert event["occurred_at"]

    # steps：EVENT + CASE_CREATED + DECISION + 每行动（创建 + 快照）= 7
    steps = body["steps"]
    assert len(steps) == 7
    assert [step["occurred_at"] for step in steps] == sorted(
        step["occurred_at"] for step in steps
    )
    assert steps[0]["step_type"] == "EVENT"
    assert steps[0]["actor"] == "agent-hub"
    assert steps[1]["step_type"] == "CASE_CREATED"
    decision_steps = [s for s in steps if s["step_type"] == "DECISION"]
    assert len(decision_steps) == 1
    assert decision_steps[0]["human_only"] is True
    assert "EXPEDITE" in decision_steps[0]["title"]
    action_steps = [s for s in steps if s["step_type"] == "ACTION"]
    assert len(action_steps) == 4
    # 快照节点：ACCEPTED/PROPOSED 出边均非 Human-Only（False 显式在场）
    snapshot_titles = [s["title"] for s in action_steps if "当前状态" in s["title"]]
    assert set(snapshot_titles) == {"当前状态：ACCEPTED", "当前状态：PROPOSED"}
    assert all(s["human_only"] is False for s in action_steps if "当前状态" in s["title"])
    # 创建节点 title=行动标题（human_only 缺省）
    create_nodes = [s for s in action_steps if "当前状态" not in s["title"]]
    assert {s["title"] for s in create_nodes} == {"加急采购物料X", "通知客户预计交期"}
    assert all("human_only" not in s for s in create_nodes)

    # actions[]：全量 + allowed_to
    actions = {item["action_id"]: item for item in body["actions"]}
    assert set(actions) == {a1["action_id"], a2["action_id"]}
    assert actions[a1["action_id"]]["status"] == "ACCEPTED"
    assert actions[a1["action_id"]]["owner"] == "manager1"
    assert actions[a1["action_id"]]["allowed_to"] == [
        {"to_status": "APPROVED", "human_only": False},
        {"to_status": "CANCELLED", "human_only": False},
    ]
    assert actions[a2["action_id"]]["allowed_to"]

    # evidence_chain：四层各 ≥ 1
    chain = body["evidence_chain"]
    by_layer: dict[str, list[dict]] = {}
    for node in chain:
        by_layer.setdefault(node["layer"], []).append(node)
    assert len(by_layer["RESULT"]) >= 1
    # seed 回流结果证据（T9：risk 事件自动落 result:{event_id} 证据 + RESULT link）
    assert any(
        node["source_record_id"] == f"result:{source_id}" for node in by_layer["RESULT"]
    )
    assert len(by_layer["DECISION"]) >= 1
    assert any(
        node["source_record_id"] == f"decision:{case_id}" for node in by_layer["DECISION"]
    )
    assert len(by_layer["EVIDENCE"]) >= 1  # seed CASE links（erp/plm/agent-hub）
    # SOURCE：三层证据 (source_system, source_record_id) 投影去重、无 evidence_id
    source_nodes = by_layer["SOURCE"]
    assert len(source_nodes) >= 1
    assert all("evidence_id" not in node for node in source_nodes)
    projected = {
        (node["source_system"], node["source_record_id"])
        for layer in ("RESULT", "DECISION", "EVIDENCE")
        for node in by_layer[layer]
    }
    assert {
        (node["source_system"], node["source_record_id"]) for node in source_nodes
    } == projected
    assert len(source_nodes) == len(projected)  # 去重无重复


# ---- 2. 同 source_id 二次建案例 → 409 ----


async def test_duplicate_source_case_conflict_409(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    source_id = await _seed_case_source_id(db_session, default_tenant_id)

    resp = await client.post(
        f"{BASE}/cases",
        headers=DEV_HEADERS,
        json={
            "question": "同源事件重复建案例",
            "source_type": "capability.result",
            "source_id": source_id,
        },
    )
    assert resp.status_code == 409, resp.text
    error = resp.json()["error"]
    assert error["code"] == "CONFLICT"
    assert "该来源事件已建案例" in error["message"]

    # 仅 seed 案例 1 行（冲突插入已回滚）
    assert (
        await db_session.execute(
            text("SELECT count(*) FROM decision.cases WHERE tenant_id = :t"),
            {"t": default_tenant_id},
        )
    ).scalar_one() == 1


# ---- 3. ebms exceptions：标量子查询单行无倍增 ----


async def test_ebms_exceptions_scalar_case_id_single_row(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    case_id = await _seed_case_id(db_session, default_tenant_id)
    manager = await _login(client, "manager1")

    resolved = await client.get(EBMS, params={"status": "RESOLVED"}, headers=DEV_HEADERS)
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["items"] == []

    decided = await client.post(
        f"{BASE}/cases/{case_id}/records",
        headers=manager,
        json={"chosen_option": "EXPEDITE"},
    )
    assert decided.status_code == 201, decided.text

    resolved = await client.get(EBMS, params={"status": "RESOLVED"}, headers=DEV_HEADERS)
    assert resolved.status_code == 200, resolved.text
    items = resolved.json()["items"]
    # 单行命中（标量子查询：无 join 倍增）、case_id 正确
    assert [item["order_no"] for item in items] == ["SO-2026-00123"]
    assert items[0]["case_id"] == str(case_id)

    opened = await client.get(EBMS, params={"status": "OPEN"}, headers=DEV_HEADERS)
    assert opened.status_code == 200, opened.text
    assert "SO-2026-00123" not in {item["order_no"] for item in opened.json()["items"]}


# ---- 4. 无 source_id 案例：聚合字段最小形态 ----


async def test_case_without_source_minimal_aggregation(
    client: httpx.AsyncClient,
) -> None:
    created = await client.post(
        f"{BASE}/cases",
        headers=DEV_HEADERS,
        json={"question": "无源事件案例", "risk_level": "P2"},
    )
    assert created.status_code == 201, created.text

    detail = await client.get(
        f"{BASE}/cases/{created.json()['case_id']}", headers=DEV_HEADERS
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    # exclude_none：event 无源事件 → 键缺省；steps 仅 CASE_CREATED
    assert "event" not in body
    assert [step["step_type"] for step in body["steps"]] == ["CASE_CREATED"]
    assert body["actions"] == []
    assert body["evidence_chain"] == []


# ---- 5. 跨租户：tenant-case-agg 读 default 案例 detail → 404 ----


async def test_cross_tenant_detail_not_leaked(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    case_id = await _seed_case_id(db_session, default_tenant_id)
    tenant_b = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO platform.tenants (tenant_id, slug, name, status)"
            " VALUES (:t, :slug, '租户CaseAggB', 'ACTIVE')"
        ),
        {"t": tenant_b, "slug": TENANT_B_SLUG},
    )
    await db_session.commit()
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
            "key_hash": hash_key(TENANT_B_KEY),
            "t": tenant_b,
            "principal": TENANT_B_PRINCIPAL,
            "scopes": ["readonly"],
        },
    )
    await db_session.commit()

    resp = await client.get(
        f"{BASE}/cases/{case_id}", headers={"X-API-Key": TENANT_B_KEY}
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "NOT_FOUND"
