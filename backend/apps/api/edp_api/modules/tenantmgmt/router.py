"""tenantmgmt 路由：GET /api/v1/tenants/current（当前租户信息）+
GET /api/v1/tenants/current/usage（本租户使用量，B.14/W3R-04 双轨）。

tenant_scoped（认证 → 租户状态 → bind_tenant）后按 principal.tenant_id
回读控制面租户行（tenants 不受 RLS）；租户行缺失统一 404（不泄露存在性）。
W2 租户生命周期 CRUD（POST /tenants 等，require_platform_admin）见
platform_router.py。
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import EdpError, ErrorCode, error_responses
from edp_api.core.pagination import Page
from edp_api.core.security.principal import Principal
from edp_api.modules.tenantmgmt import service as tenantmgmt_service
from edp_api.modules.tenantmgmt.dependencies import require_tenant_admin, tenant_scoped
from edp_api.modules.tenantmgmt.schemas import TenantInfo, UsageItem

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get(
    "/current",
    response_model=TenantInfo,
    summary="获取当前租户信息",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED, ErrorCode.TENANT_SUSPENDED, ErrorCode.NOT_FOUND
    ),
)
async def current_tenant(
    principal: Annotated[Principal, Depends(tenant_scoped)],
    sess: DbSession,
) -> TenantInfo:
    """当前凭据所属租户的 id/slug/name/plan/status。"""
    tenant = await tenantmgmt_service.get_tenant(sess, principal.tenant_id)
    if tenant is None:
        raise EdpError.not_found("租户不存在")
    return TenantInfo(
        tenant_id=tenant.tenant_id,
        slug=tenant.slug,
        name=tenant.name,
        plan=tenant.plan,
        status=tenant.status,
    )


@router.get(
    "/current/usage",
    response_model=Page[UsageItem],
    response_model_exclude_none=True,
    summary="本租户使用量日报（B.14 租户内 ADMIN 轨道，W3R-04 收口）",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.TENANT_SUSPENDED,
    ),
)
async def current_tenant_usage(
    principal: Annotated[Principal, Depends(require_tenant_admin)],
    sess: DbSession,
    since: Annotated[date | None, Query(description="起始日期（含）")] = None,
    until: Annotated[date | None, Query(description="结束日期（含）")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[UsageItem]:
    """租户内 ADMIN 经 tenant_scoped 查本租户使用量（复用平台面
    query_usage；平台面 GET /tenants/{id}/usage 契约不变）；MANAGER 及
    以下 403（require_tenant_admin）。"""
    items, next_cursor = await tenantmgmt_service.query_usage(
        sess, principal.tenant_id, since=since, until=until, limit=limit, cursor=cursor
    )
    return Page(items=items, next_cursor=next_cursor)
