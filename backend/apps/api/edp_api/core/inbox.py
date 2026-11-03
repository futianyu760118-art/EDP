"""Canonical consumer idempotency keys for cross-system event delivery.

The Inbox key is intentionally independent from a producer's event UUID. Two
consumers must be able to process the same event once each, while a replay for
the same consumer, object revision and event type must converge to one row.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID


def _required_text(name: str, value: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} must not be blank")
    return normalized


@dataclass(frozen=True, slots=True)
class InboxKey:
    """Stable, tenant-scoped key for one consumer delivery attempt."""

    tenant_id: UUID
    consumer: str
    source_system: str
    object_type: str
    object_id: str
    revision: int
    event_type: str

    def as_tuple(self) -> tuple[str, str, str, str, str, int, str]:
        return (
            str(self.tenant_id),
            self.consumer,
            self.source_system,
            self.object_type,
            self.object_id,
            self.revision,
            self.event_type,
        )

    def canonical(self) -> str:
        """Return a delimiter-safe representation for logs and APIs."""

        return json.dumps(self.as_tuple(), ensure_ascii=False, separators=(",", ":"))


def build_inbox_key(
    *,
    tenant_id: UUID,
    consumer: str,
    source_system: str,
    object_type: str,
    object_id: str,
    revision: int,
    event_type: str,
) -> InboxKey:
    """Normalize and validate the Phase 1 Inbox idempotency tuple."""

    if not isinstance(tenant_id, UUID):
        raise ValueError("tenant_id must be a UUID")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("revision must be a positive integer")
    return InboxKey(
        tenant_id=tenant_id,
        consumer=_required_text("consumer", consumer),
        source_system=_required_text("source_system", source_system),
        object_type=_required_text("object_type", object_type),
        object_id=_required_text("object_id", object_id),
        revision=revision,
        event_type=_required_text("event_type", event_type),
    )
