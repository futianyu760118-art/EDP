"""decisions 认证增强依赖（B.5 / 设计 8.4）。

- require_decision_read：双轨读判定——HUMAN ``decision:read`` / SERVICE
  ``readonly``（make_require_access 薄委托）；
- require_case_create：HUMAN ``decision:decide`` / SERVICE scope
  ``write:decision``（0010 已为 dev Key 追加）；
- require_decision_decide：**Human-Only**——非 HUMAN 经 service 层
  ``record_guard_denied``（独立会话提交）落 GUARD_DENIED 审计后抛 403
  GUARD_POLICY_DENIED；HUMAN 需 ``decision:decide``（MANAGER 及以上角色
  矩阵已含）。

拒绝审计走独立会话（与 tools 同一模式，唯一实现见 decisions.service.
record_guard_denied）：请求随后抛 403，请求事务回滚，审计不能依赖请求
会话；独立会话与请求事务解耦，审计失败仅 warning，不改变 403 决策。
"""

from typing import Annotated

from fastapi import Depends, Request

from edp_api.core.errors import EdpError
from edp_api.core.security.principal import Principal
from edp_api.core.security.rbac import has_permission, make_require_access
from edp_api.modules.decisions.service import (
    HUMAN_ONLY_MESSAGE,
    HUMAN_ONLY_REASON,
    record_guard_denied,
)
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

TenantScoped = Annotated[Principal, Depends(tenant_scoped)]

DECIDE_PERMISSION = "decision:decide"
CREATE_SCOPE = "write:decision"


def require_decision_read():
    """依赖工厂：tenant_scoped 后接双轨读判定（语义见 make_require_access）。"""

    check = make_require_access("decision", "read")

    def dependency(principal: TenantScoped) -> Principal:
        return check(principal)

    return dependency


def require_case_create():
    """依赖工厂：HUMAN ``decision:decide`` / SERVICE scope ``write:decision``。"""

    def dependency(principal: TenantScoped) -> Principal:
        if principal.kind == "HUMAN":
            if not has_permission(principal, DECIDE_PERMISSION):
                raise EdpError.forbidden(f"缺少权限：{DECIDE_PERMISSION}")
            return principal
        if CREATE_SCOPE not in principal.scopes:
            raise EdpError.forbidden(f"缺少 scope：{CREATE_SCOPE}")
        return principal

    return dependency


def require_decision_decide():
    """依赖工厂：Human-Only（非 HUMAN 审计后 GUARD_POLICY_DENIED）+ 人工权限。"""

    async def dependency(request: Request, principal: TenantScoped) -> Principal:
        if principal.kind != "HUMAN":
            await record_guard_denied(
                principal,
                path=request.url.path,
                reason=HUMAN_ONLY_REASON,
                resource_id=request.path_params.get("case_id"),
            )
            raise EdpError.guard_policy_denied(HUMAN_ONLY_MESSAGE)
        if not has_permission(principal, DECIDE_PERMISSION):
            raise EdpError.forbidden(f"缺少权限：{DECIDE_PERMISSION}")
        return principal

    return dependency
