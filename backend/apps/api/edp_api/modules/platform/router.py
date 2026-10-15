"""auth 路由（附录 B.1）：POST /login、POST /refresh、GET /me。

auth 为平台级路由：不挂租户绑定依赖（登录时租户尚未确定）；get_db 提供
请求级会话。薄层约定：业务逻辑（凭据校验/时序硬化/token 签发/claims
重建）归 platform.service（authenticate_and_login / refresh_tokens /
build_me_response），本层只做参数解析 + 调用 + 响应；bind_tenant 时序
（RLS 死锁修复，T9 遗留）随逻辑下沉 service。/me 仅支持 JWT
（API Key 服务主体无用户语义 → 401）。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import EdpError, ErrorCode, error_responses
from edp_api.core.security.auth import get_principal, parse_bearer
from edp_api.core.security.jwt import require_access_claims
from edp_api.core.security.principal import Principal
from edp_api.modules.platform import service as platform_service
from edp_api.modules.platform.schemas import (
    ChangePasswordRequest,
    ChangePasswordResponse,
    LoginRequest,
    MeResponse,
    ProfileUpdateRequest,
    RefreshRequest,
    RefreshResponse,
    TokenResponse,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


def _require_jwt_user(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> Principal:
    """JWT 用户守卫（me/profile/change-password 共用）：仅 Bearer access
    claims；API Key 服务主体无用户语义 → 401。"""
    token = parse_bearer(request.headers.get("authorization"))
    if token is None:
        raise EdpError.unauthenticated("此接口仅支持 JWT 认证")
    require_access_claims(token)
    if principal.user_id is None:
        raise EdpError.unauthenticated("access token 主体无效")
    return principal


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="用户登录，签发访问与刷新令牌",
    responses=error_responses(ErrorCode.UNAUTHENTICATED, ErrorCode.TENANT_SUSPENDED),
)
async def login(payload: LoginRequest, sess: DbSession) -> TokenResponse:
    """登录（凭据校验/时序硬化/签发归 service.authenticate_and_login）。"""
    return await platform_service.authenticate_and_login(sess, payload)


@router.post(
    "/refresh",
    response_model=RefreshResponse,
    summary="刷新访问令牌",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED, ErrorCode.TENANT_SUSPENDED
    ),
)
async def refresh(payload: RefreshRequest, sess: DbSession) -> RefreshResponse:
    """刷新（claims 校验与重建归 service.refresh_tokens）。"""
    return await platform_service.refresh_tokens(sess, payload.refresh_token)


@router.get(
    "/me",
    response_model=MeResponse,
    summary="获取当前用户信息与权限清单",
    responses=error_responses(ErrorCode.UNAUTHENTICATED),
)
async def me(
    sess: DbSession,
    principal: Annotated[Principal, Depends(_require_jwt_user)],
) -> MeResponse:
    """当前用户信息（含 display_name/email + 角色权限清单）。"""
    return await platform_service.build_me_response(sess, principal)


@router.put(
    "/profile",
    response_model=MeResponse,
    summary="更新个人资料（display_name / email）",
    responses=error_responses(ErrorCode.UNAUTHENTICATED, ErrorCode.VALIDATION_ERROR),
)
async def update_profile(
    payload: ProfileUpdateRequest,
    sess: DbSession,
    principal: Annotated[Principal, Depends(_require_jwt_user)],
) -> MeResponse:
    """局部更新 + 审计 AUTH_PROFILE_UPDATE；返回更新后的 /me。"""
    return await platform_service.update_profile(sess, principal, payload)


@router.post(
    "/change-password",
    response_model=ChangePasswordResponse,
    summary="修改当前用户密码",
    responses=error_responses(ErrorCode.UNAUTHENTICATED, ErrorCode.VALIDATION_ERROR),
)
async def change_password(
    payload: ChangePasswordRequest,
    sess: DbSession,
    principal: Annotated[Principal, Depends(_require_jwt_user)],
) -> ChangePasswordResponse:
    """旧密校验（400，会话内输入校验语义）→ 强度校验（400）→ Argon2id
    重哈希 + 审计。"""
    await platform_service.change_password(sess, principal, payload)
    return ChangePasswordResponse(message="密码已更新")
