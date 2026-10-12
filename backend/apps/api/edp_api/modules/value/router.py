"""value 路由（V1.2 T25）：价值账本基础版（复用 metric 权限轨道）。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import EdpError, ErrorCode, error_responses
from edp_api.core.pagination import Page
from edp_api.core.security.principal import Principal
from edp_api.modules.metric.dependencies import require_metric_manage, require_metric_read
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped
from edp_api.modules.value import service as value_service
from edp_api.modules.value.schemas import (
    ValueLedgerCreate,
    ValueLedgerItem,
    ValueLedgerVerifyResponse,
)

router = APIRouter(
    prefix="/api/v1/value-ledger",
    tags=["value-ledger"],
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
    response_model=ValueLedgerItem,
    status_code=status.HTTP_201_CREATED,
    summary="登记价值事实（改善前后 + 证据引用）",
    responses=error_responses(*_WRITE_ERRORS),
)
async def create_entry(
    payload: ValueLedgerCreate,
    principal: Annotated[Principal, Depends(require_metric_manage())],
    sess: DbSession,
) -> ValueLedgerItem:
    return ValueLedgerItem.model_validate(
        await value_service.create_entry(sess, principal, payload)
    )


@router.get(
    "",
    response_model=Page[ValueLedgerItem],
    response_model_exclude_none=True,
    summary="价值账本列表（metric_ref 过滤 + 游标分页）",
    responses=error_responses(*_READ_ERRORS),
)
async def list_entries(
    principal: Annotated[Principal, Depends(require_metric_read())],
    sess: DbSession,
    metric_ref: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=value_service.MAX_LIMIT)] = (
        value_service.DEFAULT_LIMIT
    ),
    cursor: Annotated[str | None, Query()] = None,
) -> Page[ValueLedgerItem]:
    return await value_service.query_entries(
        sess, metric_ref=metric_ref, limit=limit, cursor=cursor
    )


@router.get(
    "/{value_id}",
    response_model=ValueLedgerItem,
    summary="价值账本详情",
    responses=error_responses(*_READ_ERRORS, ErrorCode.NOT_FOUND),
)
async def get_entry(
    value_id: UUID,
    principal: Annotated[Principal, Depends(require_metric_read())],
    sess: DbSession,
) -> ValueLedgerItem:
    entry = await value_service.get_entry(sess, value_id)
    if entry is None:
        raise EdpError.not_found("价值记录不存在")
    return ValueLedgerItem.model_validate(entry)


@router.post(
    "/{value_id}/verify",
    response_model=ValueLedgerVerifyResponse,
    summary="人工核验价值事实（Human-Only）",
    responses=error_responses(*_VERIFY_ERRORS),
)
async def verify_entry(
    value_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(require_metric_manage())],
    sess: DbSession,
) -> ValueLedgerVerifyResponse:
    entry = await value_service.verify_entry(
        sess, principal, value_id, path=request.url.path
    )
    if entry is None:
        raise EdpError.not_found("价值记录不存在")
    return ValueLedgerVerifyResponse(
        value_id=entry.value_id,
        verified_by=entry.verified_by,
        verified_at=entry.verified_at,
    )
