"""FAC HTTP subscriber for EDP outbox events.

Only finance-relevant M05/M04 events are forwarded. Any non-success HTTP result
raises so the existing EDP outbox worker performs retry/backoff and eventually
marks the row FAILED.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from edp_api.core.events import OutboxMessage


M05_EVENT_TYPES = {"inquiry.upserted"}
M04_EVENT_TYPES = {
    "BOMReleased",
    "bom.released",
    "ProductConfigurationConfirmed",
    "SpecificationConfirmed",
}


@dataclass(slots=True)
class FACWebhookSubscriber:
    base_url: str
    token: str = ""
    timeout: float = 10.0

    async def on_event(self, msg: OutboxMessage) -> None:
        if msg.aggregate_type != "EVENT":
            return

        source_system = str(msg.payload.get("source_system") or "")
        event_type = str(msg.payload.get("event_type") or msg.event_type)
        data = msg.payload.get("data")
        if not isinstance(data, dict):
            data = {}

        endpoint: str | None = None
        body: dict | None = None

        if source_system == "M05" and event_type in M05_EVENT_TYPES:
            aeos_event = data.get("aeos_event")
            if not isinstance(aeos_event, dict):
                raise ValueError("M05 finance-relevant event missing data.aeos_event")
            endpoint = "/api/v1/fac/integration/m02/crm-aeos-event"
            body = {
                "tenant_id": str(msg.tenant_id),
                "ingress_system": "M02",
                "event": aeos_event,
            }
        elif source_system == "M04" and event_type in M04_EVENT_TYPES:
            plm_event = data.get("plm_event")
            source_event_id = data.get("source_event_id")
            if not isinstance(plm_event, dict) or not source_event_id:
                raise ValueError(
                    "M04 finance-relevant event missing data.plm_event/source_event_id"
                )
            endpoint = "/api/v1/fac/integration/m02/plm-event"
            body = {
                "tenant_id": str(msg.tenant_id),
                "ingress_system": "M02",
                "event_id": str(source_event_id),
                "event": plm_event,
            }
        else:
            return

        url = f"{self.base_url.rstrip('/')}{endpoint}"
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=body, headers=headers)

        if 200 <= response.status_code < 300 or response.status_code == 409:
            return
        raise RuntimeError(
            f"FAC webhook failed status={response.status_code} url={url} "
            f"body={response.text[:500]}"
        )
