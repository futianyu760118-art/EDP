"""tenantmgmt 平台级路由（EDP-024 / B.14）：租户生命周期 + W5 补齐
（PATCH / context 切换 / members CRUD / quotas 读改，EDP-501 后端）+
W6 平台用户目录（GET /api/v1/admin/users，W5-11 收口）。

与 router.py（GET /tenants/current[+/usage]，租户视角 tenant_scoped）相对，
本路由为平台运营视角：每路由 require_platform_admin + get_db，**不挂
tenant_scoped**——平台管理员跨租户操作控制面（tenants / tenant_quotas
无 RLS；users / tenant_members 的读写由 service 在 bind_tenant 目标租户
后完成）。例外：GET members 双轨（平台 ADMIN 之外，主体为该租户 ADMIN
时放行——ensure_members_readable，B.14 租户内 ADMIN 限本租户）。
"""

from datetime import UTC, date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import EdpError, ErrorCode, error_responses
from edp_api.core.pagination import Page
from edp_api.core.security.auth import get_principal
from edp_api.core.security.principal import Principal
from edp_api.modules.platform.dependencies import require_platform_admin
from edp_api.modules.tenantmgmt import service as tenantmgmt_service
from edp_api.modules.tenantmgmt.dependencies import ensure_members_readable
from edp_api.modules.tenantmgmt.schemas import (
    AdminUserItem,
    TenantCancelRequest,
    TenantContextResponse,
    TenantCreateRequest,
    TenantCreateResponse,
    TenantDetail,
    TenantLifecycleResponse,
    TenantMemberCreateRequest,
    TenantMemberItem,
    TenantMemberUpdateRequest,
    TenantQuotaDetail,
    TenantQuotaUpdateRequest,
    TenantSummary,
    TenantUpdateRequest,
    UsageItem,
)

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])

admin_router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
PlatformAdmin = Annotated[Principal, Depends(require_platform_admin)]
AnyPrincipal = Annotated[Principal, Depends(get_principal)]


@router.post(
    "",
    status_code=201,
    response_model=TenantCreateResponse,
    summary="开通租户（含初始管理员与计划配额）",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.CONFLICT,
    ),
)
async def create_tenant(
    payload: TenantCreateRequest, sess: DbSession, principal: PlatformAdmin
) -> TenantCreateResponse:
    """单事务开通：tenants(ACTIVE) + tenant_quotas（PLAN_QUOTAS[plan]）+
    初始管理员 users + tenant_members(ADMIN)；请求未携带 admin.password 时
    响应回传一次性临时口令（B.14 扩展）。租户编码服务端自动生成
    （ten-YYYY-NNNN，next_tenant_code 原子取号）；编码撞号 → 409（防御）。"""
    tenant, admin_user, temporary_password = await tenantmgmt_service.create_tenant(
        sess, payload, principal.id
    )
    return TenantCreateResponse(
        tenant_id=tenant.tenant_id,
        slug=tenant.slug,
        name=tenant.name,
        status=tenant.status,
        created_at=tenant.created_at,
        initial_admin_user_id=admin_user.user_id,
        temporary_password=temporary_password,
    )


@router.get(
    "",
    response_model=Page[TenantSummary],
    response_model_exclude_none=True,
    summary="租户清单（过滤 + 游标分页）",
    responses=error_responses(ErrorCode.UNAUTHENTICATED, ErrorCode.FORBIDDEN),
)
async def list_tenants(
    sess: DbSession,
    principal: PlatformAdmin,
    status: Annotated[str | None, Query()] = None,
    plan: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = tenantmgmt_service.DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[TenantSummary]:
    """status / plan 过滤 + 游标分页（created_at DESC，tenant_id tiebreak）。"""
    return await tenantmgmt_service.list_tenants(
        sess, status=status, plan=plan, limit=limit, cursor=cursor
    )


@router.get(
    "/{tenant_id}",
    response_model=TenantDetail,
    summary="租户详情（配额与用量）",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED, ErrorCode.FORBIDDEN, ErrorCode.NOT_FOUND
    ),
)
async def get_tenant(
    tenant_id: UUID, sess: DbSession, principal: PlatformAdmin
) -> TenantDetail:
    """基本信息 + 配额行 + 用量（MVP 可空）；不存在 → 404。"""
    return await tenantmgmt_service.get_tenant_detail(sess, tenant_id)


@router.patch(
    "/{tenant_id}",
    response_model=TenantDetail,
    summary="更新租户（name / plan；B.14）",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.NOT_FOUND,
        ErrorCode.VALIDATION_ERROR,
    ),
)
async def update_tenant(
    tenant_id: UUID,
    payload: TenantUpdateRequest,
    sess: DbSession,
    principal: PlatformAdmin,
) -> TenantDetail:
    """name / plan 局部更新 → 200 更新后完整租户对象。**plan 变更仅记录
    不调配额**（TENANTS_UPDATE 审计行留痕；配额调整唯一入口 PATCH
    /quotas，见 service.update_tenant docstring）；不存在 → 404。"""
    await tenantmgmt_service.update_tenant(
        sess, tenant_id, payload, actor_id=principal.id
    )
    return await tenantmgmt_service.get_tenant_detail(sess, tenant_id)


@router.post(
    "/{tenant_id}/suspend",
    status_code=202,
    response_model=TenantLifecycleResponse,
    summary="暂停租户（ACTIVE → SUSPENDED）",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.NOT_FOUND,
        ErrorCode.INVALID_TRANSITION,
    ),
)
async def suspend_tenant(
    tenant_id: UUID, sess: DbSession, principal: PlatformAdmin
) -> TenantLifecycleResponse:
    """暂停后该租户全部业务 API 即时 403 TENANT_SUSPENDED（3.3 状态墙）。"""
    tenant = await tenantmgmt_service.set_tenant_status(
        sess, tenant_id, "SUSPENDED", "suspend", actor_id=principal.id
    )
    return TenantLifecycleResponse(
        tenant_id=tenant.tenant_id,
        status=tenant.status,
        operation="suspend",
        occurred_at=tenant.updated_at,
    )


@router.post(
    "/{tenant_id}/resume",
    status_code=202,
    response_model=TenantLifecycleResponse,
    summary="恢复租户（SUSPENDED → ACTIVE）",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.NOT_FOUND,
        ErrorCode.INVALID_TRANSITION,
    ),
)
async def resume_tenant(
    tenant_id: UUID, sess: DbSession, principal: PlatformAdmin
) -> TenantLifecycleResponse:
    """恢复后业务 API 立即复通（数据未动，直接回到 ACTIVE）。"""
    tenant = await tenantmgmt_service.set_tenant_status(
        sess, tenant_id, "ACTIVE", "resume", actor_id=principal.id
    )
    return TenantLifecycleResponse(
        tenant_id=tenant.tenant_id,
        status=tenant.status,
        operation="resume",
        occurred_at=tenant.updated_at,
    )


@router.post(
    "/{tenant_id}/cancel",
    status_code=202,
    response_model=TenantLifecycleResponse,
    summary="注销租户（强确认，30 天数据保留窗口）",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.NOT_FOUND,
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.INVALID_TRANSITION,
    ),
)
async def cancel_tenant(
    tenant_id: UUID,
    payload: TenantCancelRequest,
    sess: DbSession,
    principal: PlatformAdmin,
) -> TenantLifecycleResponse:
    """需 body.confirm=true 且 reason 非空；受理后写 cancel_scheduled_at =
    now + 30 天（保留窗口到期清数据，W4 定时任务）。重复注销 → 422。"""
    tenant = await tenantmgmt_service.set_tenant_status(
        sess,
        tenant_id,
        "CANCELLED",
        "cancel",
        confirm=payload.confirm,
        reason=payload.reason,
        actor_id=principal.id,
    )
    return TenantLifecycleResponse(
        tenant_id=tenant.tenant_id,
        status=tenant.status,
        operation="cancel",
        occurred_at=tenant.updated_at,
    )


@router.post(
    "/{tenant_id}/context",
    response_model=TenantContextResponse,
    summary="切换自身会话的目标租户上下文（B.14）",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.TENANT_SUSPENDED,
        ErrorCode.TENANT_FORBIDDEN,
        ErrorCode.NOT_FOUND,
    ),
)
async def switch_tenant_context(
    tenant_id: UUID, sess: DbSession, principal: PlatformAdmin
) -> TenantContextResponse:
    """平台 ADMIN 把自身会话切到目标租户执行：目标须 ACTIVE（SUSPENDED/
    CANCELLED → 403 TENANT_SUSPENDED——复用既有租户状态墙；不存在 404），
    通过后重签 access token（claims 附加 act_tenant，复用既有签发参数与
    过期语义）并落平台面审计行（detail 含 from_tenant/to_tenant）。

    **token 经响应体返回是最小可行口径（B.14 未定义通道）**——前端持有后
    替换本地凭据、全站缓存清空重拉（13.8，T10 对接）；后续业务请求由
    tenant_scoped 按 act_tenant 优先解析（SUSPENDED 目标复用状态墙即时拦截）。
    """
    tenant, token = await tenantmgmt_service.switch_tenant_context(
        sess, principal, tenant_id
    )
    return TenantContextResponse(
        tenant_id=tenant.tenant_id,
        switched_at=datetime.now(UTC),
        note=tenantmgmt_service.CONTEXT_SWITCH_NOTE,
        access_token=token,
    )


@router.get(
    "/{tenant_id}/members",
    response_model=Page[TenantMemberItem],
    summary="租户成员清单（B.14：平台 ADMIN / 租户内 ADMIN 本租户）",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.NOT_FOUND,
    ),
)
async def list_tenant_members(
    tenant_id: UUID,
    principal: AnyPrincipal,
    sess: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = tenantmgmt_service.DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[TenantMemberItem]:
    """双轨判定（ensure_members_readable）：平台 ADMIN 全量；主体为该租户
    ADMIN 时放行（本租户）；本租户非 ADMIN → 403；他租户 → 404（不泄露
    存在性）。joined_at DESC 游标分页；投影含 display_name（join
    platform.users，service 内 bind_tenant 目标租户后查询）。"""
    ensure_members_readable(principal, tenant_id)
    return await tenantmgmt_service.list_members(
        sess, tenant_id, limit=limit, cursor=cursor
    )


@router.post(
    "/{tenant_id}/members",
    status_code=201,
    response_model=TenantMemberItem,
    summary="添加租户成员（B.14；平台 ADMIN）",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.NOT_FOUND,
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.CONFLICT,
    ),
)
async def add_tenant_member(
    tenant_id: UUID,
    payload: TenantMemberCreateRequest,
    sess: DbSession,
    principal: PlatformAdmin,
) -> TenantMemberItem:
    """{user_id, member_roles}：user_id 须为目标租户内 ACTIVE 用户（否则
    404）；已在册 → 409；member_roles 空数组 → 400 VALIDATION_ERROR；
    201 成员对象。"""
    return await tenantmgmt_service.add_member(
        sess, tenant_id, payload, actor_id=principal.id
    )


@router.patch(
    "/{tenant_id}/members/{member_id}",
    response_model=TenantMemberItem,
    summary="更新成员（改角色/禁用；B.14；平台 ADMIN）",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.NOT_FOUND,
        ErrorCode.VALIDATION_ERROR,
    ),
)
async def update_tenant_member(
    tenant_id: UUID,
    member_id: UUID,
    payload: TenantMemberUpdateRequest,
    sess: DbSession,
    principal: PlatformAdmin,
) -> TenantMemberItem:
    """{member_roles?, status?}；不可禁用（或降级）最后一个 ACTIVE ADMIN
    → 400 VALIDATION_ERROR；跨租户/不存在 member → 404。"""
    return await tenantmgmt_service.update_member(
        sess, tenant_id, member_id, payload, actor_id=principal.id
    )


@router.get(
    "/{tenant_id}/quotas",
    response_model=TenantQuotaDetail,
    summary="租户完整配额对象（B.14 七字段）",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED, ErrorCode.FORBIDDEN, ErrorCode.NOT_FOUND
    ),
)
async def get_tenant_quotas(
    tenant_id: UUID, sess: DbSession, principal: PlatformAdmin
) -> TenantQuotaDetail:
    """api_rate_limit / batch_max_events / query_timeout_ms / pool_share /
    storage_gb / events_per_month / updated_at（+tenant_id）；不存在 → 404。"""
    return await tenantmgmt_service.get_quota_detail(sess, tenant_id)


@router.patch(
    "/{tenant_id}/quotas",
    response_model=TenantQuotaDetail,
    summary="调整配额（B.14 临时提额；reason 必填留痕）",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.NOT_FOUND,
        ErrorCode.VALIDATION_ERROR,
    ),
)
async def update_tenant_quotas(
    tenant_id: UUID,
    payload: TenantQuotaUpdateRequest,
    sess: DbSession,
    principal: PlatformAdmin,
) -> TenantQuotaDetail:
    """{api_rate_limit?, storage_gb?, events_per_month?, reason}——仅三字段
    可调；reason 必填非空（缺失/空白 → 400 VALIDATION_ERROR）；审计留痕
    （切面 TENANT_QUOTAS_UPDATE diff + TENANT_QUOTAS_ADJUST 携 reason）
    → 200 更新后完整配额对象。"""
    return await tenantmgmt_service.update_quota(
        sess, tenant_id, payload, actor_id=principal.id, principal=principal
    )


@router.get(
    "/{tenant_id}/usage",
    response_model=Page[UsageItem],
    response_model_exclude_none=True,
    summary="租户使用量日报（平台运营；EDP-025 计量）",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.NOT_FOUND,
    ),
)
async def get_tenant_usage(
    tenant_id: UUID,
    sess: DbSession,
    principal: PlatformAdmin,
    since: Annotated[date | None, Query(description="起始日期（含）")] = None,
    until: Annotated[date | None, Query(description="结束日期（含）")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[UsageItem]:
    """使用量日报（B.14 最小版）：usage_date DESC 游标分页；租户不存在 404。"""
    if await tenantmgmt_service.get_tenant(sess, tenant_id) is None:
        raise EdpError.not_found("租户不存在")
    items, next_cursor = await tenantmgmt_service.query_usage(
        sess, tenant_id, since=since, until=until, limit=limit, cursor=cursor
    )
    return Page(items=items, next_cursor=next_cursor)


@admin_router.get(
    "/users",
    response_model=Page[AdminUserItem],
    summary="平台用户目录简投影（邀请成员下拉真数据源；W5-11 收口）",
    responses=error_responses(ErrorCode.UNAUTHENTICATED, ErrorCode.FORBIDDEN),
)
async def list_admin_users(
    sess: DbSession,
    principal: PlatformAdmin,
    limit: Annotated[int, Query(ge=1, le=100)] = tenantmgmt_service.DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[AdminUserItem]:
    """平台 ADMIN：username ASC keyset 游标简投影 {user_id, username,
    display_name}；目录范围口径见 service.list_users docstring（W6 最小
    口径 = 平台管理员主租户，B.14 未定义留痕）。"""
    return await tenantmgmt_service.list_users(
        sess, principal, limit=limit, cursor=cursor
    )
