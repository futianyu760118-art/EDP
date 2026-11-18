"""M04/PLM domain-event puller into M02/EDP.

Ordering guarantee:
1. fetch PLM NEW event;
2. bind EDP tenant, resolve/register source object, ingest event, COMMIT;
3. only after EDP commit succeeds, ACK PLM event NEW→PUBLISHED.

If ACK fails, PLM keeps the event NEW. The next pull is safe because EDP event
ingest is idempotent; the retried pull then attempts ACK again.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID

from edp_api.core.config import Settings, get_settings
from edp_api.core.db import bind_tenant
from edp_api.core.security.principal import Principal
from edp_api.modules.events import service as events_service
from edp_api.modules.events.schemas import EventIn
from edp_api.modules.registry import service as registry_service
from edp_api.modules.registry.schemas import ObjectUpsertRequest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

logger = logging.getLogger("edp.worker.plm")

FINANCE_EVENT_TYPES = {
    "BOMReleased",
    "bom.released",
    "ProductConfigurationConfirmed",
    "SpecificationConfirmed",
}


@dataclass(frozen=True, slots=True)
class PlmPendingEvent:
    event_id: str
    event_type: str
    object_type: str
    object_id: str
    occurred_at: datetime
    source_system: str
    correlation_id: str
    version: int
    evidence_refs: list[str]
    payload: dict[str, Any]


def _read_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    text = str(value).strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def _object_type(value: str) -> str:
    value = re.sub(r"(?<!^)(?=[A-Z])", "_", value).upper()
    value = re.sub(r"[^A-Z0-9_]", "_", value)
    return value or "UNKNOWN"


def parse_pending_row(row: dict[str, Any]) -> PlmPendingEvent:
    event_id = str(row.get("event_id") or row.get("eventId") or "").strip()
    event_type = str(row.get("event_type") or row.get("eventType") or "").strip()
    object_type = str(
        row.get("object_type")
        or row.get("objectType")
        or row.get("aggregate_type")
        or "UNKNOWN"
    ).strip()
    object_id = str(
        row.get("object_id")
        or row.get("objectId")
        or row.get("aggregate_id")
        or ""
    ).strip()
    occurred_raw = row.get("occurred_at") or row.get("occurredAt") or row.get("created_at")
    if not event_id or not event_type or not object_id or occurred_raw is None:
        raise ValueError("PLM pending event missing event_id/event_type/object_id/occurred_at")
    occurred_at = (
        occurred_raw
        if isinstance(occurred_raw, datetime)
        else datetime.fromisoformat(str(occurred_raw).replace("Z", "+00:00"))
    )
    evidence = _read_json(row.get("evidence_refs"), [])
    payload = _read_json(row.get("payload_json") or row.get("payload"), {})
    return PlmPendingEvent(
        event_id=event_id,
        event_type=event_type,
        object_type=object_type,
        object_id=object_id,
        occurred_at=occurred_at,
        source_system="M04",
        correlation_id=str(row.get("correlation_id") or row.get("correlationId") or object_id),
        version=max(int(row.get("version") or 1), 1),
        evidence_refs=[str(item) for item in evidence] if isinstance(evidence, list) else [],
        payload=payload if isinstance(payload, dict) else {},
    )


def _http_json(
    method: str,
    url: str,
    *,
    token: str,
    timeout: float,
) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            if not 200 <= int(response.status) < 300:
                raise RuntimeError(f"PLM HTTP {response.status}: {body[:500]}")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"PLM HTTP {exc.code}: {body[:500]}") from exc
    except URLError as exc:
        raise RuntimeError(f"PLM connection failed: {exc}") from exc
    data = json.loads(body)
    if not isinstance(data, dict) or int(data.get("code", 500)) != 200:
        raise RuntimeError(f"PLM business response failed: {data}")
    return data


async def fetch_pending(settings: Settings) -> list[PlmPendingEvent]:
    query = urlencode({"limit": max(1, min(settings.plm_batch_size, 200))})
    url = f"{settings.plm_base_url.rstrip('/')}/v1/integration/events/pending?{query}"
    body = await asyncio.to_thread(
        _http_json,
        "GET",
        url,
        token=settings.plm_bearer_token,
        timeout=settings.plm_timeout_seconds,
    )
    rows = body.get("data") or []
    if not isinstance(rows, list):
        raise RuntimeError("PLM pending response data must be a list")
    return [parse_pending_row(row) for row in rows if isinstance(row, dict)]


async def ack_event(settings: Settings, event_id: str) -> None:
    url = (
        f"{settings.plm_base_url.rstrip('/')}/v1/integration/events/"
        f"{event_id}/ack"
    )
    await asyncio.to_thread(
        _http_json,
        "POST",
        url,
        token=settings.plm_bearer_token,
        timeout=settings.plm_timeout_seconds,
    )


async def _resolve_object(
    sess,
    principal: Principal,
    event: PlmPendingEvent,
):
    object_type = _object_type(event.object_type)
    page = await registry_service.query_objects(
        sess,
        object_type=object_type,
        source_system="M04",
        source_id=event.object_id,
        limit=1,
    )
    if page.items:
        return page.items[0].object_id

    obj, _ = await registry_service.upsert_object(
        sess,
        principal,
        ObjectUpsertRequest(
            object_type=object_type,
            owner_domain="rd",
            source_system="M04",
            source_id=event.object_id,
            attributes={
                "correlation_id": event.correlation_id,
                "plm_version": event.version,
            },
        ),
    )
    return obj.object_id


async def ingest_one(
    engine: AsyncEngine,
    tenant_id: UUID,
    event: PlmPendingEvent,
) -> None:
    principal = Principal(
        id="m02-plm-puller",
        kind="SERVICE",
        tenant_id=tenant_id,
        scopes=["write:registry", "write:event"],
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as sess:
        await bind_tenant(sess, tenant_id)
        object_id = await _resolve_object(sess, principal, event)
        plm_event = {
            "eventType": event.event_type,
            "objectType": event.object_type,
            "objectId": event.object_id,
            "occurredAt": event.occurred_at.isoformat(),
            "sourceSystem": "M04",
            "correlationId": event.correlation_id,
            "version": event.version,
            "evidenceRefs": event.evidence_refs,
            "payload": event.payload,
        }
        response = await events_service.ingest_batch(
            sess,
            principal,
            f"M04:{event.event_id}",
            [
                EventIn(
                    event_type=event.event_type,
                    object_id=object_id,
                    source_system="M04",
                    occurred_at=event.occurred_at,
                    actor_type="SERVICE",
                    actor_id="M04",
                    data={
                        "source_event_id": event.event_id,
                        "plm_event": plm_event,
                    },
                )
            ],
        )
        if response.rejected:
            await sess.rollback()
            raise RuntimeError(
                f"EDP rejected PLM event {event.event_id}: {response.errors}"
            )
        await sess.commit()


async def pull_once(
    engine: AsyncEngine,
    *,
    settings: Settings | None = None,
) -> dict[str, int]:
    settings = settings or get_settings()
    if not settings.plm_base_url.strip() or not settings.plm_tenant_id.strip():
        return {"fetched": 0, "ingested": 0, "acked": 0, "failed": 0}

    tenant_id = UUID(settings.plm_tenant_id)
    events = await fetch_pending(settings)
    stats = {"fetched": len(events), "ingested": 0, "acked": 0, "failed": 0}

    for event in events:
        if event.event_type not in FINANCE_EVENT_TYPES:
            continue
        try:
            await ingest_one(engine, tenant_id, event)
            stats["ingested"] += 1
            await ack_event(settings, event.event_id)
            stats["acked"] += 1
        except Exception:  # noqa: BLE001 — 单事件失败保留 NEW，下一轮重试
            stats["failed"] += 1
            logger.exception("PLM event pull failed event_id=%s", event.event_id)
    return stats


async def run_forever(
    engine: AsyncEngine,
    *,
    settings: Settings | None = None,
) -> None:
    settings = settings or get_settings()
    while True:
        try:
            stats = await pull_once(engine, settings=settings)
            if stats["fetched"] or stats["failed"]:
                logger.info(
                    "PLM pull stats fetched=%d ingested=%d acked=%d failed=%d",
                    stats["fetched"],
                    stats["ingested"],
                    stats["acked"],
                    stats["failed"],
                )
        except Exception:  # noqa: BLE001 — 拉取循环不得因单次故障退出
            logger.exception("PLM pull cycle failed")
        await asyncio.sleep(settings.plm_poll_interval_seconds)
