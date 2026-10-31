"""租户上下文依赖（tenant_scoped）：业务路由统一依赖链（3.3 ②③④ 的落地）。

链路：get_principal（401 语义）→ **act_tenant 归位**（B.14 上下文切换：
principal.act_tenant claim 优先于用户绑定租户，principal.tenant_id 置为
执行租户）→ 租户状态守卫（403 语义，SUSPENDED 目标租户复用既有状态墙）
→ bind_tenant（事务级 app.tenant_id，RLS 隔离键）→ **EDP-025 限流**
（进程内 per-tenant 令牌桶；超限 429 + Retry-After，拒绝经独立会话留痕）
→ **statement_timeout**（租户配额 query_timeout_ms，事务级）→
**api_calls 计量**（独立短会话，不随请求事务持锁）→ contextvar
（current_principal / current_tenant_id，供审计/日志携带）。业务路由
（registry/events 等）统一 ``Depends(tenant_scoped)``，勿各自拼接。
auth / 租户管理等平台级路由不挂（天然不受限流与计量）。
"""

from dataclasses import replace
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.contextvars import current_principal, current_tenant_id
from edp_api.core.db import bind_tenant, get_db
from edp_api.core.errors import EdpError
from edp_api.core.security.auth import get_principal
from edp_api.core.security.principal import Principal
from edp_api.core.tenant_context import ensure_tenant_usable
from edp_api.modules.tenantmgmt import ratelimit
from edp_api.modules.tenantmgmt import service as tenantmgmt_service


async def tenant_scoped(
    request: Request,
    sess: Annotated[AsyncSession, Depends(get_db)],
) -> Principal:
    """业务路由统一依赖：认证 → 执行租户归位 → 租户状态 → bind_tenant →
    限流 → statement_timeout → 用量计数 → contextvar。

    - get_principal：Bearer（claims.tenant_id）或 X-API-Key（key 绑定租户），
      无有效凭据 → 401；
    - act_tenant 归位（B.14，W5）：claims 带 act_tenant（平台 ADMIN 经
      POST /tenants/{id}/context 重签）时以目标租户执行——principal.tenant_id
      原地替换为执行租户，后续限流/配额/RLS 绑定/审计 contextvar 全链一致；
      目标租户 SUSPENDED/CANCELLED 由下方既有状态墙统一 403
      TENANT_SUSPENDED（切换时已拦，后续请求复拦即时生效）；
    - tenants 为控制面表（不受 RLS），状态查询可在绑定前执行。
    """
    principal = await get_principal(request)
    if principal.act_tenant is not None:
        principal = replace(principal, tenant_id=principal.act_tenant)
    status = await tenantmgmt_service.get_tenant_status(sess, principal.tenant_id)
    ensure_tenant_usable(status)
    await bind_tenant(sess, principal.tenant_id)

    quota = await tenantmgmt_service.get_quota(sess, principal.tenant_id)
    retry_after, near_limit = ratelimit.check_rate_limit(
        principal.tenant_id, quota.api_rate_limit
    )
    if retry_after > 0:
        # 请求将 429，请求事务回滚——审计/计数经独立会话提交
        await ratelimit.record_rate_limited(
            principal,
            path=request.url.path,
            retry_after=retry_after,
            limit_per_min=quota.api_rate_limit,
        )
        raise EdpError.rate_limited(
            f"请求超出租户限流（{quota.api_rate_limit} req/min）",
            extra={"retry_after": retry_after},
        )
    if near_limit:
        await ratelimit.record_rate_warning(
            principal, path=request.url.path, limit_per_min=quota.api_rate_limit
        )
    # SET 不支持绑定参数；query_timeout_ms 为整型列，内插安全
    await sess.execute(
        text(f"SET LOCAL statement_timeout = {int(quota.query_timeout_ms)}")
    )
    # api_calls 计量走独立短会话（usage 行锁不随请求事务持有——见
    # ratelimit.record_api_call docstring）
    await ratelimit.record_api_call(principal.tenant_id)

    current_principal.set(principal)
    current_tenant_id.set(principal.tenant_id)
    return principal


async def require_tenant_admin(
    principal: Annotated[Principal, Depends(tenant_scoped)],
) -> Principal:
    """租户内 ADMIN 轨道（B.14 / W3R-04）：tenant_scoped 之后的角色门槛——
    ADMIN（或平台 ADMIN 通配）放行；MANAGER 及以下 403 FORBIDDEN。
    GET /tenants/current/usage 等租户视角管理面端点使用。"""
    if principal.is_platform_admin or "ADMIN" in principal.roles:
        return principal
    raise EdpError.forbidden("需要租户 ADMIN 角色")


def ensure_members_readable(principal: Principal, tenant_id: UUID) -> None:
    """GET /tenants/{id}/members 双轨判定（B.14：平台 ADMIN / 租户内 ADMIN）。

    平台 ADMIN 放行；主体绑定租户 = 目标租户且角色含 ADMIN 放行（租户内
    ADMIN 仅可读本租户）；本租户但非 ADMIN → 403 FORBIDDEN；他租户统一
    404 NOT_FOUND（不泄露存在性）。仅在平台路由上做主体判定，不替代
    tenant_scoped（SUSPENDED 状态墙不在此层，业务面仍由 tenant_scoped 拦）。
    """
    if principal.is_platform_admin:
        return
    if principal.tenant_id == tenant_id:
        if "ADMIN" in principal.roles:
            return
        raise EdpError.forbidden("需要租户 ADMIN 角色")
    raise EdpError.not_found("租户不存在")
