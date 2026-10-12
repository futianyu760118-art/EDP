"""metric 路由（V1.2 T23）：指标口径注册 / 列表 / 计量值。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import EdpError, ErrorCode, error_responses
from edp_api.core.pagination import Page
from edp_api.core.security.principal import Principal
from edp_api.modules.metric import service as metric_service
from edp_api.modules.metric.dependencies import require_metric_manage, require_metric_read
from edp_api.modules.metric.schemas import (
    MetricCreateRequest,
    MetricItem,
    MetricValueCreate,
    MetricValueItem,
)
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

router = APIRouter(
    prefix="/api/v1/metrics",
    tags=["metrics"],
    dependencies=[Depends(tenant_scoped)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]

_READ_ERRORS = (
    ErrorCode.UNAUTHENTICATED,
    ErrorCode.FORBIDDEN,
    ErrorCode.TENANT_SUSPENDED,
)
_WRITE_ERRORS = (*_READ_ERRORS, ErrorCode.VALIDATION_ERROR)


@router.post(
    "",
    response_model=MetricItem,
    status_code=status.HTTP_201_CREATED,
    summary="注册指标口径（同 code 新版本收旧生效区间）",
    responses=error_responses(*_WRITE_ERRORS),
)
async def create_metric(
    payload: MetricCreateRequest,
    principal: Annotated[Principal, Depends(require_metric_manage())],
    sess: DbSession,
) -> MetricItem:
    return MetricItem.model_validate(
        await metric_service.create_metric(sess, principal, payload)
    )


@router.get(
    "",
    response_model=Page[MetricItem],
    response_model_exclude_none=True,
    summary="指标口径列表（code 过滤 + 游标分页）",
    responses=error_responses(*_READ_ERRORS),
)
async def list_metrics(
    principal: Annotated[Principal, Depends(require_metric_read())],
    sess: DbSession,
    code: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=metric_service.MAX_LIMIT)] = (
        metric_service.DEFAULT_LIMIT
    ),
    cursor: Annotated[str | None, Query()] = None,
) -> Page[MetricItem]:
    return await metric_service.query_metrics(sess, code=code, limit=limit, cursor=cursor)


@router.post(
    "/{metric_id}/values",
    response_model=MetricValueItem,
    status_code=status.HTTP_201_CREATED,
    summary="记录计量值（同 period 覆盖 upsert）",
    responses=error_responses(*_WRITE_ERRORS, ErrorCode.NOT_FOUND),
)
async def record_value(
    metric_id: UUID,
    payload: MetricValueCreate,
    principal: Annotated[Principal, Depends(require_metric_manage())],
    sess: DbSession,
) -> MetricValueItem:
    if await metric_service.get_metric(sess, metric_id) is None:
        raise EdpError.not_found("指标不存在")
    return MetricValueItem.model_validate(
        await metric_service.record_value(sess, principal, metric_id, payload)
    )


@router.get(
    "/{metric_id}/values",
    response_model=list[MetricValueItem],
    summary="计量值列表（period 降序）",
    responses=error_responses(*_READ_ERRORS, ErrorCode.NOT_FOUND),
)
async def list_values(
    metric_id: UUID,
    principal: Annotated[Principal, Depends(require_metric_read())],
    sess: DbSession,
) -> list[MetricValueItem]:
    if await metric_service.get_metric(sess, metric_id) is None:
        raise EdpError.not_found("指标不存在")
    return [
        MetricValueItem.model_validate(item)
        for item in await metric_service.list_values(sess, metric_id)
    ]
