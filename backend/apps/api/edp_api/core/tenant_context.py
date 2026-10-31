"""租户上下文纯逻辑：租户状态判定规则（设计文档 3.3 传播链 ②）。

core 不得 import modules（import-linter 契约），而租户状态的 DB 查询在
tenantmgmt.service——故本文件只提供无 IO 的判定函数，FastAPI 依赖组装
在 modules/tenantmgmt/dependencies.py（tenant_scoped），Worker 按租户
循环时亦可复用（T13）。
"""

from edp_api.core.errors import EdpError, ErrorCode

_ACTIVE = "ACTIVE"
_BLOCKED = frozenset({"SUSPENDED", "CANCELLED"})


def ensure_tenant_usable(status: str | None) -> None:
    """租户状态守卫（3.3）：ACTIVE 放行；SUSPENDED/CANCELLED → 403
    TENANT_SUSPENDED（数据保留、API 即时拒绝）；其余状态（PROVISIONING、
    未知、租户不存在 → None）→ 403 TENANT_FORBIDDEN。"""
    if status == _ACTIVE:
        return
    if status in _BLOCKED:
        raise EdpError.tenant_suspended()
    raise EdpError(
        ErrorCode.TENANT_FORBIDDEN,
        "租户不可用" if status is not None else "租户不存在",
    )
