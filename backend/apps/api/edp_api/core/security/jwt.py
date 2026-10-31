"""JWT 签发与校验（HS256）：access（完整 claims）/ refresh（sub + tenant_id）双令牌。

claims 结构（附录 B.0）：sub / tenant_id / roles / principal_type / is_platform_admin
+ typ='access'|'refresh' + iat + exp；typ 字段的语义校验由调用方（require_access_claims）执行。
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt as pyjwt

from edp_api.core.config import get_settings
from edp_api.core.errors import EdpError


def _encode(claims: dict[str, Any]) -> str:
    settings = get_settings()
    return pyjwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_alg)


def create_access_token(
    user_id: UUID | str,
    tenant_id: UUID | str,
    roles: list[str] | tuple[str, ...],
    principal_type: str,
    is_platform_admin: bool,
    act_tenant: UUID | str | None = None,
) -> str:
    """签发 access token：exp = now + access_ttl，claims 含租户与角色全量上下文。

    act_tenant（B.14 租户上下文切换，可选）：平台 ADMIN 经
    POST /tenants/{id}/context 切换会话目标租户时写入——tenant_id 保持
    用户绑定租户（身份归属不变），act_tenant 为该会话的实际执行租户
    （tenant_scoped 解析优先级 act_tenant > tenant_id）。
    """
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "roles": list(roles),
        "principal_type": principal_type,
        "is_platform_admin": bool(is_platform_admin),
        "typ": "access",
        "iat": now,
        "exp": now + timedelta(seconds=get_settings().access_ttl_seconds),
    }
    if act_tenant is not None:
        claims["act_tenant"] = str(act_tenant)
    return _encode(claims)


def create_refresh_token(user_id: UUID | str, tenant_id: UUID | str) -> str:
    """签发 refresh token：sub + tenant_id + typ='refresh'，exp = refresh_ttl。

    tenant_id 用途（B.0 未禁止扩展 claims）：users / tenant_members 受
    FORCE RLS 约束，refresh 端点须先恢复 app.tenant_id 隔离键才能查到
    用户行——claims 携带租户使 edp_app 连接无需先查库即可 bind_tenant
    （T9 遗留死锁修复）。roles 不入 refresh claims：换发时按库重查。
    """
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "typ": "refresh",
        "iat": now,
        "exp": now + timedelta(seconds=get_settings().refresh_ttl_seconds),
    }
    return _encode(claims)


def decode_token(token: str) -> dict[str, Any]:
    """解码并校验签名/有效期；过期或非法 → EdpError.unauthenticated（401）。"""
    settings = get_settings()
    try:
        return pyjwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_alg])
    except pyjwt.ExpiredSignatureError:
        raise EdpError.unauthenticated("Token 已过期") from None
    except pyjwt.InvalidTokenError:
        raise EdpError.unauthenticated("Token 无效") from None


def require_access_claims(token: str) -> dict[str, Any]:
    """decode 后强制 typ='access'；refresh 等其他令牌 → 401 UNAUTHENTICATED。"""
    claims = decode_token(token)
    if claims.get("typ") != "access":
        raise EdpError.unauthenticated("需要 access token")
    return claims
