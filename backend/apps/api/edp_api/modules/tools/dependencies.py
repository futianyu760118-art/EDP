"""tools 认证增强依赖：require_tools_read（双轨判定 + GUARD_DENIED 审计）。

双轨判定（B.8 / 设计 8.3）复用 core.security.rbac.make_require_access 单点
实现：服务主体（API Key，kind=SERVICE/AI）走 scope 轨道 ``readonly``；
人主体（JWT，kind=HUMAN）走权限轨道 ``tools:read``（0010 权限码，角色集
PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST，RBAC 常量同步见 core.security.rbac）。
与 events/adapters_admin 的薄委托不同——本依赖是 Read-Only 三层的审计层
（8.3 ③）：拒绝时**先**落 GUARD_DENIED 审计行（resource_type=tools，detail
含请求 path/原因/scopes）**再**抛 403，支撑「AI 越权 0 次」度量与告警联动。

拒绝审计走**独立会话**（core.db.get_session_local 新建 + bind_tenant +
record_explicit + commit + close），不复用请求会话：请求随后抛 403，get_db
会回滚请求事务，若在请求会话内提交将产生部分提交（请求语义已失败而事务
残留）；独立会话与请求事务解耦，审计失败仅 warning，不改变 403 决策。
"""

import logging
from typing import Annotated

from fastapi import Depends, Request

from edp_api.core import db as core_db
from edp_api.core.db import bind_tenant
from edp_api.core.errors import EdpError, ErrorCode
from edp_api.core.security.principal import Principal
from edp_api.core.security.rbac import make_require_access
from edp_api.modules.audit import service as audit_service
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

logger = logging.getLogger(__name__)

TenantScoped = Annotated[Principal, Depends(tenant_scoped)]


def require_tools_read():
    """依赖工厂：tenant_scoped → 双轨读判定；拒绝先落 GUARD_DENIED 审计再 403。"""

    check = make_require_access("tools", "read")

    async def dependency(request: Request, principal: TenantScoped) -> Principal:
        try:
            return check(principal)
        except EdpError as exc:
            if exc.code == ErrorCode.FORBIDDEN:
                await _record_guard_denied(principal, request.url.path, exc.message)
            raise

    return dependency


async def _record_guard_denied(principal: Principal, path: str, reason: str) -> None:
    """独立会话落 GUARD_DENIED 审计（拒绝路径专用；失败仅 warning）。"""
    try:
        session = core_db.get_session_local()()
        try:
            # 与请求路径同一 RLS 绑定约定（audit_logs 当前为控制面表，
            # 绑定为纵深一致性；后续若启用 RLS 亦不漏租户）
            await bind_tenant(session, principal.tenant_id)
            await audit_service.record_explicit(
                session,
                action="GUARD_DENIED",
                resource_type="tools",
                resource_id=None,
                detail={
                    "path": path,
                    "reason": reason,
                    "scopes": list(principal.scopes),
                },
                principal=principal,
            )
            await session.commit()
        finally:
            await session.close()
    except Exception:
        logger.warning("GUARD_DENIED 审计落库失败", exc_info=True)
