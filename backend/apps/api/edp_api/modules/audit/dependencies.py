"""audit 认证增强依赖：require_read（薄委托，镜像 registry/dependencies.py）。

双轨判定语义归 core.security.rbac.make_require_access 单点实现：JWT 人主体
走权限轨道 ``audit:read``（RBAC 矩阵：PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST
均有），API Key 服务主体走 scope 轨道 ``readonly``。本文件仅将其与
tenant_scoped 组装（401/403 租户语义先于资源授权语义）。
"""

from typing import Annotated

from fastapi import Depends

from edp_api.core.security.principal import Principal
from edp_api.core.security.rbac import make_require_access
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

TenantScoped = Annotated[Principal, Depends(tenant_scoped)]


def require_read(resource: str):
    """依赖工厂：tenant_scoped 后接双轨读判定（语义见 make_require_access）。"""

    check = make_require_access(resource, "read")

    def dependency(principal: TenantScoped) -> Principal:
        return check(principal)

    return dependency
