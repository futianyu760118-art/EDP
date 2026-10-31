"""memories 认证增强依赖（B.11 / 设计 8.2 Human-Only）。

- require_memory_read：双轨读判定——HUMAN ``memory:read`` / SERVICE
  ``readonly``（make_require_access 薄委托）；
- require_memory_write：双轨写判定——HUMAN ``memory:write``（无角色持有，
  写入仅服务主体）/ SERVICE scope ``write:memory``（0011 已为 dev Key 追加）；
- require_memory_review：**Human-Only**——非 HUMAN 经 service 层
  ``record_guard_denied``（独立会话提交）落 GUARD_DENIED 审计后抛 403
  GUARD_POLICY_DENIED；HUMAN 需 ``memory:review``（0011 角色矩阵：
  PLATFORM_ADMIN/ADMIN/MANAGER）。

拒绝审计走独立会话（与 tools/decisions 同一模式，唯一实现见
memories.service.record_guard_denied）：请求随后抛 403，请求事务回滚，
审计不能依赖请求会话；独立会话与请求事务解耦，审计失败仅 warning。
"""

from typing import Annotated

from fastapi import Depends, Request

from edp_api.core.errors import EdpError
from edp_api.core.security.principal import Principal
from edp_api.core.security.rbac import has_permission, make_require_access
from edp_api.modules.memories.service import (
    HUMAN_ONLY_MESSAGE,
    HUMAN_ONLY_REASON,
    record_guard_denied,
)
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

TenantScoped = Annotated[Principal, Depends(tenant_scoped)]

REVIEW_PERMISSION = "memory:review"


def require_memory_read():
    """依赖工厂：tenant_scoped 后接双轨读判定（语义见 make_require_access）。"""

    check = make_require_access("memory", "read")

    def dependency(principal: TenantScoped) -> Principal:
        return check(principal)

    return dependency


def require_memory_write():
    """依赖工厂：tenant_scoped 后接双轨写判定（HUMAN 无 memory:write → 403）。"""

    check = make_require_access("memory", "write")

    def dependency(principal: TenantScoped) -> Principal:
        return check(principal)

    return dependency


def require_memory_review():
    """依赖工厂：Human-Only（非 HUMAN 审计后 GUARD_POLICY_DENIED）+ 人工权限。"""

    async def dependency(request: Request, principal: TenantScoped) -> Principal:
        if principal.kind != "HUMAN":
            await record_guard_denied(
                principal,
                path=request.url.path,
                reason=HUMAN_ONLY_REASON,
                resource_id=request.path_params.get("memory_id"),
            )
            raise EdpError.guard_policy_denied(HUMAN_ONLY_MESSAGE)
        if not has_permission(principal, REVIEW_PERMISSION):
            raise EdpError.forbidden(f"缺少权限：{REVIEW_PERMISSION}")
        return principal

    return dependency
