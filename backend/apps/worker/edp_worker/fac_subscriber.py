"""FAC HTTP subscriber for EDP outbox events.

Only finance-relevant M05/M04 events are forwarded. Any non-success HTTP result
raises so the existing EDP outbox worker performs retry/backoff and eventually
marks the row FAILED.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from edp_api.core.events import OutboxMessage


M05_EVENT_TYPES = {"inquiry.upserted"}
M04_EVENT_TYPES = {
    "BOMReleased",
    "bom.released",
    "ProductConfigurationConfirmed",
    "SpecificationConfirmed",
}


def _post_json(
    url: str,
    body: dict,
    headers: dict[str, str],
    timeout: float,
) -> tuple[int, str]:
    request = Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        return int(exc.code), exc.read().decode("utf-8", errors="replace")
    except URLError as exc:
        raise RuntimeError(f"FAC webhook connection failed url={url}: {exc}") from exc


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

        status, response_text = await asyncio.to_thread(
            _post_json,
            url,
            body,
            headers,
            self.timeout,
        )
        if 200 <= status < 300 or status == 409:
            return
        raise RuntimeError(
            f"FAC webhook failed status={status} url={url} "
            f"body={response_text[:500]}"
        )
