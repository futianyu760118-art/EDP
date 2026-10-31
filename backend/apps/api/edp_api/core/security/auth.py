"""认证依赖：Authorization Bearer（JWT）或 X-API-Key → Principal。

DB 会话遵循 T7 协议：get_principal 从 request.state.db 取 get_db 提供的
请求级会话（不自行开连接）。API Key 查询走 platform.lookup_api_key
（迁移 0006 的 SECURITY DEFINER 安全例外）：认证发生在租户绑定之前，
直接查 api_keys 会被 FORCE RLS 过滤为空（T8 Concern #1）。

本层只做凭据有效性判定（401 语义）；租户状态守卫（SUSPENDED → 403
TENANT_SUSPENDED 等，3.3 传播链 ②）由业务路由依赖 tenant_scoped
（modules/tenantmgmt/dependencies.py）执行。
"""

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.errors import EdpError
from edp_api.core.security.apikey import hash_key
from edp_api.core.security.jwt import require_access_claims
from edp_api.core.security.principal import Principal

# SECURITY DEFINER（0006）：以属主身份绕过 api_keys 的 FORCE RLS——认证先于
# 租户绑定的唯一例外路径；函数内置 Key 自身 status='ACTIVE' 与未过期过滤
_API_KEY_SQL = text("SELECT * FROM platform.lookup_api_key(CAST(:kh AS TEXT))")


def parse_bearer(header: str | None) -> str:
    """解析 Authorization 头；返回 Bearer token，缺失/非 Bearer/格式非法 → None。"""
    if not header:
        return None
    parts = header.strip().split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


async def principal_from_api_key(sess: AsyncSession, key_hash: str) -> Principal:
    """经 platform.lookup_api_key 查询：Key 不存在/已吊销/已过期（SQL 过滤后
    函数返回空）→ 401 UNAUTHENTICATED；通过 → Principal。

    不校验所属租户状态（T10 起语义归位）：非 ACTIVE 租户的业务请求由
    tenant_scoped 统一拦截（403 TENANT_SUSPENDED / TENANT_FORBIDDEN），
    认证层不把租户状态与凭据有效性混同。
    """
    row = (await sess.execute(_API_KEY_SQL, {"kh": key_hash})).mappings().first()
    if row is None:
        raise EdpError.unauthenticated("API Key 无效")
    return Principal.from_api_key(row)


async def get_principal(request: Request) -> Principal:
    """FastAPI 认证依赖：Bearer（优先）或 X-API-Key；均无有效凭据 → 401。"""
    token = parse_bearer(request.headers.get("authorization"))
    if token is not None:
        return Principal.from_jwt_claims(require_access_claims(token))
    api_key = request.headers.get("x-api-key")
    if api_key:
        sess: AsyncSession | None = getattr(request.state, "db", None)
        if sess is None:
            raise EdpError.internal("认证依赖缺少请求级数据库会话（需先挂 get_db）")
        return await principal_from_api_key(sess, hash_key(api_key))
    raise EdpError.unauthenticated("缺少认证凭据（Authorization: Bearer 或 X-API-Key）")
