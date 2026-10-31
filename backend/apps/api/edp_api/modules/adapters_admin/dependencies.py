"""adapters_admin 认证增强依赖：require_read / require_write（薄委托）。

双轨判定语义（B.12）归 core.security.rbac.make_require_access 单点实现：
服务主体（API Key，kind = SERVICE/AI）走 scope 轨道——写 = ``write:adapters``、
读 = ``readonly``；人主体（JWT，kind = HUMAN）走权限轨道
``adapters:read|write``（RBAC 矩阵，0008 种子）。本文件仅将其与
tenant_scoped 组装（401/403 租户语义先于资源授权语义）。
"""

from typing import Annotated

from fastapi import Depends

from edp_api.core.security.principal import Principal
from edp_api.core.security.rbac import make_require_access
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

TenantScoped = Annotated[Principal, Depends(tenant_scoped)]


def require_write(resource: str):
    """依赖工厂：tenant_scoped 后接双轨写判定（语义见 make_require_access）。"""

    check = make_require_access(resource, "write")

    def dependency(principal: TenantScoped) -> Principal:
        return check(principal)

    return dependency


def require_read(resource: str):
    """依赖工厂：tenant_scoped 后接双轨读判定（语义见 make_require_access）。"""

    check = make_require_access(resource, "read")

    def dependency(principal: TenantScoped) -> Principal:
        return check(principal)

    return dependency
