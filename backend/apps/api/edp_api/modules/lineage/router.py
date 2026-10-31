"""lineage 路由（V1.2 T20）：血缘只读查询（governance:read 轨道）。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import EdpError, ErrorCode, error_responses
from edp_api.core.security.principal import Principal
from edp_api.modules.governance.dependencies import require_governance_read
from edp_api.modules.lineage import service as lineage_service
from edp_api.modules.lineage.schemas import LineageDetail, LineageItem
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

router = APIRouter(
    prefix="/api/v1/lineage",
    tags=["lineage"],
    dependencies=[Depends(tenant_scoped)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]

_READ_ERRORS = (
    ErrorCode.UNAUTHENTICATED,
    ErrorCode.FORBIDDEN,
    ErrorCode.TENANT_SUSPENDED,
)


@router.get(
    "",
    response_model=list[LineageItem],
    response_model_exclude_none=True,
    summary="按源记录查询血缘链（新→旧）",
    responses=error_responses(*_READ_ERRORS),
)
async def list_lineage(
    principal: Annotated[Principal, Depends(require_governance_read())],
    sess: DbSession,
    source_record_id: Annotated[str, Query(min_length=1, max_length=255)],
) -> list[LineageItem]:
    return [
        LineageItem.model_validate(item)
        for item in await lineage_service.query_by_source_record(
            sess, principal.tenant_id, source_record_id
        )
    ]


@router.get(
    "/{lineage_id}",
    response_model=LineageDetail,
    response_model_exclude_none=True,
    summary="血缘详情（附对象引用）",
    responses=error_responses(*_READ_ERRORS, ErrorCode.NOT_FOUND),
)
async def get_lineage(
    lineage_id: UUID,
    principal: Annotated[Principal, Depends(require_governance_read())],
    sess: DbSession,
) -> LineageDetail:
    lineage = await lineage_service.get_lineage(sess, lineage_id)
    if lineage is None:
        raise EdpError.not_found("血缘记录不存在")
    return LineageDetail(
        **LineageItem.model_validate(lineage).model_dump(),
        object=await lineage_service.object_ref_for(
            sess, principal.tenant_id, lineage_id
        ),
    )
