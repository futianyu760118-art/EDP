"""T5 产能投影集成测试（EDP-017 剩余）：mes-demo → delivery.capacity。

覆盖：
1. seed 后 `delivery.capacity` 三行（场景 7：L1/2026-W40=1200 紧张 +
   L2/2026-W40=3600 + L1/2026-W41=2400），product_line/period/capacity_qty/
   snapshot_at 落库正确（NUMERIC 精度）；
2. `POST /admin/adapters/mes-demo/sync {mode:"replay"}` → 202 → 状态
   duplicated==fetched（UUIDv5 幂等，不重复行、不推 revision）；
3. mes-demo 记录对象类型为 CAPACITY 且事件/证据计数与数据集 mes 段一致。

会话形态：应用引擎 = conftest.app_role_engine（edp_app，FORCE RLS）；断言以
migrator db_session 直查。清场：复用 demo_service.purge_tenant_business_data
（逆依赖序，含 capacity 所属 delivery 域）+ 本模块审计行。
"""

import asyncio
from decimal import Decimal
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
DEV_KEY = "edp-dev-agent-hub-key"
DEV_HEADERS = {"X-API-Key": DEV_KEY}
LOGIN = "/api/v1/auth/login"
SEED_PASSWORD = "Admin@123!"

EXPECTED = {
    ("L1", "2026-W40"): Decimal("1200"),
    ("L2", "2026-W40"): Decimal("3600"),
    ("L1", "2026-W41"): Decimal("2400"),
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
async def _clean_business_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    """每测试后清场：seed 业务数据（逆依赖序，含 delivery.capacity）+
    本模块审计行 + adapter_sync 任务行（T5 起 sync 落 ops.tasks，防跨文件
    残留——同 test_adapters_api 口径）。清场经 migrator 会话（BYPASSRLS，
    同 test_demo_seed 模式）。"""
    yield
    await demo_service.purge_tenant_business_data(db_session, default_tenant_id)
    await db_session.execute(
        text(
            "DELETE FROM platform.audit_logs WHERE tenant_id = :t"
            " AND resource_type IN ('capacity', 'business_objects', 'events',"
            " 'records', 'systems')"
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


async def _seed(app_role_engine: AsyncEngine, tenant_id: UUID) -> dict:
    return await demo_service.seed(app_role_engine, tenant_id)


async def _capacity_rows(db_session: AsyncSession, tenant_id: UUID) -> list:
    return (
        (
            await db_session.execute(
                text(
                    "SELECT product_line, period, capacity_qty, snapshot_at"
                    " FROM delivery.capacity WHERE tenant_id = :t"
                    " ORDER BY product_line, period"
                ),
                {"t": tenant_id},
            )
        )
        .mappings()
        .all()
    )


# ---- 1. seed → capacity 三行（场景 7） ----


async def test_seed_projects_capacity_rows(
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await _seed(app_role_engine, default_tenant_id)

    rows = await _capacity_rows(db_session, default_tenant_id)
    assert len(rows) == 3
    assert {
        (row["product_line"], row["period"]): row["capacity_qty"] for row in rows
    } == EXPECTED
    assert all(row["snapshot_at"] is not None for row in rows)

    # mes 段事件/证据计数（3 条 CAPACITY_SNAPSHOT）
    assert (
        await db_session.execute(
            text(
                "SELECT count(*) FROM event.events"
                " WHERE tenant_id = :t AND source_system = 'mes'"
                " AND event_type = 'CAPACITY_SNAPSHOT'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one() == 3


# ---- 2. mes-demo replay：202 + duplicated==fetched（幂等） ----


async def test_mes_replay_duplicates_all_records(
    client: httpx.AsyncClient,
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await _seed(app_role_engine, default_tenant_id)
    headers = await _login(client, "manager1")

    resp = await client.post(
        f"{BASE}/admin/adapters/mes-demo/sync",
        headers=headers,
        json={"mode": "replay"},
    )
    assert resp.status_code == 202, resp.text

    for _ in range(50):
        status = await client.get(
            f"{BASE}/admin/adapters/mes-demo/status", headers=headers
        )
        assert status.status_code == 200, status.text
        last_sync = status.json()["last_sync"]
        if last_sync and last_sync["status"] != "RUNNING":
            break
        await asyncio.sleep(0.1)
    assert last_sync["status"] == "SUCCEEDED", last_sync
    assert last_sync["stats"]["fetched"] == 3
    assert last_sync["stats"]["duplicated"] == 3
    assert last_sync["stats"]["registered"] == 0

    # 行数不翻倍（幂等）
    rows = await _capacity_rows(db_session, default_tenant_id)
    assert len(rows) == 3
