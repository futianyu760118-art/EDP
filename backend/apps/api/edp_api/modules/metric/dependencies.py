"""metric 认证增强依赖（V1.2 T23）。

- require_metric_read：双轨读——HUMAN ``metric:read`` / SERVICE ``readonly``；
- require_metric_manage：双轨写——HUMAN ``metric:manage`` / SERVICE scope
  ``write:metric``（0016 权限码；value ledger 复用本轨道）。
"""

from typing import Annotated

from fastapi import Depends

from edp_api.core.errors import EdpError
from edp_api.core.security.principal import Principal
from edp_api.core.security.rbac import has_permission, make_require_access
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

TenantScoped = Annotated[Principal, Depends(tenant_scoped)]

MANAGE_PERMISSION = "metric:manage"
MANAGE_SCOPE = "write:metric"


def require_metric_read():
    """依赖工厂：tenant_scoped 后接双轨读判定。"""

    check = make_require_access("metric", "read")

    def dependency(principal: TenantScoped) -> Principal:
        return check(principal)

    return dependency


def require_metric_manage():
    """依赖工厂：HUMAN ``metric:manage`` / SERVICE scope ``write:metric``。"""

    def dependency(principal: TenantScoped) -> Principal:
        if principal.kind == "HUMAN":
            if not has_permission(principal, MANAGE_PERMISSION):
                raise EdpError.forbidden(f"缺少权限：{MANAGE_PERMISSION}")
            return principal
        if MANAGE_SCOPE not in principal.scopes:
            raise EdpError.forbidden(f"缺少 scope：{MANAGE_SCOPE}")
        return principal

    return dependency
