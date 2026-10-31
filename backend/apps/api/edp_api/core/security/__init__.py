"""安全套件：Argon2id 密码 / JWT / API Key / Principal / RBAC / 认证依赖。"""

from edp_api.core.security.apikey import hash_key
from edp_api.core.security.auth import (
    get_principal,
    parse_bearer,
    principal_from_api_key,
)
from edp_api.core.security.jwt import (
    create_access_token,
    create_refresh_token,
    decode_token,
    require_access_claims,
)
from edp_api.core.security.password import hash_password, verify_password
from edp_api.core.security.principal import Principal, PrincipalKind
from edp_api.core.security.rbac import (
    ALL_PERMISSIONS,
    ROLE_PERMISSIONS,
    has_permission,
    has_scope,
    permission_codes,
    require_permission,
    require_scope,
)

__all__ = [
    "ALL_PERMISSIONS",
    "ROLE_PERMISSIONS",
    "Principal",
    "PrincipalKind",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "get_principal",
    "hash_key",
    "hash_password",
    "has_permission",
    "has_scope",
    "parse_bearer",
    "permission_codes",
    "principal_from_api_key",
    "require_access_claims",
    "require_permission",
    "require_scope",
    "verify_password",
]
