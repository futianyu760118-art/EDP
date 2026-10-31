"""audit 路由（附录 B.6）：GET /audit-logs（过滤 + 游标分页）。

router 级挂 tenant_scoped（认证 → 租户状态 → bind_tenant → contextvar）；
audit_logs 为控制面表（不启用 RLS），租户收敛由 service 查询的显式
tenant_id 条件完成（is_platform_admin 见全量）。
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import ErrorCode, error_responses
from edp_api.core.pagination import Page
from edp_api.core.security.principal import Principal
from edp_api.modules.audit import service as audit_service
from edp_api.modules.audit.dependencies import require_read
from edp_api.modules.audit.schemas import AuditLogItem
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

router = APIRouter(
    prefix="/api/v1/audit-logs",
    tags=["audit"],
    dependencies=[Depends(tenant_scoped)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get(
    "",
    response_model=Page[AuditLogItem],
    response_model_exclude_none=True,
    summary="查询审计日志（过滤 + 游标分页）",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED, ErrorCode.FORBIDDEN, ErrorCode.TENANT_SUSPENDED
    ),
)
async def list_audit_logs(
    principal: Annotated[Principal, Depends(require_read("audit"))],
    sess: DbSession,
    actor_id: Annotated[str | None, Query()] = None,
    resource_type: Annotated[str | None, Query()] = None,
    action: Annotated[str | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = audit_service.DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[AuditLogItem]:
    """过滤（actor_id/resource_type/action/since/until 闭区间）+ 游标分页
    （occurred_at DESC, audit_id tiebreak）；非平台管理员仅见本租户。"""
    return await audit_service.query_logs(
        sess,
        principal,
        actor_id=actor_id,
        resource_type=resource_type,
        action=action,
        since=since,
        until=until,
        limit=limit,
        cursor=cursor,
    )
