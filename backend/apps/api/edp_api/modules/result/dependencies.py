"""result 认证增强依赖（V1.2 T17）。

- require_result_read：双轨读——HUMAN ``result:read`` / SERVICE ``readonly``；
- require_result_write：双轨写——HUMAN ``result:write`` / SERVICE scope
  ``write:result``（0015 权限码）。
"""

from typing import Annotated

from fastapi import Depends

from edp_api.core.errors import EdpError
from edp_api.core.security.principal import Principal
from edp_api.core.security.rbac import has_permission, make_require_access
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

TenantScoped = Annotated[Principal, Depends(tenant_scoped)]

WRITE_PERMISSION = "result:write"
WRITE_SCOPE = "write:result"


def require_result_read():
    """依赖工厂：tenant_scoped 后接双轨读判定。"""

    check = make_require_access("result", "read")

    def dependency(principal: TenantScoped) -> Principal:
        return check(principal)

    return dependency


def require_result_write():
    """依赖工厂：HUMAN ``result:write`` / SERVICE scope ``write:result``。"""

    def dependency(principal: TenantScoped) -> Principal:
        if principal.kind == "HUMAN":
            if not has_permission(principal, WRITE_PERMISSION):
                raise EdpError.forbidden(f"缺少权限：{WRITE_PERMISSION}")
            return principal
        if WRITE_SCOPE not in principal.scopes:
            raise EdpError.forbidden(f"缺少 scope：{WRITE_SCOPE}")
        return principal

    return dependency
