from uuid import UUID

import pytest
from edp_api.core.events import CRMLeadSubscriber, OutboxMessage

TENANT = UUID("11111111-1111-1111-1111-111111111111")


@pytest.mark.asyncio
async def test_crm_lead_subscriber_only_delivers_lead_events() -> None:
    calls: list[tuple[str, dict[str, str], bytes, float]] = []

    async def sender(url: str, headers: dict[str, str], body: bytes, timeout_s: float) -> None:
        calls.append((url, headers, body, timeout_s))

    subscriber = CRMLeadSubscriber(
        "https://crm.example/api/v1/integrations/aeos/lead-intake",
        "service-token",
        sender=sender,
    )
    await subscriber.on_event(
        OutboxMessage(1, TENANT, "EVENT", UUID(int=1), "other.event", {"id": 1})
    )
    assert calls == []

    await subscriber.on_event(
        OutboxMessage(
            2,
            TENANT,
            "LEAD_INTAKE",
            UUID(int=2),
            "lead.intake.received",
            {"intake_id": "lead_1", "idempotency_key": "web-1"},
        )
    )
    assert len(calls) == 1
    url, headers, body, timeout = calls[0]
    assert url.endswith("/lead-intake")
    assert headers["Authorization"] == "Bearer service-token"
    assert headers["X-Idempotency-Key"] == "web-1"
    assert b"lead_1" in body
    assert timeout == 5.0


def test_crm_lead_subscriber_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDP_CRM_LEAD_TARGET_URL", "https://crm.example/intake")
    monkeypatch.delenv("EDP_CRM_LEAD_TARGET_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="TOKEN"):
        CRMLeadSubscriber.from_env()
