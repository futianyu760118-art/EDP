"""result 路由（V1.2 T17）：经营结果创建/列表/详情/核验。

- POST /results：result:write → 201（evidence_refs 必填非空）；
- GET /results：result:read 游标分页（result_type/status 过滤）；
- GET /results/{id}：详情；跨租户统一 404；
- POST /results/{id}/verify：Human-Only 核验（GUARD_DENIED 审计由 service 落）。
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import EdpError, ErrorCode, error_responses
from edp_api.core.pagination import Page
from edp_api.core.security.principal import Principal
from edp_api.modules.result import service as result_service
from edp_api.modules.result.dependencies import require_result_read, require_result_write
from edp_api.modules.result.schemas import (
    ResultCreatedResponse,
    ResultCreateRequest,
    ResultDetailResponse,
    ResultListItem,
    VerifyResponse,
)
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

router = APIRouter(
    prefix="/api/v1/results",
    tags=["results"],
    dependencies=[Depends(tenant_scoped)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]

_READ_ERRORS = (
    ErrorCode.UNAUTHENTICATED,
    ErrorCode.FORBIDDEN,
    ErrorCode.TENANT_SUSPENDED,
)
_WRITE_ERRORS = (*_READ_ERRORS, ErrorCode.VALIDATION_ERROR)
_VERIFY_ERRORS = (*_WRITE_ERRORS, ErrorCode.NOT_FOUND, ErrorCode.GUARD_POLICY_DENIED)


@router.post(
    "",
    response_model=ResultCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建经营结果（evidence_refs 必填非空）",
    responses=error_responses(*_WRITE_ERRORS),
)
async def create_result(
    payload: ResultCreateRequest,
    principal: Annotated[Principal, Depends(require_result_write())],
    sess: DbSession,
) -> ResultCreatedResponse:
    result = await result_service.create_result(sess, principal, payload)
    return ResultCreatedResponse(
        result_id=result.result_id,
        status=result.status,
        generated_at=result.generated_at,
    )


@router.get(
    "",
    response_model=Page[ResultListItem],
    response_model_exclude_none=True,
    summary="经营结果列表（result_type/status 过滤 + 游标分页）",
    responses=error_responses(*_READ_ERRORS),
)
async def list_results(
    principal: Annotated[Principal, Depends(require_result_read())],
    sess: DbSession,
    result_type: Annotated[str | None, Query(max_length=128)] = None,
    status_filter: Annotated[str | None, Query(alias="status", max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=result_service.MAX_LIMIT)] = (
        result_service.DEFAULT_LIMIT
    ),
    cursor: Annotated[str | None, Query()] = None,
) -> Page[ResultListItem]:
    return await result_service.query_results(
        sess, result_type=result_type, status=status_filter, limit=limit, cursor=cursor
    )


@router.get(
    "/{result_id}",
    response_model=ResultDetailResponse,
    summary="经营结果详情",
    responses=error_responses(*_READ_ERRORS, ErrorCode.NOT_FOUND),
)
async def get_result(
    result_id: UUID,
    principal: Annotated[Principal, Depends(require_result_read())],
    sess: DbSession,
) -> ResultDetailResponse:
    result = await result_service.get_result(sess, result_id)
    if result is None:
        raise EdpError.not_found("经营结果不存在")
    return ResultDetailResponse.model_validate(result)


@router.post(
    "/{result_id}/verify",
    response_model=VerifyResponse,
    summary="核验经营结果（Human-Only；证据链重校验）",
    responses=error_responses(*_VERIFY_ERRORS),
)
async def verify_result(
    result_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(require_result_write())],
    sess: DbSession,
) -> VerifyResponse:
    result = await result_service.verify_result(
        sess, principal, result_id, path=request.url.path
    )
    if result is None:
        raise EdpError.not_found("经营结果不存在")
    return VerifyResponse(
        result_id=result.result_id,
        verified_status=result.verified_status,
        verified_by=result.verified_by,
        verified_at=result.verified_at,
    )
