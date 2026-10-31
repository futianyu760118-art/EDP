"""quality 认证增强依赖（EDP-030；读报告/触发任务均 JWT 轨道）。

不走 make_require_access 的原因（留痕）：quality:read/run 无 SERVICE
scope 轨道（0013 迁移与 rbac.py 矩阵注释同口径——SERVICE readonly Key
不放行质量面），而 make_require_access("quality", "read") 的 SERVICE 分支
会让持 ``readonly`` scope 的 API Key 通过 scope 轨道，与该口径冲突。故
直接采用 require_permission 权限码判定（SERVICE 主体 roles=[] 无矩阵
权限 → 恒 403 FORBIDDEN），先经 tenant_scoped 绑定租户（租户语义先于
资源授权，与其他模块一致）——手法同 audit_policies.dependencies。
"""

from typing import Annotated

from fastapi import Depends

from edp_api.core.security.principal import Principal
from edp_api.core.security.rbac import require_permission
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

TenantScoped = Annotated[Principal, Depends(tenant_scoped)]

READ_PERMISSION = "quality:read"
RUN_PERMISSION = "quality:run"


def require_quality_read():
    """依赖工厂：tenant_scoped 后接权限码判定（quality:read）。"""

    check = require_permission(READ_PERMISSION)

    def dependency(principal: TenantScoped) -> Principal:
        return check(principal)

    return dependency


def require_quality_run():
    """依赖工厂：tenant_scoped 后接权限码判定（quality:run；T4 任务轨道用）。"""

    check = require_permission(RUN_PERMISSION)

    def dependency(principal: TenantScoped) -> Principal:
        return check(principal)

    return dependency
