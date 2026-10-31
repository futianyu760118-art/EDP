"""actions 认证增强依赖（B.5 / 设计 8.4）。

- require_action_read：双轨读判定——HUMAN ``action:read`` / SERVICE
  ``readonly``（make_require_access 薄委托，0005 基线权限码）；
- require_action_execute：双轨写判定——HUMAN ``action:execute`` / SERVICE
  scope ``write:action``（0012 已为 dev Key 追加）。矩阵无 ``action:write``
  码（写权限即 execute），故不走 make_require_access 的 mode 拼名，与
  decisions.require_case_create 同构手写双轨。

Human-Only 转移守卫不在依赖层（依赖层不知道 to_status）——由 service.
transition_action 按 TRANSITIONS 边属性判定并落 GUARD_DENIED 审计。
"""

from typing import Annotated

from fastapi import Depends

from edp_api.core.errors import EdpError
from edp_api.core.security.principal import Principal
from edp_api.core.security.rbac import has_permission, make_require_access
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

TenantScoped = Annotated[Principal, Depends(tenant_scoped)]

EXECUTE_PERMISSION = "action:execute"
WRITE_SCOPE = "write:action"


def require_action_read():
    """依赖工厂：tenant_scoped 后接双轨读判定（语义见 make_require_access）。"""

    check = make_require_access("action", "read")

    def dependency(principal: TenantScoped) -> Principal:
        return check(principal)

    return dependency


def require_action_execute():
    """依赖工厂：HUMAN ``action:execute`` / SERVICE scope ``write:action``。"""

    def dependency(principal: TenantScoped) -> Principal:
        if principal.kind == "HUMAN":
            if not has_permission(principal, EXECUTE_PERMISSION):
                raise EdpError.forbidden(f"缺少权限：{EXECUTE_PERMISSION}")
            return principal
        if WRITE_SCOPE not in principal.scopes:
            raise EdpError.forbidden(f"缺少 scope：{WRITE_SCOPE}")
        return principal

    return dependency
