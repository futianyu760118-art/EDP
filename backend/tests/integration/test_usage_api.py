"""T7 使用量日报 API 集成测试（B.14 最小版，EDP-025）：过滤/排序/游标、
权限、404、与真实请求计量联动。

应用引擎 = conftest.app_role_engine；usage 行造数以 migrator db_session 直插
（控制面表无 RLS）。清场：本模块造的行 + 审计行。
"""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.main import create_app
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

BASE = "/api/v1"
LOGIN = "/api/v1/auth/login"
SEED_PASSWORD = "Admin@123!"
TODAY = datetime.now(UTC).date()


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
async def _clean_usage_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    """用例前后清空默认租户的 usage 行与限流审计行——本模块断言精确计数，
    需隔离其他用例写入的今日行（全量运行时同库共享）。"""

    async def _purge() -> None:
        await db_session.execute(
            text(
                "DELETE FROM platform.tenant_usage_daily WHERE tenant_id = :t"
            ),
            {"t": default_tenant_id},
        )
        await db_session.execute(
            text(
                "DELETE FROM platform.audit_logs WHERE tenant_id = :t"
                " AND resource_type = 'ratelimit'"
            ),
            {"t": default_tenant_id},
        )
        await db_session.commit()

    await _purge()
    yield
    await _purge()


async def _login(client: httpx.AsyncClient, username: str) -> dict[str, str]:
    resp = await client.post(
        LOGIN, json={"username": username, "password": SEED_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _insert_usage(
    db_session: AsyncSession,
    tenant_id: UUID,
    usage_date: date,
    *,
    api_calls: int = 0,
    events_in: int = 0,
    events_duplicated: int = 0,
    throttled_429: int = 0,
) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO platform.tenant_usage_daily
                (id, tenant_id, usage_date, api_calls, events_in,
                 events_duplicated, storage_gb, throttled_429)
            VALUES (:id, :t, :d, :api, :ev, :dup, 0, :thr)
            ON CONFLICT (tenant_id, usage_date) DO UPDATE
            SET api_calls = EXCLUDED.api_calls,
                events_in = EXCLUDED.events_in,
                events_duplicated = EXCLUDED.events_duplicated,
                throttled_429 = EXCLUDED.throttled_429
            """
        ),
        {
            "id": uuid4(),
            "t": tenant_id,
            "d": usage_date,
            "api": api_calls,
            "ev": events_in,
            "dup": events_duplicated,
            "thr": throttled_429,
        },
    )
    await db_session.commit()


# ---- 1. 过滤/排序/字段 ----


async def test_usage_query_filters_and_shape(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    for offset, calls in ((3, 10), (1, 30), (2, 20)):
        await _insert_usage(
            db_session,
            default_tenant_id,
            TODAY - timedelta(days=offset),
            api_calls=calls,
            events_in=calls * 2,
            events_duplicated=1,
            throttled_429=offset,
        )

    admin = await _login(client, "admin")
    resp = await client.get(
        f"{BASE}/tenants/{default_tenant_id}/usage", headers=admin
    )
    assert resp.status_code == 200, resp.text
    page = resp.json()
    assert page.get("next_cursor") is None
    assert [item["usage_date"] for item in page["items"]] == [
        (TODAY - timedelta(days=1)).isoformat(),
        (TODAY - timedelta(days=2)).isoformat(),
        (TODAY - timedelta(days=3)).isoformat(),
    ]
    first = page["items"][0]
    assert set(first) == {
        "usage_date",
        "api_calls",
        "events_in",
        "events_duplicated",
        "storage_gb",
        "throttled_429",
    }
    assert first["api_calls"] == 30
    assert first["events_in"] == 60
    assert first["throttled_429"] == 1

    # since/until 闭区间
    resp = await client.get(
        f"{BASE}/tenants/{default_tenant_id}/usage",
        headers=admin,
        params={
            "since": (TODAY - timedelta(days=2)).isoformat(),
            "until": (TODAY - timedelta(days=1)).isoformat(),
        },
    )
    assert resp.status_code == 200, resp.text
    assert [item["usage_date"] for item in resp.json()["items"]] == [
        (TODAY - timedelta(days=1)).isoformat(),
        (TODAY - timedelta(days=2)).isoformat(),
    ]


# ---- 2. 游标分页 ----


async def test_usage_cursor_pagination(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    for offset in range(1, 4):
        await _insert_usage(
            db_session, default_tenant_id, TODAY - timedelta(days=offset)
        )

    admin = await _login(client, "admin")
    first = await client.get(
        f"{BASE}/tenants/{default_tenant_id}/usage",
        headers=admin,
        params={"limit": 2},
    )
    assert first.status_code == 200, first.text
    page = first.json()
    assert len(page["items"]) == 2
    assert page["next_cursor"]

    second = await client.get(
        f"{BASE}/tenants/{default_tenant_id}/usage",
        headers=admin,
        params={"limit": 2, "cursor": page["next_cursor"]},
    )
    assert second.status_code == 200, second.text
    assert len(second.json()["items"]) == 1
    assert second.json().get("next_cursor") is None


# ---- 3. 权限与 404 ----


async def test_usage_permissions_and_not_found(
    client: httpx.AsyncClient, default_tenant_id: UUID
) -> None:
    manager = await _login(client, "manager1")
    resp = await client.get(
        f"{BASE}/tenants/{default_tenant_id}/usage", headers=manager
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    admin = await _login(client, "admin")
    resp = await client.get(f"{BASE}/tenants/{uuid4()}/usage", headers=admin)
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "NOT_FOUND"


# ---- 4. 真实请求计量联动（api_calls 由 tenant_scoped 写入） ----


async def test_usage_reflects_live_api_calls(
    client: httpx.AsyncClient, default_tenant_id: UUID
) -> None:
    admin = await _login(client, "admin")
    resp = await client.get(f"{BASE}/tenants/{default_tenant_id}/usage", headers=admin)
    assert resp.status_code == 200, resp.text
    today_rows = [
        item
        for item in resp.json()["items"]
        if item["usage_date"] == TODAY.isoformat()
    ]
    before = today_rows[0]["api_calls"] if today_rows else 0

    # 两个租户域请求（GET /events 走 tenant_scoped → 计量）
    for _ in range(2):
        resp = await client.get(
            f"{BASE}/events",
            headers={"X-API-Key": "edp-dev-agent-hub-key"},
            params={"limit": 1},
        )
        assert resp.status_code == 200, resp.text

    resp = await client.get(f"{BASE}/tenants/{default_tenant_id}/usage", headers=admin)
    assert resp.status_code == 200, resp.text
    today_rows = [
        item
        for item in resp.json()["items"]
        if item["usage_date"] == TODAY.isoformat()
    ]
    assert today_rows
    # usage 查询本身是平台路由（不挂 tenant_scoped）→ 不计入；断言 >= before + 2
    assert today_rows[0]["api_calls"] >= before + 2
