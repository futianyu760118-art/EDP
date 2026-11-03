"""人员状态事件的收件箱、目标状态、重试和结果汇总。"""

import json
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import bind_tenant
from edp_api.core.inbox import build_inbox_key
from edp_api.modules.events import service as events_service
from edp_api.modules.person_lifecycle.models import PersonLifecycleDelivery, PersonLifecycleEvent
from edp_api.modules.person_lifecycle.schemas import (
    PersonLifecycleEventIn,
    PersonLifecycleEventResponse,
    PersonLifecycleRetryResponse,
)
from edp_api.modules.tenantmgmt.models import Tenant


CONSUMER = "EDP_PERSON_LIFECYCLE"
TERMINAL_SUCCESS = {"synced", "skipped"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _targets() -> list[dict]:
    raw = os.getenv("EDP_AEOS_PERSON_LIFECYCLE_TARGETS_JSON") or os.getenv("AEOS_PERSON_LIFECYCLE_TARGETS_JSON") or "[]"
    try:
        values = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(values, list):
        return []
    result: list[dict] = []
    for item in values:
        if not isinstance(item, dict) or not item.get("system_id") or not item.get("url"):
            continue
        if item.get("enabled", True) is False:
            continue
        result.append({
            "system_id": str(item["system_id"]),
            "url": str(item["url"]),
            "key_id": str(item.get("key_id") or "edp-lifecycle"),
            "secret": str(item.get("secret") or ""),
        })
    return result


def target_config(system_id: str) -> dict | None:
    return next((item for item in _targets() if item["system_id"] == system_id), None)


async def resolve_tenant_id(sess: AsyncSession, raw: str) -> UUID:
    try:
        return UUID(str(raw))
    except ValueError:
        tenant = (await sess.execute(select(Tenant).where(Tenant.slug == str(raw)))).scalar_one_or_none()
        if tenant is None:
            raise ValueError("tenant_id must be a UUID or a registered tenant slug")
        return tenant.tenant_id


def aggregate_delivery_status(statuses: list[str]) -> str:
    normalized = {str(value).lower() for value in statuses}
    if not normalized:
        return "pending"
    if "dlq" in normalized:
        return "failed"
    if "failed" in normalized:
        return "partial" if normalized & TERMINAL_SUCCESS else "failed"
    if normalized & {"pending", "scheduled", "retrying"}:
        return "pending"
    if "pending_confirmation" in normalized:
        return "pending_confirmation"
    if normalized <= TERMINAL_SUCCESS:
        return "synced"
    return "pending"


async def ingest_event(
    sess: AsyncSession,
    payload: PersonLifecycleEventIn,
    tenant_id: UUID,
    actor: str,
) -> PersonLifecycleEventResponse:
    """先写 Inbox，再写事件和目标清单；同一 AEOS 幂等键只接受一次。"""

    inbox_key = build_inbox_key(
        tenant_id=tenant_id,
        consumer=CONSUMER,
        source_system=payload.source_system,
        object_type=payload.object_type,
        object_id=payload.object_id,
        revision=payload.revision,
        event_type=payload.event_type,
    )
    inbox, inserted = await events_service.register_inbox(
        sess, inbox_key, payload.model_dump(mode="json"), actor=actor
    )
    existing = (
        await sess.execute(
            select(PersonLifecycleEvent).where(
                PersonLifecycleEvent.tenant_id == tenant_id,
                PersonLifecycleEvent.idempotency_key == payload.idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if not inserted or existing is not None:
        if existing is None:
            existing = (
                await sess.execute(
                    select(PersonLifecycleEvent).where(PersonLifecycleEvent.event_id == payload.event_id)
                )
            ).scalar_one_or_none()
        if existing is None:
            raise ValueError("重复事件已登记，但原事件正在提交")
        deliveries = list(
            (
                await sess.execute(
                    select(PersonLifecycleDelivery)
                    .where(PersonLifecycleDelivery.tenant_id == tenant_id, PersonLifecycleDelivery.event_id == existing.event_id)
                    .order_by(PersonLifecycleDelivery.delivery_id)
                )
            ).scalars()
        )
        response = _response(existing, deliveries)
        response.status = "duplicate"
        response.duplicate = True
        return response

    now = _now()
    scheduled = payload.effective_at > now
    event = PersonLifecycleEvent(
        event_id=payload.event_id,
        tenant_id=tenant_id,
        event_type=payload.event_type,
        event_version=payload.event_version,
        source_system=payload.source_system,
        object_type=payload.object_type,
        object_id=payload.object_id,
        revision=payload.revision,
        occurred_at=payload.occurred_at,
        effective_at=payload.effective_at,
        correlation_id=payload.correlation_id,
        trace_id=payload.trace_id,
        idempotency_key=payload.idempotency_key,
        payload=payload.model_dump(mode="json"),
        status="SCHEDULED" if scheduled else "PENDING",
        created_by=actor,
        updated_by=actor,
    )
    sess.add(event)
    for target in _targets():
        sess.add(PersonLifecycleDelivery(
            tenant_id=tenant_id,
            event_id=payload.event_id,
            target_system=target["system_id"],
            target_url=target["url"],
            status="SCHEDULED" if scheduled else "PENDING",
            next_attempt_at=payload.effective_at if scheduled else now,
            created_by=actor,
            updated_by=actor,
        ))
    await events_service.mark_inbox_processed(sess, inbox.inbox_id, tenant_id, actor=actor)
    await sess.flush()
    deliveries = list(
        (
            await sess.execute(
                select(PersonLifecycleDelivery)
                .where(PersonLifecycleDelivery.tenant_id == tenant_id, PersonLifecycleDelivery.event_id == payload.event_id)
                .order_by(PersonLifecycleDelivery.delivery_id)
            )
        ).scalars()
    )
    return _response(event, deliveries)


def _response(event: PersonLifecycleEvent, deliveries: list[PersonLifecycleDelivery]) -> PersonLifecycleEventResponse:
    return PersonLifecycleEventResponse(
        event_id=event.event_id,
        status=event.status.lower(),
        revision=event.revision,
        event_type=event.event_type,
        object_id=event.object_id,
        effective_at=event.effective_at,
        # 普通查询只返回状态和时间；详细错误只给管理员的 deliveries 查询。
        deliveries=[
            {
                "delivery_id": row.delivery_id,
                "event_id": row.event_id,
                "target_system": row.target_system,
                "status": row.status.lower(),
                "attempt_count": row.attempt_count,
                "last_error": None,
                "delivered_at": row.delivered_at,
                "next_attempt_at": row.next_attempt_at,
            }
            for row in deliveries
        ],
    )


async def get_event(sess: AsyncSession, tenant_id: UUID, event_id: str) -> PersonLifecycleEventResponse | None:
    event = (
        await sess.execute(
            select(PersonLifecycleEvent).where(PersonLifecycleEvent.tenant_id == tenant_id, PersonLifecycleEvent.event_id == event_id)
        )
    ).scalar_one_or_none()
    if event is None:
        return None
    deliveries = list(
        (
            await sess.execute(
                select(PersonLifecycleDelivery)
                .where(PersonLifecycleDelivery.tenant_id == tenant_id, PersonLifecycleDelivery.event_id == event_id)
                .order_by(PersonLifecycleDelivery.delivery_id)
            )
        ).scalars()
    )
    return _response(event, deliveries)


async def list_deliveries(sess: AsyncSession, tenant_id: UUID, event_id: str) -> list[PersonLifecycleDelivery]:
    return list(
        (
            await sess.execute(
                select(PersonLifecycleDelivery)
                .where(PersonLifecycleDelivery.tenant_id == tenant_id, PersonLifecycleDelivery.event_id == event_id)
                .order_by(PersonLifecycleDelivery.delivery_id)
            )
        ).scalars()
    )


async def retry_failed(sess: AsyncSession, tenant_id: UUID, event_id: str, actor: str) -> PersonLifecycleRetryResponse | None:
    event = (
        await sess.execute(
            select(PersonLifecycleEvent).where(PersonLifecycleEvent.tenant_id == tenant_id, PersonLifecycleEvent.event_id == event_id)
        )
    ).scalar_one_or_none()
    if event is None:
        return None
    rows = await list_deliveries(sess, tenant_id, event_id)
    retried: list[str] = []
    for row in rows:
        if row.status in {"FAILED", "DLQ"}:
            row.status = "PENDING"
            row.next_attempt_at = _now()
            row.last_error = None
            row.updated_by = actor
            retried.append(row.target_system)
    if retried:
        event.status = "PENDING"
        event.updated_by = actor
    await sess.flush()
    return PersonLifecycleRetryResponse(event_id=event_id, status=event.status.lower(), retried_targets=retried)


async def claim_pending_deliveries(sess: AsyncSession, tenant_id: UUID, limit: int = 50) -> list[PersonLifecycleDelivery]:
    rows = list(
        (
            await sess.execute(
                select(PersonLifecycleDelivery)
                .where(
                    PersonLifecycleDelivery.tenant_id == tenant_id,
                    PersonLifecycleDelivery.status.in_(["PENDING", "SCHEDULED", "RETRYING"]),
                    PersonLifecycleDelivery.next_attempt_at <= _now(),
                )
                .order_by(PersonLifecycleDelivery.delivery_id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    )
    for row in rows:
        row.status = "RETRYING"
    await sess.flush()
    return rows


async def event_payload(sess: AsyncSession, tenant_id: UUID, event_id: str) -> dict | None:
    event = (
        await sess.execute(
            select(PersonLifecycleEvent).where(PersonLifecycleEvent.tenant_id == tenant_id, PersonLifecycleEvent.event_id == event_id)
        )
    ).scalar_one_or_none()
    return event.payload if event else None


async def mark_delivery_success(sess: AsyncSession, row: PersonLifecycleDelivery, status: str, response: dict | None) -> None:
    row.status = status.upper()
    row.response = response or {}
    row.last_error = None
    row.delivered_at = _now()
    row.updated_at = _now()
    event = (
        await sess.execute(
            select(PersonLifecycleEvent).where(PersonLifecycleEvent.tenant_id == row.tenant_id, PersonLifecycleEvent.event_id == row.event_id)
        )
    ).scalar_one()
    statuses = list(
        (
            await sess.execute(
                select(PersonLifecycleDelivery.status).where(PersonLifecycleDelivery.tenant_id == row.tenant_id, PersonLifecycleDelivery.event_id == row.event_id)
            )
        ).scalars()
    )
    event.status = aggregate_delivery_status(statuses).upper()


async def mark_delivery_failure(sess: AsyncSession, row: PersonLifecycleDelivery, error: str, max_retries: int, backoff_base_seconds: float) -> None:
    row.attempt_count += 1
    row.last_error = error[:1000]
    if row.attempt_count >= max_retries:
        row.status = "DLQ"
    else:
        row.status = "RETRYING"
        row.next_attempt_at = _now() + timedelta(seconds=(2 ** row.attempt_count) * backoff_base_seconds)
    event = (
        await sess.execute(
            select(PersonLifecycleEvent).where(PersonLifecycleEvent.tenant_id == row.tenant_id, PersonLifecycleEvent.event_id == row.event_id)
        )
    ).scalar_one()
    statuses = list(
        (
            await sess.execute(
                select(PersonLifecycleDelivery.status).where(PersonLifecycleDelivery.tenant_id == row.tenant_id, PersonLifecycleDelivery.event_id == row.event_id)
            )
        ).scalars()
    )
    event.status = aggregate_delivery_status(statuses).upper()
