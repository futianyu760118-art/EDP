"""LeadIntakeV1 persistence and transactional Outbox handoff."""

from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.errors import EdpError
from edp_api.core.security.principal import Principal
from edp_api.modules.events import service as events_service
from edp_api.modules.lead_intake.models import LeadIntake
from edp_api.modules.lead_intake.schemas import LeadIntakeIn, LeadIntakeResponse

AGGREGATE_TYPE = "LEAD_INTAKE"
EVENT_TYPE = "lead.intake.received"


def aggregate_id_for(tenant_id: UUID, idempotency_key: str) -> UUID:
    return uuid5(tenant_id, f"{AGGREGATE_TYPE}:{idempotency_key}")


async def accept(
    sess: AsyncSession, principal: Principal, payload: LeadIntakeIn
) -> LeadIntakeResponse:
    tenant_id = principal.effective_tenant_id
    if payload.tenant_id is not None and payload.tenant_id != str(tenant_id):
        raise EdpError.forbidden("LeadIntake tenant_id 与认证租户不一致")

    event_payload = payload.model_dump(mode="json")
    event_payload["tenant_id"] = str(tenant_id)
    stmt = (
        pg_insert(LeadIntake)
        .values(
            tenant_id=tenant_id,
            intake_id=payload.intake_id,
            idempotency_key=payload.idempotency_key,
            payload=event_payload,
            status="PENDING",
            created_by=principal.id,
            updated_by=principal.id,
        )
        .on_conflict_do_nothing(
            index_elements=[LeadIntake.tenant_id, LeadIntake.idempotency_key]
        )
        .returning(LeadIntake.lead_intake_id)
    )
    inserted_id = (await sess.execute(stmt)).scalar_one_or_none()
    if inserted_id is None:
        existing = (
            await sess.execute(
                select(LeadIntake).where(
                    LeadIntake.tenant_id == tenant_id,
                    LeadIntake.idempotency_key == payload.idempotency_key,
                )
            )
        ).scalar_one()
        return LeadIntakeResponse(
            lead_reference=existing.intake_id, deduplicated=True
        )

    await events_service.append_outbox(
        sess,
        tenant_id=tenant_id,
        aggregate_type=AGGREGATE_TYPE,
        aggregate_id=aggregate_id_for(tenant_id, payload.idempotency_key),
        event_type=EVENT_TYPE,
        payload=event_payload,
        actor=principal.id,
    )
    return LeadIntakeResponse(
        lead_reference=payload.intake_id, deduplicated=False
    )
