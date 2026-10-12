"""V1.2 经营结果层集成测试（T23~T26）：Metric Registry / Period / Value
Ledger / EBMS 指标走 Registry。

覆盖：
1. metric 注册 + 同 code 版本化（旧版本收 effective_to）+ 计量值 upsert；
2. period API：AEOS 窗口 + 周期枚举；
3. value ledger 创建（delta 派生）+ Human-Only 核验 + 权限矩阵
   （analyst metric:manage 403）；
4. EBMS 指标走 Registry：seed 后 /ebms/reports/summary kpis 与既有口径
   一致（on_time_delivery 91.2 等），且 registry 行存在（T26 双写）。

会话形态：应用引擎 = conftest.app_role_engine（edp_app，FORCE RLS）；断言
以 migrator db_session 直查。清场：purge（0016 起含 metric/value 段）。
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

METRIC_PAYLOAD = {
    "code": "otd_rate",
    "name": "准时交付率",
    "business_definition": "按承诺日期计算的准时交付订单比例",
    "owner": "DELIVERY",
    "definition_owner": "DELIVERY",
    "definition_source": "DOMAIN",
    "target_owner": "M01_KERNEL",
    "period_rule": "AEOS Operating Window",
    "unit": "%",
}


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
async def _clean_metric_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    yield
    await demo_service.purge_tenant_business_data(db_session, default_tenant_id)
    await db_session.execute(
        text(
            "DELETE FROM platform.audit_logs WHERE tenant_id = :t"
            " AND (resource_type IN ('metric.metrics', 'metric_values',"
            " 'metric.metric_values', 'value.value_ledger', 'value_ledger')"
            " OR action = 'GUARD_DENIED')"
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


# ---- 1. metric 注册 + 版本化 + 计量值 ----


async def test_metric_registry_versioning_and_values(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    headers = await _login(client, "admin")

    resp = await client.post(f"{BASE}/metrics", headers=headers, json=METRIC_PAYLOAD)
    assert resp.status_code == 201, resp.text
    assert resp.json()["version"] == 1
    metric_id = resp.json()["metric_id"]

    # 同 code 新版本：旧版本收 effective_to
    resp = await client.post(
        f"{BASE}/metrics",
        headers=headers,
        json={**METRIC_PAYLOAD, "formula": "on_time_orders/total_orders"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["version"] == 2
    rows = (
        await db_session.execute(
            text(
                "SELECT version, effective_to FROM metric.metrics"
                " WHERE tenant_id = :t AND code = 'otd_rate' ORDER BY version"
            ),
            {"t": default_tenant_id},
        )
    ).all()
    assert len(rows) == 2
    assert rows[0].effective_to is not None  # v1 已收口
    assert rows[1].effective_to is None

    # 计量值 upsert（同 period 覆盖）
    payload = {"period": "2026-W40", "value": 91.2, "source": "demo"}
    resp = await client.post(
        f"{BASE}/metrics/{metric_id}/values", headers=headers, json=payload
    )
    assert resp.status_code == 201, resp.text
    resp = await client.post(
        f"{BASE}/metrics/{metric_id}/values",
        headers=headers,
        json={**payload, "value": 92.0},
    )
    assert resp.status_code == 201, resp.text
    values = (
        await db_session.execute(
            text(
                "SELECT count(*), max(value) FROM metric.metric_values"
                " WHERE tenant_id = :t AND metric_id = :m"
            ),
            {"t": default_tenant_id, "m": metric_id},
        )
    ).one()
    assert values.count == 1
    assert float(values.max) == 92.0

    # analyst：读 200 / manage 403
    analyst = await _login(client, "analyst1")
    assert (await client.get(f"{BASE}/metrics", headers=analyst)).status_code == 200
    resp = await client.post(f"{BASE}/metrics", headers=analyst, json=METRIC_PAYLOAD)
    assert resp.status_code == 403


# ---- 2. period API ----


async def test_period_aeos_api(
    client: httpx.AsyncClient, default_tenant_id: UUID
) -> None:
    headers = await _login(client, "analyst1")
    resp = await client.get(
        f"{BASE}/periods/aeos", headers=headers, params={"date": "2026-10-10"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["label"] == "AEOS-2026-09"
    assert body["start"] == "2026-09-16"
    assert body["end"] == "2026-10-15"

    resp = await client.get(f"{BASE}/periods/aeos", headers=headers)
    assert resp.status_code == 200

    resp = await client.get(f"{BASE}/periods/kinds", headers=headers)
    assert resp.status_code == 200
    kinds = {item["kind"] for item in resp.json()}
    assert {"DAILY", "WEEKLY", "MONTHLY", "AEOS", "CUSTOM", "ROLLING_7D", "ROLLING_30D"} <= kinds


# ---- 3. value ledger ----


async def test_value_ledger_create_and_verify(
    client: httpx.AsyncClient,
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await demo_service.seed(app_role_engine, default_tenant_id)
    admin = await _login(client, "admin")
    evidence_id = (
        await db_session.execute(
            text("SELECT evidence_id FROM evidence.records WHERE tenant_id = :t LIMIT 1"),
            {"t": default_tenant_id},
        )
    ).scalar_one()

    resp = await client.post(
        f"{BASE}/value-ledger",
        headers=admin,
        json={
            "baseline_ref": "库存账龄报告-2026Q3",
            "initiative_ref": "库存优化项目",
            "metric_ref": "inventory_turnover",
            "before_value": 8500000,
            "after_value": 6900000,
            "evidence_refs": [str(evidence_id)],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert float(body["delta"]) == -1600000.0  # after-before 派生
    value_id = body["value_id"]

    # SERVICE verify → 403（Human-Only）
    assert (
        await client.post(f"{BASE}/value-ledger/{value_id}/verify", headers=DEV_HEADERS)
    ).status_code == 403

    # manager 无 metric:manage → 403；admin verify → 200（metric:manage）
    manager = await _login(client, "manager1")
    assert (
        await client.post(
            f"{BASE}/value-ledger/{value_id}/verify", headers=manager
        )
    ).status_code == 403
    resp = await client.post(
        f"{BASE}/value-ledger/{value_id}/verify", headers=admin
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["verified_by"] is not None

    # 列表（metric_ref 过滤）
    listed = await client.get(
        f"{BASE}/value-ledger", headers=admin, params={"metric_ref": "inventory_turnover"}
    )
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1


# ---- 4. EBMS 指标走 Registry（T26 双写） ----


async def test_ebms_kpis_serve_from_metric_registry(
    client: httpx.AsyncClient,
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await demo_service.seed(app_role_engine, default_tenant_id)
    headers = await _login(client, "manager1")

    # registry 行存在（3 指标 + 6 计量值，T26 双写）
    metrics = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM metric.metrics WHERE tenant_id = :t"
                " AND definition_source = 'DOMAIN' AND target_owner = 'M01_KERNEL'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one()
    assert metrics == 3

    resp = await client.get(f"{BASE}/ebms/reports/summary", headers=headers)
    assert resp.status_code == 200, resp.text
    kpis = resp.json()["kpis"]
    by_code = {item["code"]: item for item in kpis}
    assert by_code["on_time_delivery"]["value"] == 91.2
    assert by_code["inventory_turnover"]["value"] == 7.2
    assert by_code["risk_closure_rate"]["value"] == 85.0
