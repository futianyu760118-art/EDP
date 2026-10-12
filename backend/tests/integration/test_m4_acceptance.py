"""T13 M4 端到端验收集成测试（演示脚本 ①~⑤ 断言化，EDP-029）。

与 ``docs/demo/m4-demo.md`` 五幕脚本一一对应（计划 7.1：订单 B 关键料缺失
——物料 X 缺口 1000、供应商交期 10 天；⑥ 浏览器级彩排为人工清单）：

- ① 全链闭环：seed → tools 取数（订单 B + X-100 库存缺口读数）→ POST
  /events/batch 回流（幂等重放）→ POST /decisions/cases → manager records
  （决策意见落证最小补建）→ action 六步 PROPOSED→…→VERIFIED（comment 落
  证据 ref_type=ACTION）→ ebms 待办清空；
- ② Human-Only 403：SERVICE Key 提交 records → 403 GUARD_POLICY_DENIED +
  GUARD_DENIED 审计（decision.records）；SERVICE Key PATCH EXECUTING
  （Human-Only 边）→ 403 + 审计（action.actions）；
- ③ 非法转移 422：PROPOSED→VERIFIED → 422 INVALID_TRANSITION 且
  error.allowed_to 为 PROPOSED 允许列表；
- ④ 并发 409：同 from_status 两请求并发，仅一成功（乐观锁）；
- ⑤ ebms 口径：决策前 pending 含该案例 / todos pending_actions 含行动
  （VERIFIED 前）/ VERIFIED 后 todos 清空该行动、pending 归零；
- ⑥ 闭环聚合完整：case detail event/steps（≥6）/evidence_chain 四层各 ≥1/
  actions.allowed_to。

会话形态：应用引擎 = conftest.app_role_engine（edp_app，FORCE RLS）；断言以
migrator db_session 直查（绕 RLS）。清场：purge_tenant_business_data（逆依赖
序）+ demo 锚还原 + 本模块审计行（口径同 test_actions/test_case_aggregation）。
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.main import create_app
from edp_api.modules.audit.aspect import install_audit_aspect
from edp_api.modules.demo import service as demo_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

BASE = "/api/v1"
TOOLS = f"{BASE}/tools"
EVENTS = f"{BASE}/events"
EVIDENCE = f"{BASE}/evidence"
DECISIONS = f"{BASE}/decisions"
ACTIONS = f"{BASE}/actions"
EBMS = f"{BASE}/ebms"
LOGIN = f"{BASE}/auth/login"
DEV_KEY = "edp-dev-agent-hub-key"
DEV_HEADERS = {"X-API-Key": DEV_KEY}
SEED_PASSWORD = "Admin@123!"

# 演示数据集计数（快照段 erp36+mes3+plm4；回流段 10 风险事件 + 场景 2 案例）
SEED_FETCHED = 43
SEED_RESULT_EVENTS = 10
# seed 风险事件中无关联案例条数（10 风险事件 - 场景 2 一条有案例）
UNCASED_RISK_EVENTS = 9

CASE_ORDER_NO = "SO-2026-00123"


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS），decisions/
    actions 路由随 create_app 装配（含 GUARD_DENIED 独立会话路径）。"""
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
    """seed 的 ORM 写依赖切面落审计——与 create_app 同一装配（幂等）。"""
    install_audit_aspect()


@pytest.fixture
async def demo(
    app_role_engine: AsyncEngine, default_tenant_id: UUID, db_session: AsyncSession
) -> demo_service.SeedStats:
    """default 租户演示数据集（场景 2 案例主线）；清场见 _clean_m4_rows。

    V1.2 T21：tools 缺省 official_only=true——种子后统一置 CURATED
    （目标态准入后语义；门禁行为见 test_v12_fact_layer）。
    """
    stats = await demo_service.seed(app_role_engine, default_tenant_id)
    assert stats.failed == 0
    await db_session.execute(
        text(
            "UPDATE master.business_objects SET layer_status = 'CURATED'"
            " WHERE tenant_id = :t"
        ),
        {"t": default_tenant_id},
    )
    await db_session.commit()
    return stats


@pytest.fixture(autouse=True)
async def _clean_m4_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    """每测试后清场：default 业务行（seed 全量 + cases/actions/evidence/
    events）+ demo 锚还原 + 本模块审计行（migrator 绕 RLS）。

    demo 锚必须还原（口径同 test_actions_api/test_case_aggregation）：残留会
    污染 test_adapters_api 的锚直写与 test_demo_seed 的首跑整点断言。
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
    await db_session.commit()


async def _login(client: httpx.AsyncClient, username: str) -> dict[str, str]:
    resp = await client.post(
        LOGIN, json={"username": username, "password": SEED_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed_case(
    db_session: AsyncSession, tenant_id: UUID
) -> tuple[UUID, str]:
    """seed 场景 2 案例：(case_id, source 事件 id)。"""
    return (
        await db_session.execute(
            text(
                "SELECT c.case_id, c.source_id FROM decision.cases c"
                " JOIN event.events e ON e.event_id::text = c.source_id"
                " WHERE c.tenant_id = :t AND e.data->>'order_no' = :order_no"
            ),
            {"t": tenant_id, "order_no": CASE_ORDER_NO},
        )
    ).one()


async def _seed_object_id(
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


async def _manager1_id(db_session: AsyncSession) -> str:
    return str(
        (
            await db_session.execute(
                text("SELECT user_id FROM platform.users WHERE username = 'manager1'")
            )
        ).scalar_one()
    )


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
            "action_type": "expedite_purchase",
            "owner": "procurement_zhang",
            "owner_role": "PROCUREMENT",
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
    comment: str | None = None,
) -> httpx.Response:
    payload: dict = {"from_status": from_status, "to_status": to_status}
    if comment is not None:
        payload["comment"] = comment
    return await client.patch(
        f"{ACTIONS}/{action_id}/status", headers=headers, json=payload
    )


async def _decide_order_b(
    client: httpx.AsyncClient,
    manager: dict[str, str],
    case_id: UUID,
) -> dict:
    """manager 决策（EXPEDITE）+ 决策意见落证最小补建（ref_type=DECISION，
    W4-10 口径——决策记录本身不自动落证，消费方按 B.5 证据链补建）。"""
    decided = await client.post(
        f"{DECISIONS}/cases/{case_id}/records",
        headers=manager,
        json={
            "chosen_option": "EXPEDITE",
            "decision_type": "HUMAN",
            "comment": "同意加急采购，优先保交付",
        },
    )
    assert decided.status_code == 201, decided.text
    return decided.json()


async def _backfill_decision_evidence(
    client: httpx.AsyncClient,
    manager: dict[str, str],
    case_id: UUID,
    object_id: UUID,
) -> UUID:
    created = await client.post(
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
    assert created.status_code == 201, created.text
    return UUID(created.json()["evidence_id"])


# ---- ① 全链闭环：seed → tools → 回流 → 案例 → 决策 → 行动六步 → VERIFIED ----


async def test_full_closed_loop_seed_to_verified(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    # 幕前：seed 计数（快照 43 + 回流 10 + 场景 2 案例）
    assert (demo.fetched, demo.events_accepted, demo.case_created) == (
        SEED_FETCHED,
        SEED_RESULT_EVENTS,
        True,
    )

    # ① 总览：tools 缺口读数（订单 B 12 万 + X-100 需 1000；库存可用 3200）
    order = await client.get(f"{TOOLS}/orders/{CASE_ORDER_NO}", headers=DEV_HEADERS)
    assert order.status_code == 200, order.text
    order_body = order.json()
    assert order_body["amount"] == 120000.0
    x_line = next(
        line for line in order_body["lines"] if line["material_code"] == "X-100"
    )
    assert x_line["quantity"] == 1000.0
    assert order_body["evidence_hint"]["event_id"]

    inventory = await client.get(
        f"{TOOLS}/inventory", params={"material_code": "X-100"}, headers=DEV_HEADERS
    )
    assert inventory.status_code == 200, inventory.text
    assert inventory.json()["total_available"] == 3200.0
    assert len(inventory.json()["warehouses"]) == 2

    case_id, source_id = await _seed_case(db_session, default_tenant_id)
    detail = await client.get(f"{DECISIONS}/cases/{case_id}", headers=DEV_HEADERS)
    assert detail.status_code == 200, detail.text
    case_body = detail.json()
    assert case_body["risk_level"] == "P1"
    assert case_body["context"]["material_gap"] == 1000
    assert case_body["event"]["summary"] == "物料X缺口1000，预计延误5天"

    # ③ 证据链 verify：seed 态 RESULT 证据（ref RESULT ← 源事件）
    result_rows = await client.get(
        EVIDENCE,
        params={"ref_type": "RESULT", "ref_id": source_id},
        headers=DEV_HEADERS,
    )
    assert result_rows.status_code == 200, result_rows.text
    assert len(result_rows.json()["items"]) == 1
    verify = await client.get(
        f"{EVIDENCE}/{result_rows.json()['items'][0]['evidence_id']}/verify",
        headers=DEV_HEADERS,
    )
    assert verify.status_code == 200, verify.text
    assert verify.json()["valid"] is True

    # ④ 幕前：新风险事件建案例（场景 5：SO-2026-00126，无 seed 案例）
    s5_event_id = (
        await db_session.execute(
            text(
                "SELECT event_id FROM event.events"
                " WHERE tenant_id = :t AND data->>'order_no' = 'SO-2026-00126'"
                " AND event_type = 'capability.result.order_quality'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one()
    created_case = await client.post(
        f"{DECISIONS}/cases",
        headers=DEV_HEADERS,
        json={
            "question": "订单 SO-2026-00126 产品F库存不足，是否补料并通知客户？",
            "risk_level": "P1",
            "source_type": "capability.result",
            "source_id": str(s5_event_id),
        },
    )
    assert created_case.status_code == 201, created_case.text
    assert created_case.json()["case_no"].startswith("DC-")
    assert created_case.json()["status"] == "OPEN"

    # ④ HITL 审批：manager 决策 + 决策意见落证（最小补建）
    manager = await _login(client, "manager1")
    decided = await _decide_order_b(client, manager, case_id)
    assert decided["case_status"] == "DECIDED"
    object_id = await _seed_object_id(db_session, default_tenant_id, source_id)
    await _backfill_decision_evidence(client, manager, case_id, object_id)

    # ④ Action 闭环：六步到 VERIFIED（两步带 comment 落证）
    action = await _create_action(client, manager, case_id, "加急采购物料X 1000 件")
    action_id = action["action_id"]
    assert action["status"] == "PROPOSED"

    chain = [
        ("PROPOSED", "ASSIGNED", "指派给采购张三，限两日内反馈"),
        ("ASSIGNED", "ACCEPTED", None),
        ("ACCEPTED", "APPROVED", None),
        ("APPROVED", "EXECUTING", "采购下单完成，供应商 S-021 确认交期 10 天"),
        ("EXECUTING", "COMPLETED", None),
        ("COMPLETED", "VERIFIED", "到货 1000 件已入库，缺口闭环"),
    ]
    for from_status, to_status, comment in chain:
        resp = await _transition(
            client, manager, action_id, from_status, to_status, comment
        )
        assert resp.status_code == 200, f"{from_status}→{to_status}: {resp.text}"
        assert resp.json()["status"] == to_status

    detail_action = await client.get(f"{ACTIONS}/{action_id}", headers=manager)
    assert detail_action.status_code == 200, detail_action.text
    action_body = detail_action.json()
    assert action_body["status"] == "VERIFIED"
    assert action_body["allowed_to"] == []
    assert action_body["completion_time"] is not None
    assert action_body["verified_at"] is not None
    # verified_by = principal.id（JWT = 用户 UUID，与 memories.reviewed_by 同口径）
    assert action_body["verified_by"] == await _manager1_id(db_session)

    # comment 落证据（ref_type=ACTION；source_record_id={action_id}#{to_status}）
    action_evidence = await client.get(
        EVIDENCE,
        params={"ref_type": "ACTION", "ref_id": action_id},
        headers=DEV_HEADERS,
    )
    assert action_evidence.status_code == 200, action_evidence.text
    items = action_evidence.json()["items"]
    assert len(items) == 3  # ASSIGNED / EXECUTING / VERIFIED 三次带意见转移
    assert {item["source_record_id"] for item in items} == {
        f"{action_id}#ASSIGNED",
        f"{action_id}#EXECUTING",
        f"{action_id}#VERIFIED",
    }
    assert all(item["source_system"] == "edp" for item in items)

    # ⑤ 回总览：中枢回流 action.verified（幂等重放 deduplicated）
    reflow = {
        "events": [
            {
                "event_type": "action.verified",
                "object_id": str(object_id),
                "source_system": "edp",
                "occurred_at": "2026-09-18T03:00:00Z",
                "actor_type": "SERVICE",
                "actor_id": "edp",
                "result_type": "ACTION",
                "data": {
                    "order_no": CASE_ORDER_NO,
                    "action_id": action_id,
                    "summary": "行动已验证：加急采购物料X缺口闭环",
                },
            }
        ]
    }
    headers = {**DEV_HEADERS, "Idempotency-Key": "m4-accept:reflow:v1"}
    first = await client.post(f"{EVENTS}/batch", headers=headers, json=reflow)
    assert first.status_code == 200, first.text
    assert first.json()["accepted"] == 1
    assert first.json()["deduplicated"] is False

    replay = await client.post(f"{EVENTS}/batch", headers=headers, json=reflow)
    assert replay.status_code == 200, replay.text
    assert replay.json()["deduplicated"] is True  # 同 Idempotency-Key 存档命中

    reflowed = await client.get(
        f"{EVENTS}", params={"event_type": "action.verified"}, headers=DEV_HEADERS
    )
    assert reflowed.status_code == 200, reflowed.text
    assert reflowed.json()["total"] == 1

    # ⑤ 待办清空：决策已提交（pending 0）+ 行动已 VERIFIED（todos 不含）
    pending = await client.get(f"{EBMS}/decisions/pending", headers=DEV_HEADERS)
    assert pending.status_code == 200, pending.text
    # 场景 5 案例仍 OPEN（本用例只决策订单 B）→ total_pending == 1
    assert pending.json()["total_pending"] == 1
    assert pending.json()["items"][0]["question"].startswith("订单 SO-2026-00126")

    todos = await client.get(f"{EBMS}/todos", headers=DEV_HEADERS)
    assert todos.status_code == 200, todos.text
    todos_body = todos.json()
    assert [item["case_id"] for item in todos_body["pending_decisions"]] == [
        str(created_case.json()["case_id"])
    ]
    assert action_id not in {
        item["action_id"] for item in todos_body["pending_actions"]
    }


# ---- ② Human-Only 403：records（decision.records）+ EXECUTING（action.actions）----


async def test_human_only_service_denied_and_audited(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    case_id, _ = await _seed_case(db_session, default_tenant_id)

    # SERVICE Key 提交决策记录 → 403 GUARD_POLICY_DENIED（非 HUMAN）
    denied = await client.post(
        f"{DECISIONS}/cases/{case_id}/records",
        headers=DEV_HEADERS,
        json={"chosen_option": "EXPEDITE"},
    )
    assert denied.status_code == 403, denied.text
    error = denied.json()["error"]
    assert error["code"] == "GUARD_POLICY_DENIED"
    assert error["message"] == "该操作仅限人工执行"

    # 拒绝留痕：GUARD_DENIED 审计行（decision.records）
    record_rows = (
        (
            await db_session.execute(
                text(
                    "SELECT actor_type, resource_type, resource_id, detail"
                    " FROM platform.audit_logs"
                    " WHERE action = 'GUARD_DENIED' AND resource_type ="
                    " 'decision.records' AND actor_id = 'agent-hub'"
                )
            )
        )
        .mappings()
        .one()
    )
    assert record_rows["actor_type"] == "SERVICE"
    assert record_rows["resource_id"] == str(case_id)
    assert record_rows["detail"]["reason"] == "Human-Only"
    assert record_rows["detail"]["path"] == f"{DECISIONS}/cases/{case_id}/records"

    # SERVICE Key 走非 Human-Only 三步到 APPROVED（write:action scope 双轨）
    action = await _create_action(
        client, DEV_HEADERS, case_id, "加急采购物料X 1000 件"
    )
    action_id = action["action_id"]
    for from_status, to_status in (
        ("PROPOSED", "ASSIGNED"),
        ("ASSIGNED", "ACCEPTED"),
        ("ACCEPTED", "APPROVED"),
    ):
        resp = await _transition(
            client, DEV_HEADERS, action_id, from_status, to_status
        )
        assert resp.status_code == 200, resp.text

    # APPROVED→EXECUTING 为 Human-Only 边：SERVICE → 403 + 审计（action.actions）
    denied_exec = await _transition(
        client, DEV_HEADERS, action_id, "APPROVED", "EXECUTING"
    )
    assert denied_exec.status_code == 403, denied_exec.text
    assert denied_exec.json()["error"]["code"] == "GUARD_POLICY_DENIED"

    action_rows = (
        (
            await db_session.execute(
                text(
                    "SELECT resource_id, detail FROM platform.audit_logs"
                    " WHERE action = 'GUARD_DENIED' AND resource_type ="
                    " 'action.actions' AND actor_id = 'agent-hub'"
                )
            )
        )
        .mappings()
        .one()
    )
    assert action_rows["resource_id"] == action_id
    assert action_rows["detail"]["reason"] == "Human-Only"
    assert action_rows["detail"]["path"] == f"{ACTIONS}/{action_id}/status"

    # 守卫先于写：状态仍 APPROVED（未被 SERVICE 推进）
    detail = await client.get(f"{ACTIONS}/{action_id}", headers=DEV_HEADERS)
    assert detail.json()["status"] == "APPROVED"


# ---- ③ 非法转移 422：extra.allowed_to == PROPOSED 允许列表 ----


async def test_invalid_transition_422_with_allowed_to(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    case_id, _ = await _seed_case(db_session, default_tenant_id)
    manager = await _login(client, "manager1")
    action = await _create_action(client, manager, case_id, "启用替代料方案")

    resp = await _transition(
        client, manager, action["action_id"], "PROPOSED", "VERIFIED"
    )
    assert resp.status_code == 422, resp.text
    error = resp.json()["error"]
    assert error["code"] == "INVALID_TRANSITION"
    assert error["allowed_to"] == [
        {"to_status": "ASSIGNED", "human_only": False},
        {"to_status": "CANCELLED", "human_only": False},
        {"to_status": "REJECTED", "human_only": False},
    ]

    # 状态未变（拒绝不落任何转移）
    detail = await client.get(f"{ACTIONS}/{action['action_id']}", headers=manager)
    assert detail.json()["status"] == "PROPOSED"


# ---- ④ 并发 409：同 from_status 两请求仅一成功（乐观锁）----


async def test_concurrent_transition_single_winner(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    case_id, _ = await _seed_case(db_session, default_tenant_id)
    manager = await _login(client, "manager1")
    action = await _create_action(client, manager, case_id, "调整生产计划")
    action_id = action["action_id"]

    # 两请求同 from_status=PROPOSED（目标不同，均为合法边）→ 200/409 各一
    first, second = await asyncio.gather(
        _transition(client, manager, action_id, "PROPOSED", "ASSIGNED"),
        _transition(client, manager, action_id, "PROPOSED", "REJECTED"),
    )
    codes = sorted([first.status_code, second.status_code])
    assert codes == [200, 409], (first.text, second.text)
    loser = second if second.status_code == 409 else first
    assert loser.json()["error"]["code"] == "CONFLICT"

    # 终态 = 胜者目标（未撕裂）
    detail = await client.get(f"{ACTIONS}/{action_id}", headers=manager)
    assert detail.json()["status"] in {"ASSIGNED", "REJECTED"}


# ---- ⑤ ebms 口径：pending 含案例 / todos 三段随决策与 VERIFIED 变化 ----


async def test_ebms_pending_todos_lifecycle(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    case_id, _ = await _seed_case(db_session, default_tenant_id)
    manager = await _login(client, "manager1")

    # 决策前：pending 含订单 B 案例；todos 待决同源
    pending_before = await client.get(f"{EBMS}/decisions/pending", headers=DEV_HEADERS)
    assert pending_before.status_code == 200, pending_before.text
    before = pending_before.json()
    assert before["total_pending"] == 1
    assert before["items"][0]["case_id"] == str(case_id)
    assert before["items"][0]["case_no"].startswith("DC-")
    assert before["items"][0]["risk_level"] == "P1"

    action = await _create_action(client, manager, case_id, "加急采购物料X 1000 件")
    action_id = action["action_id"]

    todos_before = await client.get(f"{EBMS}/todos", headers=DEV_HEADERS)
    assert todos_before.status_code == 200, todos_before.text
    before_todos = todos_before.json()
    assert [item["case_id"] for item in before_todos["pending_decisions"]] == [
        str(case_id)
    ]
    assert action_id in {
        item["action_id"] for item in before_todos["pending_actions"]
    }
    # seed 风险事件 10 条仅场景 2 有关联案例 → 待确认异常 9 条
    assert len(before_todos["exceptions_to_confirm"]) == UNCASED_RISK_EVENTS

    # 决策后：pending 清零；行动非终态仍在 todos
    await _decide_order_b(client, manager, case_id)
    pending_after = await client.get(f"{EBMS}/decisions/pending", headers=DEV_HEADERS)
    assert pending_after.json()["total_pending"] == 0

    todos_open = await client.get(f"{EBMS}/todos", headers=DEV_HEADERS)
    open_todos = todos_open.json()
    assert open_todos["pending_decisions"] == []
    assert action_id in {
        item["action_id"] for item in open_todos["pending_actions"]
    }

    # 六步到 VERIFIED → todos 清空该行动（终态出待办）
    for from_status, to_status in (
        ("PROPOSED", "ASSIGNED"),
        ("ASSIGNED", "ACCEPTED"),
        ("ACCEPTED", "APPROVED"),
        ("APPROVED", "EXECUTING"),
        ("EXECUTING", "COMPLETED"),
        ("COMPLETED", "VERIFIED"),
    ):
        resp = await _transition(client, manager, action_id, from_status, to_status)
        assert resp.status_code == 200, resp.text

    todos_done = await client.get(f"{EBMS}/todos", headers=DEV_HEADERS)
    done_todos = todos_done.json()
    assert action_id not in {
        item["action_id"] for item in done_todos["pending_actions"]
    }
    assert len(done_todos["exceptions_to_confirm"]) == UNCASED_RISK_EVENTS


# ---- ⑥ 闭环聚合完整：event/steps（≥6）/evidence_chain 四层/actions.allowed_to ----


async def test_case_detail_aggregation_complete(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    case_id, source_id = await _seed_case(db_session, default_tenant_id)
    manager = await _login(client, "manager1")
    object_id = await _seed_object_id(db_session, default_tenant_id, source_id)

    await _decide_order_b(client, manager, case_id)
    await _backfill_decision_evidence(client, manager, case_id, object_id)

    # 行动一：走两步；行动二：仅创建（对照快照）
    a1 = await _create_action(client, manager, case_id, "加急采购物料X")
    await _transition(client, manager, a1["action_id"], "PROPOSED", "ASSIGNED")
    await _transition(client, manager, a1["action_id"], "ASSIGNED", "ACCEPTED")
    a2 = await _create_action(client, manager, case_id, "通知客户预计交期")

    detail = await client.get(f"{DECISIONS}/cases/{case_id}", headers=manager)
    assert detail.status_code == 200, detail.text
    body = detail.json()

    # event：source 事件摘要（场景 2 读数）
    assert body["event"]["event_id"] == source_id
    assert body["event"]["risk_level"] == "P1"
    assert body["event"]["summary"] == "物料X缺口1000，预计延误5天"

    # steps：EVENT + CASE_CREATED + DECISION + 每行动两节点 = 7（≥6）且升序
    steps = body["steps"]
    assert len(steps) == 7
    assert [step["occurred_at"] for step in steps] == sorted(
        step["occurred_at"] for step in steps
    )
    assert steps[0]["step_type"] == "EVENT"
    decision_steps = [s for s in steps if s["step_type"] == "DECISION"]
    assert len(decision_steps) == 1
    assert decision_steps[0]["human_only"] is True
    assert "EXPEDITE" in decision_steps[0]["title"]

    # actions：全量 + allowed_to（ACCEPTED 目录）
    actions = {item["action_id"]: item for item in body["actions"]}
    assert set(actions) == {a1["action_id"], a2["action_id"]}
    assert actions[a1["action_id"]]["status"] == "ACCEPTED"
    assert actions[a1["action_id"]]["allowed_to"] == [
        {"to_status": "APPROVED", "human_only": False},
        {"to_status": "CANCELLED", "human_only": False},
    ]

    # evidence_chain：四层各 ≥1 + SOURCE 投影去重
    chain = body["evidence_chain"]
    by_layer: dict[str, list[dict]] = {}
    for node in chain:
        by_layer.setdefault(node["layer"], []).append(node)
    for layer in ("RESULT", "DECISION", "EVIDENCE", "SOURCE"):
        assert len(by_layer[layer]) >= 1, layer
    assert any(
        node["source_record_id"] == f"result:{source_id}"
        for node in by_layer["RESULT"]
    )
    assert any(
        node["source_record_id"] == f"decision:{case_id}"
        for node in by_layer["DECISION"]
    )
    source_nodes = by_layer["SOURCE"]
    assert all("evidence_id" not in node for node in source_nodes)
    projected = {
        (node["source_system"], node["source_record_id"])
        for layer in ("RESULT", "DECISION", "EVIDENCE")
        for node in by_layer[layer]
    }
    assert {
        (node["source_system"], node["source_record_id"]) for node in source_nodes
    } == projected
    assert len(source_nodes) == len(projected)
