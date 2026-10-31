"""Principal：认证后的统一身份主体值对象（HUMAN / SERVICE / AI）。

- JWT 用户：from_jwt_claims（sub → id，roles / is_platform_admin 来自 claims；
  act_tenant 为 B.14 上下文切换的可选执行租户 claim）；
- API Key 服务主体：from_api_key（id = principal_id，权限语义走 scopes 而非 roles）。
"""

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

PrincipalKind = Literal["HUMAN", "SERVICE", "AI"]


def _row_get(row: Any, name: str) -> Any:
    if isinstance(row, dict):
        return row[name]
    return getattr(row, name)


@dataclass(frozen=True)
class Principal:
    id: str
    kind: PrincipalKind
    tenant_id: UUID
    roles: list[str] = field(default_factory=list)
    scopes: list[str] = field(default_factory=list)
    is_platform_admin: bool = False
    display_name: str = ""
    user_id: UUID | None = None
    act_tenant: UUID | None = None

    @property
    def effective_tenant_id(self) -> UUID:
        """请求执行租户：act_tenant（B.14 上下文切换 claim）优先于绑定租户。"""
        return self.act_tenant or self.tenant_id

    @classmethod
    def from_jwt_claims(cls, claims: dict[str, Any]) -> "Principal":
        """由 access token claims 构造（sub 解析为 UUID 失败时 user_id 置 None；
        act_tenant 非法/缺失置 None——按绑定租户执行）。"""
        sub = str(claims["sub"])
        try:
            user_id: UUID | None = UUID(sub)
        except ValueError:
            user_id = None
        act_raw = claims.get("act_tenant")
        try:
            act_tenant: UUID | None = UUID(str(act_raw)) if act_raw else None
        except ValueError:
            act_tenant = None
        return cls(
            id=sub,
            kind=claims.get("principal_type", "HUMAN"),
            tenant_id=UUID(str(claims["tenant_id"])),
            roles=list(claims.get("roles") or []),
            scopes=[],
            is_platform_admin=bool(claims.get("is_platform_admin", False)),
            user_id=user_id,
            act_tenant=act_tenant,
        )

    @classmethod
    def from_api_key(cls, row: Any) -> "Principal":
        """由 api_keys 行（dict 或 dataclass）构造；row 需含
        key_id / tenant_id / principal_type / principal_id / scopes。"""
        return cls(
            id=str(_row_get(row, "principal_id")),
            kind=_row_get(row, "principal_type"),
            tenant_id=UUID(str(_row_get(row, "tenant_id"))),
            roles=[],
            scopes=list(_row_get(row, "scopes") or []),
            is_platform_admin=False,
        )
