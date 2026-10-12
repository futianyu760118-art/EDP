"""governance 认证增强依赖（V1.2）。

- require_governance_read：双轨读——HUMAN ``governance:read`` / SERVICE
  ``readonly``（make_require_access 薄委托）；
- require_governance_manage：双轨写——HUMAN ``governance:manage`` /
  SERVICE scope ``write:governance``（0014 权限码；dev Key scope 收口
  任务补写）；
- require_admission_review：Human-Only 审核——非 HUMAN 直接 403
  FORBIDDEN（GUARD_DENIED 审计由 service 落），HUMAN 需
  ``admission:review``。
"""

from typing import Annotated

from fastapi import Depends

from edp_api.core.errors import EdpError
from edp_api.core.security.principal import Principal
from edp_api.core.security.rbac import has_permission, make_require_access
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

TenantScoped = Annotated[Principal, Depends(tenant_scoped)]

MANAGE_PERMISSION = "governance:manage"
REVIEW_PERMISSION = "admission:review"
MANAGE_SCOPE = "write:governance"


def require_governance_read():
    """依赖工厂：tenant_scoped 后接双轨读判定（语义见 make_require_access）。"""

    check = make_require_access("governance", "read")

    def dependency(principal: TenantScoped) -> Principal:
        return check(principal)

    return dependency


def require_governance_manage():
    """依赖工厂：HUMAN ``governance:manage`` / SERVICE scope ``write:governance``。"""

    def dependency(principal: TenantScoped) -> Principal:
        if principal.kind == "HUMAN":
            if not has_permission(principal, MANAGE_PERMISSION):
                raise EdpError.forbidden(f"缺少权限：{MANAGE_PERMISSION}")
            return principal
        if MANAGE_SCOPE not in principal.scopes:
            raise EdpError.forbidden(f"缺少 scope：{MANAGE_SCOPE}")
        return principal

    return dependency


def require_admission_review():
    """依赖工厂：Human-Only + ``admission:review``（SERVICE/AI 一律 403）。"""

    def dependency(principal: TenantScoped) -> Principal:
        if principal.kind != "HUMAN":
            raise EdpError.forbidden("该操作仅限人工执行（Human-Only）")
        if not has_permission(principal, REVIEW_PERMISSION):
            raise EdpError.forbidden(f"缺少权限：{REVIEW_PERMISSION}")
        return principal

    return dependency
