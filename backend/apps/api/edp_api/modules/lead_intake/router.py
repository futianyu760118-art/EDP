"""Internal service-authenticated LeadIntakeV1 handoff from Public BFF."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import ErrorCode, error_responses
from edp_api.core.security.principal import Principal
from edp_api.modules.events.dependencies import require_write
from edp_api.modules.lead_intake import service
from edp_api.modules.lead_intake.schemas import LeadIntakeIn, LeadIntakeResponse
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

router = APIRouter(
    prefix="/api/v1/public",
    tags=["public-lead-intake"],
    dependencies=[Depends(tenant_scoped)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/lead-intake",
    response_model=LeadIntakeResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="接收官网 LeadIntakeV1（仅服务身份）",
    responses=error_responses(
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.TENANT_SUSPENDED,
    ),
)
async def receive_lead(
    payload: LeadIntakeIn,
    principal: Annotated[Principal, Depends(require_write("lead"))],
    sess: DbSession,
) -> LeadIntakeResponse:
    return await service.accept(sess, principal, payload)
