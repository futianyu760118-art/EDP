from __future__ import annotations

from uuid import uuid4

import pytest
from edp_api.core.events import OutboxMessage
from edp_worker import fac_subscriber
from edp_worker.fac_subscriber import FACWebhookSubscriber

CALLS: list[dict] = []
RESPONSE = (200, "")


def _fake_post_json(
    url: str,
    body: dict,
    headers: dict[str, str],
    timeout: float,
) -> tuple[int, str]:
    CALLS.append(
        {
            "url": url,
            "body": body,
            "headers": headers,
            "timeout": timeout,
        }
    )
    return RESPONSE


@pytest.fixture(autouse=True)
def _patch_http(monkeypatch: pytest.MonkeyPatch):
    global RESPONSE
    CALLS.clear()
    RESPONSE = (200, "")
    monkeypatch.setattr(fac_subscriber, "_post_json", _fake_post_json)


def _message(*, source_system: str, event_type: str, data: dict) -> OutboxMessage:
    return OutboxMessage(
        outbox_id=1,
        tenant_id=uuid4(),
        aggregate_type="EVENT",
        aggregate_id=uuid4(),
        event_type=event_type,
        payload={
            "event_type": event_type,
            "source_system": source_system,
            "data": data,
        },
    )


async def test_m05_inquiry_event_is_forwarded_to_fac() -> None:
    aeos_event = {
        "contract_version": "AEOS.Event.V1",
        "event_id": "CRM-EVT-1",
        "event_type": "inquiry.upserted",
        "source_system": "M05",
        "object_type": "Inquiry",
        "object_id": "inquiry-1",
        "operation": "UPSERT",
        "occurred_at": "2026-11-18T08:00:00Z",
        "trace_id": "trace-1",
        "payload": {"serial_number": "INQ-2026-0088", "status": "SUBMITTED"},
    }
    msg = _message(
        source_system="M05",
        event_type="inquiry.upserted",
        data={"aeos_event": aeos_event},
    )
    await FACWebhookSubscriber(
        base_url="http://fac.local", token="tok"
    ).on_event(msg)

    sent = CALLS[-1]
    assert sent["url"] == (
        "http://fac.local/api/v1/fac/integration/m02/crm-aeos-event"
    )
    assert sent["body"]["ingress_system"] == "M02"
    assert sent["body"]["event"] == aeos_event
    assert sent["headers"]["Authorization"] == "Bearer tok"


async def test_m04_bom_event_is_forwarded_to_fac() -> None:
    plm_event = {
        "eventType": "BOMReleased",
        "objectType": "BOM",
        "objectId": "BOM-WL6000-R13",
        "occurredAt": "2026-11-18T08:00:00Z",
        "sourceSystem": "M04",
        "correlationId": "BOM:WL6000",
        "version": 13,
        "payload": {"rootPartNo": "WL6000"},
    }
    msg = _message(
        source_system="M04",
        event_type="BOMReleased",
        data={"source_event_id": "PLM-EVT-13", "plm_event": plm_event},
    )
    await FACWebhookSubscriber(base_url="http://fac.local").on_event(msg)

    sent = CALLS[-1]
    assert sent["url"].endswith("/api/v1/fac/integration/m02/plm-event")
    assert sent["body"]["event_id"] == "PLM-EVT-13"
    assert sent["body"]["event"] == plm_event


async def test_unrelated_event_is_ignored() -> None:
    msg = _message(
        source_system="M05",
        event_type="customer.upserted",
        data={"aeos_event": {}},
    )
    await FACWebhookSubscriber(base_url="http://fac.local").on_event(msg)
    assert CALLS == []


async def test_fac_http_failure_nacks_for_outbox_retry() -> None:
    global RESPONSE
    RESPONSE = (500, "boom")
    msg = _message(
        source_system="M05",
        event_type="inquiry.upserted",
        data={"aeos_event": {"event_id": "x"}},
    )
    with pytest.raises(RuntimeError, match="FAC webhook failed"):
        await FACWebhookSubscriber(base_url="http://fac.local").on_event(msg)
