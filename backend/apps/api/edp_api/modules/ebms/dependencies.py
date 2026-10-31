"""ebms 认证增强依赖：require_ebms_read（双轨判定薄委托）。

双轨判定（B.9 / spec §6.1）复用 core.security.rbac.make_require_access：
HUMAN（JWT，kind=HUMAN）走权限轨道 ``ebms:read``（0010 权限码，角色集同
decision:read：PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST）；SERVICE/AI（API Key）
走 scope 轨道 ``readonly``。本文件仅与 tenant_scoped 组装（401/403 租户语义
先于资源授权语义）。
"""

from typing import Annotated

from fastapi import Depends

from edp_api.core.security.principal import Principal
from edp_api.core.security.rbac import make_require_access
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

TenantScoped = Annotated[Principal, Depends(tenant_scoped)]


def require_ebms_read():
    """依赖工厂：tenant_scoped 后接双轨读判定（HUMAN ebms:read / SERVICE readonly）。"""

    check = make_require_access("ebms", "read")

    def dependency(principal: TenantScoped) -> Principal:
        return check(principal)

    return dependency
