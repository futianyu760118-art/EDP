"""T6 限流配额集成测试（EDP-025）：429 + Retry-After + 审计/计数、
statement_timeout、api_calls 计量、批量限额。

应用引擎 = conftest.app_role_engine（edp_app，FORCE RLS）；conftest 的
autouse ``_relax_rate_limit`` 每用例前清空令牌桶并把默认租户配额提到高位，
本模块用例自行改低配额（用例结束无需恢复——下一用例的基座会重置）。
探针路由（仅测试装配）：tenant_scoped + 读 current_setting('statement_timeout')。
"""

from typing import Annotated
from uuid import UUID

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.core.db import get_db
from edp_api.core.security.principal import Principal
from edp_api.main import create_app
from edp_api.modules.tenantmgmt import ratelimit
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

BASE = "/api/v1"
DEV_KEY = "edp-dev-agent-hub-key"
DEV_HEADERS = {"X-API-Key": DEV_KEY}
PROBE = "/api/v1/_probe/timeout"

probe_router = APIRouter(prefix="/api/v1/_probe", tags=["probe"])


@probe_router.get("/timeout")
async def probe_timeout(
    principal: Annotated[Principal, Depends(tenant_scoped)],
    sess: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """tenant_scoped 后读会话级 statement_timeout（EDP-025 生效直证）。"""
    value: str = (
        await sess.execute(text("SELECT current_setting('statement_timeout')"))
    ).scalar_one()
    return {"statement_timeout": value, "tenant_id": str(principal.tenant_id)}


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    await core_db.dispose_engine()
    monkeypatch.setattr(core_db, "get_engine", lambda: app_role_engine)
    transport = httpx.ASGITransport(app=create_app(extra_routers=[probe_router]))
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


async def _set_quota(db_session: AsyncSession, tenant_id: UUID, **fields) -> None:
    sets = ", ".join(f"{key} = :{key}" for key in fields)
    await db_session.execute(
        text(f"UPDATE platform.tenant_quotas SET {sets} WHERE tenant_id = :t"),
        {**fields, "t": tenant_id},
    )
    await db_session.commit()


async def _usage_row(db_session: AsyncSession, tenant_id: UUID) -> dict:
    row = (
        (
            await db_session.execute(
                text(
                    "SELECT api_calls, throttled_429 FROM platform.tenant_usage_daily"
                    " WHERE tenant_id = :t AND usage_date = CURRENT_DATE"
                ),
                {"t": tenant_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else {"api_calls": 0, "throttled_429": 0}


# ---- 1. 429 + Retry-After + 审计 + throttled_429 ----


async def test_rate_limited_429_retry_after_audit_and_usage(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await _set_quota(db_session, default_tenant_id, api_rate_limit=3)
    ratelimit.reset_buckets()

    for _ in range(3):
        resp = await client.get(PROBE, headers=DEV_HEADERS)
        assert resp.status_code == 200, resp.text

    resp = await client.get(PROBE, headers=DEV_HEADERS)
    assert resp.status_code == 429, resp.text
    assert resp.json()["error"]["code"] == "RATE_LIMITED"
    retry_after = int(resp.headers["Retry-After"])
    assert retry_after >= 1

    # 审计（独立会话提交）+ 用量计数
    audit = (
        await db_session.execute(
            text(
                "SELECT actor_id, detail FROM platform.audit_logs"
                " WHERE tenant_id = :t AND action = 'RATE_LIMITED'"
                " ORDER BY audit_id DESC LIMIT 1"
            ),
            {"t": default_tenant_id},
        )
    ).one()
    assert audit.actor_id == "agent-hub"
    assert audit.detail["path"] == PROBE
    assert audit.detail["limit_per_min"] == 3

    usage = await _usage_row(db_session, default_tenant_id)
    assert usage["throttled_429"] == 1


# ---- 2. 80% 水位告警审计（每窗口一次） ----


async def test_near_limit_warning_audited_once(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await _set_quota(db_session, default_tenant_id, api_rate_limit=5)
    ratelimit.reset_buckets()

    for _ in range(4):  # 第 4 次后 tokens=1/5=20% → 告警
        resp = await client.get(PROBE, headers=DEV_HEADERS)
        assert resp.status_code == 200, resp.text

    count = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM platform.audit_logs"
                " WHERE tenant_id = :t AND action = 'RATE_LIMIT_WARNING'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one()
    assert count == 1


# ---- 3. statement_timeout 按配额生效 ----


async def test_statement_timeout_applied_from_quota(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await _set_quota(db_session, default_tenant_id, query_timeout_ms=1234)

    resp = await client.get(PROBE, headers=DEV_HEADERS)
    assert resp.status_code == 200, resp.text
    assert resp.json()["statement_timeout"].startswith("1234")


# ---- 4. api_calls 每请求 +1 ----


async def test_api_calls_incremented_per_request(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    before = await _usage_row(db_session, default_tenant_id)

    for _ in range(2):
        resp = await client.get(PROBE, headers=DEV_HEADERS)
        assert resp.status_code == 200, resp.text

    after = await _usage_row(db_session, default_tenant_id)
    assert after["api_calls"] == before["api_calls"] + 2


# ---- 5. 批量限额（batch_max_events） ----


async def test_batch_over_batch_max_events_400(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await _set_quota(db_session, default_tenant_id, batch_max_events=2)

    events = [
        {
            "event_type": "order.created",
            "object_id": "00000000-0000-4000-8000-000000000001",
            "source_system": "erp",
            "occurred_at": "2026-09-28T08:00:00Z",
        }
        for _ in range(3)
    ]
    resp = await client.post(
        f"{BASE}/events/batch",
        headers={**DEV_HEADERS, "Idempotency-Key": "t6-batch-limit"},
        json={"events": events},
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()["error"]
    assert body["code"] == "VALIDATION_ERROR"
    assert "上限" in body["message"]
