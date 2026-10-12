"""V1.2 事实与结果层集成测试（T17~T21）：Result / OFFICIAL 回写 / 门禁。

覆盖：
1. Result 创建：无证据 400（Result→Evidence 100% 硬约束）/ 有证据 201 +
   RESULT links + 列表/详情；
2. verify：manager（result:write）核验 200 VERIFIED；SERVICE 403；
   权限矩阵：analyst 读 200 / 写 403；
3. OFFICIAL 回写（T19/T20）：A2+A3 审核后 business_objects 三列回写
   （layer_status=CURATED / official_version / lineage_id）+ lineage 行
   （source_record_id + review refs）+ OBJECT_OFFICIAL 审计；archive →
   ARCHIVED + OBJECT_ARCHIVED 审计；
4. lineage 读 API（governance:read 轨道）；
5. tools official_only 门禁（T21）：seed 后默认 404/空列表；
   official_only=false 全量；审核一个订单后默认仅可见该订单。

会话形态：应用引擎 = conftest.app_role_engine（edp_app，FORCE RLS）；断言
以 migrator db_session 直查。清场：purge（0015 起含 result/governance.lineage）
+ 本模块审计行。
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

ORDER_NO = "SO-2026-00131"


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
async def _clean_fact_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    yield
    await demo_service.purge_tenant_business_data(db_session, default_tenant_id)
    await db_session.execute(
        text(
            "DELETE FROM platform.audit_logs WHERE tenant_id = :t"
            " AND (resource_type IN ('result.results', 'results',"
            " 'master.business_objects') OR action IN ('OBJECT_OFFICIAL',"
            " 'OBJECT_ARCHIVED'))"
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


async def _seed(app_role_engine: AsyncEngine, tenant_id: UUID) -> None:
    await demo_service.seed(app_role_engine, tenant_id)


async def _order_object_and_evidence(
    db_session: AsyncSession, tid: UUID
) -> tuple[UUID, UUID]:
    row = (
        await db_session.execute(
            text(
                "SELECT bo.object_id,"
                " (SELECT er.evidence_id FROM evidence.records er"
                "   WHERE er.object_id = bo.object_id LIMIT 1) AS evidence_id"
                " FROM master.business_objects bo WHERE bo.tenant_id = :t"
                " AND bo.source_id = :s"
            ),
            {"t": tid, "s": ORDER_NO},
        )
    ).one()
    return row.object_id, row.evidence_id


async def _admission_of(db_session: AsyncSession, tid: UUID) -> tuple[UUID, str]:
    row = (
        await db_session.execute(
            text(
                "SELECT a.admission_id, a.state FROM governance.admission_records a"
                " JOIN master.business_objects bo ON bo.object_id = a.object_id"
                " WHERE a.tenant_id = :t AND bo.source_id = :s"
            ),
            {"t": tid, "s": ORDER_NO},
        )
    ).one()
    return row.admission_id, row.state


# ---- 1. Result 创建：无证据 400 / 有证据 201 + RESULT links ----


async def test_result_create_requires_evidence_and_links(
    client: httpx.AsyncClient,
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await _seed(app_role_engine, default_tenant_id)
    headers = await _login(client, "admin")
    object_id, evidence_id = await _order_object_and_evidence(
        db_session, default_tenant_id
    )

    # 无证据 → 400 VALIDATION_ERROR（pydantic min_length=1 经运行时映射 400，
    # 口径同仓库 422→400 惯例）
    resp = await client.post(
        f"{BASE}/results",
        headers=headers,
        json={
            "result_type": "Delivery.OrderDeliveryRisk",
            "object_id": str(object_id),
            "domain": "DELIVERY",
            "value": {"delay_days": 7},
            "status": "HIGH_RISK",
            "evidence_refs": [],
            "generated_by": "delivery-service",
        },
    )
    assert resp.status_code == 400, resp.text
    assert "evidence_refs" in resp.text

    # 有证据 → 201 + RESULT links
    resp = await client.post(
        f"{BASE}/results",
        headers=headers,
        json={
            "result_type": "Delivery.OrderDeliveryRisk",
            "object_id": str(object_id),
            "domain": "DELIVERY",
            "period": "AEOS-P10",
            "value": {"delay_days": 7},
            "status": "HIGH_RISK",
            "evidence_refs": [str(evidence_id)],
            "generated_by": "delivery-service",
        },
    )
    assert resp.status_code == 201, resp.text
    result_id = resp.json()["result_id"]
    assert (
        await db_session.execute(
            text(
                "SELECT count(*) FROM evidence.links WHERE tenant_id = :t"
                " AND ref_type = 'RESULT' AND ref_id = :r"
            ),
            {"t": default_tenant_id, "r": result_id},
        )
    ).scalar_one() == 1

    # 列表/详情
    listed = await client.get(f"{BASE}/results", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1
    detail = await client.get(f"{BASE}/results/{result_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["result_type"] == "Delivery.OrderDeliveryRisk"

    # 对象不存在 → 400
    resp = await client.post(
        f"{BASE}/results",
        headers=headers,
        json={
            "result_type": "Delivery.OrderDeliveryRisk",
            "object_id": "00000000-0000-0000-0000-000000000001",
            "domain": "DELIVERY",
            "status": "HIGH_RISK",
            "evidence_refs": [str(evidence_id)],
            "generated_by": "delivery-service",
        },
    )
    assert resp.status_code == 400, resp.text


# ---- 2. verify：Human-Only + 权限矩阵 ----


async def test_result_verify_and_permissions(
    client: httpx.AsyncClient,
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await _seed(app_role_engine, default_tenant_id)
    admin = await _login(client, "admin")
    analyst = await _login(client, "analyst1")
    manager = await _login(client, "manager1")
    object_id, evidence_id = await _order_object_and_evidence(
        db_session, default_tenant_id
    )
    resp = await client.post(
        f"{BASE}/results",
        headers=admin,
        json={
            "result_type": "Delivery.OrderDeliveryRisk",
            "object_id": str(object_id),
            "domain": "DELIVERY",
            "status": "HIGH_RISK",
            "evidence_refs": [str(evidence_id)],
            "generated_by": "delivery-service",
        },
    )
    assert resp.status_code == 201, resp.text
    result_id = resp.json()["result_id"]

    # analyst：读 200 / 写 403
    assert (
        await client.get(f"{BASE}/results/{result_id}", headers=analyst)
    ).status_code == 200
    assert (
        await client.post(
            f"{BASE}/results",
            headers=analyst,
            json={
                "result_type": "X.Y",
                "object_id": str(object_id),
                "domain": "DELIVERY",
                "status": "N",
                "evidence_refs": [str(evidence_id)],
                "generated_by": "x",
            },
        )
    ).status_code == 403

    # SERVICE verify → 403（Human-Only）
    resp = await client.post(
        f"{BASE}/results/{result_id}/verify", headers=DEV_HEADERS
    )
    assert resp.status_code == 403

    # manager verify → 200 VERIFIED
    resp = await client.post(
        f"{BASE}/results/{result_id}/verify", headers=manager
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["verified_status"] == "VERIFIED"
    assert resp.json()["verified_by"] is not None  # manager1 的 user_id


# ---- 3. OFFICIAL 回写（T19/T20）+ archive ----


async def test_official_marks_business_object_and_lineage(
    client: httpx.AsyncClient,
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await _seed(app_role_engine, default_tenant_id)
    headers = await _login(client, "admin")
    admission_id, state = await _admission_of(db_session, default_tenant_id)
    assert state == "CLASSIFIED"

    resp = await client.post(
        f"{BASE}/governance/admission/{admission_id}/source-review",
        headers=headers,
        json={"decision": "APPROVED"},
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        f"{BASE}/governance/admission/{admission_id}/management-review",
        headers=headers,
        json={"decision": "APPROVED"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "OFFICIAL"

    # business_objects 三列回写
    bo = (
        await db_session.execute(
            text(
                "SELECT layer_status, official_version, lineage_id"
                " FROM master.business_objects WHERE tenant_id = :t"
                " AND source_id = :s"
            ),
            {"t": default_tenant_id, "s": ORDER_NO},
        )
    ).one()
    assert bo.layer_status == "CURATED"
    assert bo.official_version == str(admission_id)
    assert bo.lineage_id is not None

    # lineage 行（source_record_id + 两级 review refs + official_version）
    lineage = (
        await db_session.execute(
            text(
                "SELECT source_record_id, source_review_ref,"
                " management_review_ref, official_version, operator"
                " FROM governance.lineage WHERE tenant_id = :t AND lineage_id = :l"
            ),
            {"t": default_tenant_id, "l": bo.lineage_id},
        )
    ).one()
    assert lineage.source_record_id == ORDER_NO
    assert lineage.source_review_ref is not None
    assert lineage.management_review_ref is not None
    assert lineage.official_version == str(admission_id)
    assert lineage.operator is not None  # HUMAN principal.id（admin 用户 id）

    # OBJECT_OFFICIAL 审计
    assert (
        await db_session.execute(
            text(
                "SELECT count(*) FROM platform.audit_logs WHERE tenant_id = :t"
                " AND action = 'OBJECT_OFFICIAL'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one() == 1

    # lineage 读 API（governance:read 轨道）
    listed = await client.get(
        f"{BASE}/lineage",
        headers=headers,
        params={"source_record_id": ORDER_NO},
    )
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 1
    assert listed.json()[0]["official_version"] == str(admission_id)

    # archive → ARCHIVED + OBJECT_ARCHIVED 审计
    resp = await client.post(
        f"{BASE}/governance/admission/{admission_id}/archive", headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "ARCHIVED"
    bo = (
        await db_session.execute(
            text(
                "SELECT layer_status FROM master.business_objects"
                " WHERE tenant_id = :t AND source_id = :s"
            ),
            {"t": default_tenant_id, "s": ORDER_NO},
        )
    ).one()
    assert bo.layer_status == "ARCHIVED"
    assert (
        await db_session.execute(
            text(
                "SELECT count(*) FROM platform.audit_logs WHERE tenant_id = :t"
                " AND action = 'OBJECT_ARCHIVED'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one() == 1


# ---- 4. tools official_only 门禁（T21） ----


async def test_tools_official_only_gate(
    client: httpx.AsyncClient,
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await _seed(app_role_engine, default_tenant_id)

    # 默认（true）：无 OFFICIAL 数据 → 详情 404 / 列表空
    resp = await client.get(f"{BASE}/tools/orders/{ORDER_NO}", headers=DEV_HEADERS)
    assert resp.status_code == 404, resp.text
    listed = await client.get(f"{BASE}/tools/orders", headers=DEV_HEADERS)
    assert listed.status_code == 200
    assert listed.json()["items"] == []

    # official_only=false：全量可见（过渡期开关）
    resp = await client.get(
        f"{BASE}/tools/orders/{ORDER_NO}",
        params={"official_only": "false"},
        headers=DEV_HEADERS,
    )
    assert resp.status_code == 200, resp.text

    # 审核一个订单至 OFFICIAL → 默认仅可见该订单
    headers = await _login(client, "admin")
    admission_id, _ = await _admission_of(db_session, default_tenant_id)
    assert (
        await client.post(
            f"{BASE}/governance/admission/{admission_id}/source-review",
            headers=headers,
            json={"decision": "APPROVED"},
        )
    ).status_code == 200
    assert (
        await client.post(
            f"{BASE}/governance/admission/{admission_id}/management-review",
            headers=headers,
            json={"decision": "APPROVED"},
        )
    ).status_code == 200

    resp = await client.get(f"{BASE}/tools/orders/{ORDER_NO}", headers=DEV_HEADERS)
    assert resp.status_code == 200, resp.text
    listed = await client.get(f"{BASE}/tools/orders", headers=DEV_HEADERS)
    assert [item["order_no"] for item in listed.json()["items"]] == [ORDER_NO]
