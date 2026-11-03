"""M02/EDP 人员状态同步：签名、Inbox 幂等、租户隔离和目标重试。"""

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.main import create_app
from edp_api.modules.person_lifecycle.service import aggregate_delivery_status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.integration

KEY_ID = "m01-test"
SECRET = "person-lifecycle-test-secret"
PATH = "/api/v1/person-lifecycle/events"


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    await core_db.dispose_engine()
    monkeypatch.setenv("EDP_AEOS_PERSON_LIFECYCLE_KEY_ID", KEY_ID)
    monkeypatch.setenv("EDP_AEOS_PERSON_LIFECYCLE_SECRET", SECRET)
    monkeypatch.setattr(core_db, "get_engine", lambda: app_role_engine)
    transport = httpx.ASGITransport(app=create_app())
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        await core_db.dispose_engine()


@pytest.fixture
async def tenant_id(db_session: AsyncSession) -> UUID:
    return (
        await db_session.execute(
            text("SELECT tenant_id FROM platform.tenants WHERE slug = 'default'")
        )
    ).scalar_one()


def event_body(tenant_id: UUID, *, event_id: str = "EVT-PLC-1", effective_at: str | None = None) -> dict:
    return {
        "event_id": event_id,
        "event_type": "person.offboarded",
        "event_version": 1,
        "tenant_id": str(tenant_id),
        "source_system": "M01_KERNEL",
        "object_type": "Person",
        "object_id": "P_PERSON_1",
        "revision": 2,
        "occurred_at": "2026-11-03T00:00:00Z",
        "effective_at": effective_at or "2026-11-03T00:00:00Z",
        "correlation_id": "CASE-PLC-1",
        "trace_id": "TRACE-PLC-1",
        "idempotency_key": f"{tenant_id}:M01_KERNEL:Person:P_PERSON_1:2:person.offboarded",
        "person": {"person_id": "P_PERSON_1", "emp_code": "19"},
        "status": "inactive",
        "employment_action": "offboard",
        "occurred_by": "P_OWNER",
    }


def signed_headers(body: dict) -> dict[str, str]:
    raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
    timestamp = str(int(datetime.now(tz=timezone.utc).timestamp() * 1000))
    signature = hmac.new(SECRET.encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-AEOS-Key-Id": KEY_ID,
        "X-AEOS-Timestamp": timestamp,
        "X-AEOS-Signature": f"sha256={signature}",
    }


@pytest.mark.asyncio
async def test_signed_intake_is_idempotent_and_future_event_is_scheduled(
    client: httpx.AsyncClient, tenant_id: UUID
) -> None:
    body = event_body(
        tenant_id,
        effective_at=(datetime.now(tz=timezone.utc) + timedelta(minutes=10)).isoformat(),
    )
    first = await client.post(PATH, json=body, headers=signed_headers(body))
    assert first.status_code == 202, first.text
    assert first.json()["status"] == "scheduled"

    duplicate = await client.post(PATH, json=body, headers=signed_headers(body))
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["status"] == "duplicate"


@pytest.mark.asyncio
async def test_invalid_signature_is_rejected_without_writing(
    client: httpx.AsyncClient, tenant_id: UUID, db_session: AsyncSession
) -> None:
    body = event_body(tenant_id, event_id="EVT-PLC-BAD")
    headers = signed_headers(body)
    headers["X-AEOS-Signature"] = "sha256=" + ("0" * 64)
    response = await client.post(PATH, json=body, headers=headers)
    assert response.status_code == 401
    count = (
        await db_session.execute(
            text("SELECT count(*) FROM event.person_lifecycle_events WHERE event_id = 'EVT-PLC-BAD'")
        )
    ).scalar_one()
    assert count == 0


def test_partial_result_and_retry_only_failed_targets() -> None:
    assert aggregate_delivery_status([]) == "pending"
    assert aggregate_delivery_status(["synced", "failed"]) == "partial"
    assert aggregate_delivery_status(["synced", "pending_confirmation"]) == "pending_confirmation"
    assert aggregate_delivery_status(["synced", "skipped"]) == "synced"
    assert aggregate_delivery_status(["dlq", "synced"]) == "failed"
