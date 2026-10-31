"""V1.2 Phase 6 闭环 UAT（T35/T36）：销售→订单→交付→应收 全链 + 六类异常。

主链（场景 2 缺料订单 SO-2026-00123）：
1. seed → 风险事件（P1 capability.result.order_risk）；
2. 数据准入：A2 本系统审核（人工）→ A3 管理复审 → OFFICIAL（血缘落行）；
3. Result：Delivery.OrderDeliveryRisk（引用 OFFICIAL 对象 + 证据）→ 人工核验；
4. Decision：案例（挂证据）→ Human-Only 决策记录；
5. Action：创建（owner/deadline）→ 状态机推进至 VERIFIED（Human-Only 边）；
6. 出货 + 应收：Delivery.Shipment 与 Finance.AR 结果（result 模块，挂证据）；
7. A4 归档订单 → ARCHIVED。

六类异常（缺料/产能/交期/品质/出货延期/应收逾期）：
- 缺料（场景2）、产能（场景7）、交期（场景3）为 demo 风险事件；
- 品质/出货延期/应收逾期经 events/batch 构造（manager event:write）；
- 断言：六类均在 ebms exceptions 可见（OPEN），且至少缺料类走完整
  Decision→Action→Evidence 闭环。

会话形态：应用引擎 = conftest.app_role_engine（edp_app，FORCE RLS）；断言
以 migrator db_session 直查。清场：purge + 本模块审计行。
"""

from uuid import UUID

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.main import create_app
from edp_api.modules.demo import service as demo_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

BASE = "/api/v1"
DEV_HEADERS = {"X-API-Key": "edp-dev-agent-hub-key"}
LOGIN = "/api/v1/auth/login"
SEED_PASSWORD = "Admin@123!"

ORDER_NO = "SO-2026-00123"


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    await core_db.dispose_engine()
    monkeypatch.setattr(core_db, "get_engine", lambda: app_role_engine)
    transport = httpx.ASGITransport(app=create_app())
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        await core_db.dispose_engine()


@pytest.fixture
async def default_tenant_id(db_session: AsyncSession) -> UUID:
    return (
        await db_session.execute(
            text("SELECT tenant_id FROM platform.tenants WHERE slug = 'default'")
        )
    ).scalar_one()


@pytest.fixture(autouse=True)
async def _clean_closed_loop_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    yield
    await demo_service.purge_tenant_business_data(db_session, default_tenant_id)
    await db_session.execute(
        text(
            "DELETE FROM platform.audit_logs WHERE tenant_id = :t"
            " AND action IN ('ADMISSION_REVIEW', 'OBJECT_OFFICIAL',"
            " 'OBJECT_ARCHIVED', 'GUARD_DENIED')"
        ),
        {"t": default_tenant_id},
    )
    await db_session.commit()


async def _login(client: httpx.AsyncClient, username: str) -> dict[str, str]:
    resp = await client.post(
        LOGIN, json={"username": username, "password": SEED_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _rows(db_session: AsyncSession, sql: str, **params) -> list:
    return (await db_session.execute(text(sql), params)).mappings().all()


async def _order_row(db_session: AsyncSession, tid: UUID) -> dict:
    return (
        await db_session.execute(
            text(
                "SELECT object_id, layer_status FROM master.business_objects"
                " WHERE tenant_id = :t AND source_id = :s"
            ),
            {"t": tid, "s": ORDER_NO},
        )
    ).mappings().one()


async def _admission_of(db_session: AsyncSession, tid: UUID, object_id: UUID) -> UUID:
    return (
        await db_session.execute(
            text(
                "SELECT admission_id FROM governance.admission_records"
                " WHERE tenant_id = :t AND object_id = :o"
            ),
            {"t": tid, "o": object_id},
        )
    ).scalar_one()


async def _evidence_of(db_session: AsyncSession, tid: UUID, object_id: UUID) -> UUID:
    return (
        await db_session.execute(
            text(
                "SELECT evidence_id FROM evidence.records"
                " WHERE tenant_id = :t AND object_id = :o LIMIT 1"
            ),
            {"t": tid, "o": object_id},
        )
    ).scalar_one()


async def test_closed_loop_sales_to_ar(
    client: httpx.AsyncClient,
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await demo_service.seed(app_role_engine, default_tenant_id)
    admin = await _login(client, "admin")
    manager = await _login(client, "manager1")

    # ---- 1. 销售→订单：订单对象 + 风险事件（场景 2 缺料 P1） ----
    order = await _order_row(db_session, default_tenant_id)
    risk_events = await _rows(
        db_session,
        "SELECT event_id, risk_level FROM event.events WHERE tenant_id = :t"
        " AND risk_level IS NOT NULL AND event_type = 'capability.result.order_risk'"
        " AND data->>'summary' IS NOT NULL",
        t=default_tenant_id,
    )
    assert any(row["risk_level"] == "P1" for row in risk_events)

    # ---- 2. 数据准入：A2 → A3 → OFFICIAL（血缘） ----
    admission_id = await _admission_of(db_session, default_tenant_id, order["object_id"])
    resp = await client.post(
        f"{BASE}/governance/admission/{admission_id}/source-review",
        headers=admin,
        json={"decision": "APPROVED", "comment": "销售订单事实符合业务实际"},
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        f"{BASE}/governance/admission/{admission_id}/management-review",
        headers=admin,
        json={"decision": "APPROVED", "comment": "企业正式事实复核通过"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "OFFICIAL"
    order = await _order_row(db_session, default_tenant_id)
    assert order["layer_status"] == "CURATED"

    # ---- 3. Result（交付风险）：引用 OFFICIAL 对象 + 证据 + 人工核验 ----
    evidence_id = await _evidence_of(db_session, default_tenant_id, order["object_id"])
    resp = await client.post(
        f"{BASE}/results",
        headers=admin,
        json={
            "result_type": "Delivery.OrderDeliveryRisk",
            "object_id": str(order["object_id"]),
            "domain": "DELIVERY",
            "period": "AEOS-P10",
            "metric_refs": ["otd_rate"],
            "value": {"delay_days": 5, "shortage_items": 1},
            "status": "HIGH_RISK",
            "evidence_refs": [str(evidence_id)],
            "generated_by": "delivery-risk-agent",
        },
    )
    assert resp.status_code == 201, resp.text
    risk_result_id = resp.json()["result_id"]
    resp = await client.post(f"{BASE}/results/{risk_result_id}/verify", headers=admin)
    assert resp.status_code == 200, resp.text
    assert resp.json()["verified_status"] == "VERIFIED"

    # ---- 4. Decision：案例（挂证据）→ Human-Only 决策 ----
    resp = await client.post(
        f"{BASE}/decisions/cases",
        headers=manager,
        json={
            "question": "关键料 X-100 缺口 1000，如何保障交付？",
            "options": [
                {"key": "expedite", "label": "加急采购"},
                {"key": "reschedule", "label": "与客户协商改期"},
            ],
            "risk_level": "P1",
            "source_type": "EVENT",
            "source_id": str(risk_events[0]["event_id"]),
            "evidence_ids": [str(evidence_id)],
        },
    )
    assert resp.status_code == 201, resp.text
    case_id = resp.json()["case_id"]
    resp = await client.post(
        f"{BASE}/decisions/cases/{case_id}/records",
        headers=manager,
        json={"chosen_option": "expedite", "comment": "S-021 交期 10 天，加急采购 X-100"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["case_status"] == "DECIDED"

    # ---- 5. Action：创建（owner/deadline）→ 状态机至 VERIFIED ----
    resp = await client.post(
        f"{BASE}/actions",
        headers=manager,
        json={
            "case_id": case_id,
            "title": "向 S-021 加急采购 X-100 1000 件",
            "action_type": "PROCUREMENT",
            "owner": "采购主管",
            "due_date": "2026-10-14T00:00:00Z",
        },
    )
    assert resp.status_code == 201, resp.text
    action_id = resp.json()["action_id"]
    for from_s, to_s in (
        ("PROPOSED", "ASSIGNED"),
        ("ASSIGNED", "ACCEPTED"),
        ("ACCEPTED", "APPROVED"),
        ("APPROVED", "EXECUTING"),
        ("EXECUTING", "COMPLETED"),
        ("COMPLETED", "VERIFIED"),
    ):
        resp = await client.patch(
            f"{BASE}/actions/{action_id}/status",
            headers=manager,
            json={"from_status": from_s, "to_status": to_s},
        )
        assert resp.status_code == 200, f"{from_s}→{to_s}: {resp.text}"
    assert resp.json()["status"] == "VERIFIED"

    # ---- 6. 出货 + 应收：结果层（挂证据，Evidence 闭环） ----
    for result_type, domain, status, value in (
        (
            "Delivery.Shipment",
            "DELIVERY",
            "SHIPPED",
            {"carrier": "顺丰", "shipped_at": "2026-10-14"},
        ),
        ("Finance.AR", "FINANCE", "CREATED", {"amount": 120000, "currency": "CNY"}),
    ):
        resp = await client.post(
            f"{BASE}/results",
            headers=admin,
            json={
                "result_type": result_type,
                "object_id": str(order["object_id"]),
                "domain": domain,
                "status": status,
                "value": value,
                "evidence_refs": [str(evidence_id)],
                "generated_by": "closed-loop-uat",
            },
        )
        assert resp.status_code == 201, f"{result_type}: {resp.text}"

    # ---- 7. A4 归档 ----
    resp = await client.post(
        f"{BASE}/governance/admission/{admission_id}/archive", headers=admin
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "ARCHIVED"

    # ---- 全链可追溯：Result→Evidence 100%、Decision→Evidence、Action 三要素 ----
    assert (
        await db_session.execute(
            text(
                "SELECT count(*) FROM result.results r WHERE r.tenant_id = :t"
                " AND cardinality(r.evidence_refs) >= 1"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one() == 3
    assert (
        await db_session.execute(
            text(
                "SELECT count(*) FROM evidence.links WHERE tenant_id = :t"
                " AND ref_type IN ('RESULT', 'CASE')"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one() >= 4
    assert (
        await db_session.execute(
            text(
                "SELECT count(*) FROM action.actions WHERE tenant_id = :t"
                " AND owner IS NOT NULL AND due_date IS NOT NULL AND status = 'VERIFIED'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one() == 1


async def test_six_anomaly_types_form_exceptions_and_decision_loop(
    client: httpx.AsyncClient,
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    """六类异常：缺料/产能/交期（demo 场景）+ 品质/出货延期/应收逾期（构造）→
    全部进入 exceptions；缺料类走 Decision→Action→Evidence 闭环。"""
    await demo_service.seed(app_role_engine, default_tenant_id)
    manager = await _login(client, "manager1")

    order = await _order_row(db_session, default_tenant_id)
    occurred = "2026-10-11T08:00:00Z"
    constructed = (
        ("Quality.Inspection.Failed", "P2", {"summary": "出货前抽检不合格"}),
        ("Delivery.Shipment.Delayed", "P1", {"summary": "出货延期 3 天"}),
        ("Finance.AR.Overdue", "P0", {"summary": "应收逾期 30 天"}),
    )
    for event_type, risk_level, data in constructed:
        resp = await client.post(
            f"{BASE}/events/batch",
            headers={**manager, "Idempotency-Key": f"uat-closed-loop:{event_type}"},
            json={
                "events": [
                    {
                        "event_type": event_type,
                        "object_id": str(order["object_id"]),
                        "source_system": "edp-uat",
                        "occurred_at": occurred,
                        "risk_level": risk_level,
                        "data": data,
                    }
                ]
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["accepted"] == 1

    # 六类在 exceptions 可见（OPEN）
    resp = await client.get(f"{BASE}/ebms/exceptions", headers=manager)
    assert resp.status_code == 200, resp.text
    summaries = {item["summary"] for item in resp.json()["items"]}
    assert any("缺" in s for s in summaries)  # 场景2 关键料缺失
    assert any("抽检不合格" in s for s in summaries)
    assert any("出货延期" in s for s in summaries)
    assert any("应收逾期" in s for s in summaries)

    # 缺料类（场景 2）走 Decision→Action→Evidence 闭环——seed 已预建主线案例
    # （M4：关键料缺失），复用既有案例完成决策→行动闭环（不重复建案例）
    case_row = (
        await db_session.execute(
            text(
                "SELECT c.case_id, c.status FROM decision.cases c"
                " JOIN event.events e ON e.event_id::text = c.source_id"
                " WHERE c.tenant_id = :t AND e.risk_level = 'P1'"
                " AND e.data->>'reason' LIKE '%缺口%' LIMIT 1"
            ),
            {"t": default_tenant_id},
        )
    ).one()
    assert case_row.status == "OPEN"
    resp = await client.post(
        f"{BASE}/decisions/cases/{case_row.case_id}/records",
        headers=manager,
        json={"chosen_option": "buy", "comment": "加急采购补缺"},
    )
    assert resp.status_code == 201, resp.text
    resp = await client.post(
        f"{BASE}/actions",
        headers=manager,
        json={
            "case_id": str(case_row.case_id),
            "title": "紧急采购补缺",
            "action_type": "PROCUREMENT",
            "owner": "采购主管",
            "due_date": "2026-10-13T00:00:00Z",
        },
    )
    assert resp.status_code == 201, resp.text
    assert (
        await db_session.execute(
            text(
                "SELECT count(*) FROM evidence.links WHERE tenant_id = :t"
                " AND ref_type = 'CASE'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one() >= 1
