"""health 路由（附录 B.13 子集，spec §6.3）：基础健康 + 运行指标。

- GET /api/v1/health：``tenant_scoped``（认证 → 租户状态 → bind_tenant →
  RLS）；基础字段 + ``ops_metrics``（事件流页 KPI 真数据源）；
- ``?deep=true`` 追加 ``require_permission("audit:read")``（HUMAN 权限轨道，
  ADMIN/MANAGER/ANALYST 角色集覆盖；SERVICE Key 无角色 → 403）→ ``db_ha``
  （pg_is_in_recovery / pg_stat_replication）；非 deep 响应经
  ``response_model_exclude_none`` 剔除 db_ha。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import ErrorCode, error_responses
from edp_api.core.security.principal import Principal
from edp_api.core.security.rbac import require_permission
from edp_api.modules.health import service as health_service
from edp_api.modules.health.schemas import HealthResponse
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

router = APIRouter(
    prefix="/api/v1",
    tags=["health"],
    dependencies=[Depends(tenant_scoped)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]
TenantScoped = Annotated[Principal, Depends(tenant_scoped)]

_require_audit_read = require_permission("audit:read")

_DEEP_DESCRIPTION = "深度健康检查（需 audit:read 权限）"


async def require_deep_access(
    principal: TenantScoped,
    deep: Annotated[bool, Query(description=_DEEP_DESCRIPTION)] = False,
) -> Principal:
    """deep=true 时追加 require_permission("audit:read")（非 deep 不判定）。"""
    if deep:
        _require_audit_read(principal)
    return principal


@router.get(
    "/health",
    response_model=HealthResponse,
    response_model_exclude_none=True,
    summary="健康检查与运行指标",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED, ErrorCode.FORBIDDEN, ErrorCode.TENANT_SUSPENDED
    ),
)
async def get_health(
    principal: Annotated[Principal, Depends(require_deep_access)],
    sess: DbSession,
    deep: Annotated[bool, Query(description=_DEEP_DESCRIPTION)] = False,
) -> HealthResponse:
    """基础健康 + ops_metrics；deep=true 返回 db_ha（需 audit:read）。"""
    return await health_service.build_health(sess, principal.tenant_id, deep=deep)
