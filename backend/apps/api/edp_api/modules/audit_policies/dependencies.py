"""audit_policies 认证增强依赖（EDP-032；策略管理仅 JWT 轨道）。

不走 make_require_access 的原因（留痕）：make_require_access(resource,
mode) 按 ``{resource}:{mode}`` 拼权限码、按 ``write:{resource}`` 拼 scope
——本模块权限码为 0012 的 ``audit:policy_read`` / ``audit:policy_write``
（resource=audit、action=policy_read/policy_write），make_require_access(
"audit_policy", ...) 会拼出不存在的 ``audit_policy:read``，均不匹配；
SERVICE/API Key 轨道亦无对应 scope（策略仅人工管理，rbac.py 矩阵注释
同口径）。故直接采用 require_permission 权限码判定（rbac.py 既有工厂），
先经 tenant_scoped 绑定租户（租户语义先于资源授权，与其他模块一致）。
"""

from typing import Annotated

from fastapi import Depends

from edp_api.core.security.principal import Principal
from edp_api.core.security.rbac import require_permission
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

TenantScoped = Annotated[Principal, Depends(tenant_scoped)]

READ_PERMISSION = "audit:policy_read"
WRITE_PERMISSION = "audit:policy_write"


def require_policy_read():
    """依赖工厂：tenant_scoped 后接权限码判定（audit:policy_read）。"""

    check = require_permission(READ_PERMISSION)

    def dependency(principal: TenantScoped) -> Principal:
        return check(principal)

    return dependency


def require_policy_write():
    """依赖工厂：tenant_scoped 后接权限码判定（audit:policy_write）。"""

    check = require_permission(WRITE_PERMISSION)

    def dependency(principal: TenantScoped) -> Principal:
        return check(principal)

    return dependency
