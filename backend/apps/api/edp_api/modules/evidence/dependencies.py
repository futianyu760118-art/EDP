"""evidence 认证增强依赖：require_read / require_write（薄委托）+ 重索引触发。

双轨判定语义归 core.security.rbac.make_require_access 单点实现：服务主体
（API Key，kind = SERVICE/AI）走 scope 轨道——写 = ``write:evidence``、
读 = ``readonly``；人主体（JWT，kind = HUMAN）走权限轨道
``evidence:read|write``（RBAC 矩阵）。与 registry/dependencies.py 同构。

重索引（W3-04 收口）不设 SERVICE scope 轨道，权限**复用 quality:run**
（require_permission 同 T3/T4 口径——重索引为质量运营动作，不新注册权限
码；SERVICE 主体 roles=[] 无矩阵权限 → 恒 403），手法同
quality.dependencies（先经 tenant_scoped 绑定租户，租户语义先于资源授权）。
"""

from typing import Annotated

from fastapi import Depends

from edp_api.core.security.principal import Principal
from edp_api.core.security.rbac import make_require_access, require_permission
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

TenantScoped = Annotated[Principal, Depends(tenant_scoped)]

REINDEX_RUN_PERMISSION = "quality:run"


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


def require_reindex_run():
    """依赖工厂：tenant_scoped 后接权限码判定（quality:run 复用，见模块
    docstring——POST /admin/evidence/reindex 触发守卫）。"""

    check = require_permission(REINDEX_RUN_PERMISSION)

    def dependency(principal: TenantScoped) -> Principal:
        return check(principal)

    return dependency
