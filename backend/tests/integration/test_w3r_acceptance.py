"""W3R 聚合验收测试（M3R 出口条件）：注册中心 / Trace / Memory / 产能 / 限流+用量。

按 `docs/demo/m3-demo.md`「W3 补齐」段的调用序列逐段断言（①~⑤），与各模块
集成测试互补：本文件以「演示脚本视角」端到端串起跨模块链路。

应用引擎 = conftest.app_role_engine（edp_app，FORCE RLS）；conftest 的
autouse `_relax_rate_limit` 每用例复位配额与令牌桶。清场：本模块造的行
（catalog/trace/memory/capacity/usage）+ 审计行。
"""

import asyncio
from decimal import Decimal
from uuid import UUID, uuid4

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
DEV_KEY = "edp-dev-agent-hub-key"
DEV_HEADERS = {"X-API-Key": DEV_KEY}
LOGIN = "/api/v1/auth/login"
SEED_PASSWORD = "Admin@123!"


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
async def _clean_w3r_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    yield
    await db_session.execute(
        text("DELETE FROM platform.skills WHERE tenant_id = :t"),
        {"t": default_tenant_id},
    )
    await db_session.execute(
        text("DELETE FROM platform.capabilities WHERE tenant_id = :t"),
        {"t": default_tenant_id},
    )
    await db_session.execute(
        text("DELETE FROM trace.tool_calls WHERE tenant_id = :t"),
        {"t": default_tenant_id},
    )
    await db_session.execute(
        text("DELETE FROM trace.traces WHERE tenant_id = :t"),
        {"t": default_tenant_id},
    )
    await db_session.execute(
        text("DELETE FROM memory.memories WHERE tenant_id = :t"),
        {"t": default_tenant_id},
    )
    await db_session.execute(
        text(
            "DELETE FROM platform.audit_logs WHERE tenant_id = :t"
            " AND resource_type IN ('capabilities', 'skills', 'memory.memories',"
            " 'ratelimit')"
        ),
        {"t": default_tenant_id},
    )
    await db_session.execute(
        text("DELETE FROM ops.tasks WHERE task_type = 'adapter_sync'")
    )
    await db_session.commit()


async def _login(client: httpx.AsyncClient, username: str) -> dict[str, str]:
    resp = await client.post(
        LOGIN, json={"username": username, "password": SEED_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ---- ① 注册中心：Delivery.OrderRisk 注册并可查 ----


async def test_catalog_register_and_query(
    client: httpx.AsyncClient, db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    payload = {
        "name": "Delivery.OrderRisk",
        "domain": "delivery",
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
        "risk_level": "L2",
        "permission": "READ_ONLY",
        "endpoint": "agent-hub://capabilities/delivery-order-risk",
        "owner": "wuyangpeng",
    }
    resp = await client.post(f"{BASE}/capabilities", headers=DEV_HEADERS, json=payload)
    assert resp.status_code == 201, resp.text
    capability_id = resp.json()["capability_id"]

    listed = await client.get(
        f"{BASE}/capabilities", headers=DEV_HEADERS, params={"domain": "delivery"}
    )
    assert listed.status_code == 200, listed.text
    assert [item["capability_id"] for item in listed.json()["items"]] == [capability_id]

    detail = await client.get(f"{BASE}/capabilities/{capability_id}", headers=DEV_HEADERS)
    assert detail.status_code == 200, detail.text
    assert detail.json()["endpoint"] == payload["endpoint"]


# ---- ② Trace：一条 trace + N tool_calls；重发幂等 ----


async def test_trace_write_and_idempotent_replay(
    client: httpx.AsyncClient, default_tenant_id: UUID
) -> None:
    trace_id = str(uuid4())
    payload = {
        "trace_id": trace_id,
        "agent_id": "agent:delivery-order-risk",
        "task_id": "task-w3r-001",
        "started_at": "2026-09-17T08:00:00Z",
        "finished_at": "2026-09-17T08:00:41Z",
        "status": "SUCCEEDED",
        "input_context": {"order_no": "SO-2026-00123"},
        "output_structured": {"risk_level": "P1", "score": 0.86},
        "token_usage": {"prompt": 3120, "completion": 480, "total": 3600},
        "tool_calls": [
            {
                "seq": 1,
                "tool_name": "get_inventory",
                "input": {"material_code": "X-100"},
                "output": {"total_available": 3200},
                "status_code": 200,
                "latency_ms": 85,
            },
            {
                "seq": 2,
                "tool_name": "get_order",
                "input": {"order_no": "SO-2026-00123"},
                "status_code": 200,
                "latency_ms": 42,
            },
        ],
    }
    resp = await client.post(f"{BASE}/traces", headers=DEV_HEADERS, json=payload)
    assert resp.status_code == 201, resp.text

    replay = await client.post(f"{BASE}/traces", headers=DEV_HEADERS, json=payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["trace_id"] == trace_id

    detail = await client.get(f"{BASE}/traces/{trace_id}", headers=DEV_HEADERS)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert [call["seq"] for call in body["tool_calls"]] == [1, 2]
    assert body["token_usage"]["total"] == 3600


# ---- ③ Memory：候选创建 + SERVICE 评审 403 + 审计 ----


async def test_memory_candidate_and_service_review_denied(
    client: httpx.AsyncClient, db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    resp = await client.post(
        f"{BASE}/memories",
        headers=DEV_HEADERS,
        json={
            "source_type": "decision",
            "source_id": str(uuid4()),
            "content": {"lesson": "VIP客户订单优先保交付"},
        },
    )
    assert resp.status_code == 201, resp.text
    memory_id = resp.json()["memory_id"]
    assert resp.json()["status"] == "CANDIDATE"

    denied = await client.patch(
        f"{BASE}/memories/{memory_id}/review",
        headers=DEV_HEADERS,
        json={"status": "APPROVED"},
    )
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "GUARD_POLICY_DENIED"

    audit = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM platform.audit_logs"
                " WHERE tenant_id = :t AND action = 'GUARD_DENIED'"
                " AND resource_type = 'memory.memories'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one()
    assert audit == 1


# ---- ④ 产能：seed → delivery.capacity；mes-demo replay 幂等 ----


async def test_mes_capacity_seed_and_replay(
    client: httpx.AsyncClient,
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await demo_service.seed(app_role_engine, default_tenant_id)

    rows = (
        (
            await db_session.execute(
                text(
                    "SELECT product_line, period, capacity_qty FROM delivery.capacity"
                    " WHERE tenant_id = :t ORDER BY product_line, period"
                ),
                {"t": default_tenant_id},
            )
        )
        .mappings()
        .all()
    )
    assert {(row["product_line"], row["period"]): row["capacity_qty"] for row in rows} == {
        ("L1", "2026-W40"): Decimal("1200"),
        ("L1", "2026-W41"): Decimal("2400"),
        ("L2", "2026-W40"): Decimal("3600"),
    }

    manager = await _login(client, "manager1")
    triggered = await client.post(
        f"{BASE}/admin/adapters/mes-demo/sync",
        headers=manager,
        json={"mode": "replay"},
    )
    assert triggered.status_code == 202, triggered.text
    for _ in range(50):
        status = await client.get(
            f"{BASE}/admin/adapters/mes-demo/status", headers=manager
        )
        last_sync = status.json()["last_sync"]
        if last_sync and last_sync["status"] != "RUNNING":
            break
        await asyncio.sleep(0.1)
    assert last_sync["stats"]["duplicated"] == last_sync["stats"]["fetched"] == 3


# ---- ⑤ 限流 429 + Retry-After + 用量日报可查 ----


async def test_rate_limit_429_and_usage_report(
    client: httpx.AsyncClient, db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    from edp_api.modules.tenantmgmt import ratelimit

    await db_session.execute(
        text(
            "UPDATE platform.tenant_quotas SET api_rate_limit = 2"
            " WHERE tenant_id = :t"
        ),
        {"t": default_tenant_id},
    )
    await db_session.execute(
        text(
            "DELETE FROM platform.tenant_usage_daily WHERE tenant_id = :t"
        ),
        {"t": default_tenant_id},
    )
    await db_session.commit()
    ratelimit.reset_buckets()

    for _ in range(2):
        resp = await client.get(f"{BASE}/events", headers=DEV_HEADERS, params={"limit": 1})
        assert resp.status_code == 200, resp.text

    limited = await client.get(f"{BASE}/events", headers=DEV_HEADERS, params={"limit": 1})
    assert limited.status_code == 429, limited.text
    assert int(limited.headers["Retry-After"]) >= 1

    admin = await _login(client, "admin")
    usage = await client.get(f"{BASE}/tenants/{default_tenant_id}/usage", headers=admin)
    assert usage.status_code == 200, usage.text
    items = usage.json()["items"]
    assert items, usage.text
    assert items[0]["throttled_429"] == 1
    # 精确 2：前 2 次 /events 各 +1；第 3 次在 tenant_scoped 限流分支即 429，
    # 不达 record_api_call（只计 throttled_429）；login 与 usage 端点为平台级
    # 路由不计量（W3R-02/W3R-10 口径——限流后通过的请求才计 api_calls）
    assert items[0]["api_calls"] == 2
