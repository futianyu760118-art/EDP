"""traces 认证增强依赖：require_read / require_write（薄委托）。

双轨判定语义（B.10）归 core.security.rbac.make_require_access 单点实现：
服务主体（API Key，kind = SERVICE/AI）走 scope 轨道——写 = ``write:trace``
（dev Key 0011 已追加）、读 = ``readonly``；人主体（JWT，kind = HUMAN）走
权限轨道 ``trace:read|write``（0011 矩阵：trace:read → PLATFORM_ADMIN/
ADMIN/MANAGER/ANALYST；**无任何角色持有 trace:write**——B.10 写仅 API Key，
HUMAN 写 → 403 由 make_require_access 天然给出）。本文件仅将其与
tenant_scoped 组装（401/403 租户语义先于资源授权语义）。
"""

from typing import Annotated

from fastapi import Depends

from edp_api.core.security.principal import Principal
from edp_api.core.security.rbac import make_require_access
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

TenantScoped = Annotated[Principal, Depends(tenant_scoped)]

RESOURCE = "trace"


def require_write():
    """依赖工厂：tenant_scoped 后接双轨写判定（HUMAN 恒 403——无角色持有
    trace:write；SERVICE 需 write:trace scope）。"""

    check = make_require_access(RESOURCE, "write")

    def dependency(principal: TenantScoped) -> Principal:
        return check(principal)

    return dependency


def require_read():
    """依赖工厂：tenant_scoped 后接双轨读判定（JWT trace:read / readonly）。"""

    check = make_require_access(RESOURCE, "read")

    def dependency(principal: TenantScoped) -> Principal:
        return check(principal)

    return dependency
