"""auth 请求/响应模型（设计文档附录 B.1 逐字段）。"""

from uuid import UUID

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    tenant_slug: str | None = Field(default=None)


class TenantInfo(BaseModel):
    tenant_id: UUID
    slug: str
    name: str
    status: str


class UserInfo(BaseModel):
    user_id: UUID
    username: str
    roles: list[str]
    is_platform_admin: bool


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    tenant: TenantInfo
    user: UserInfo


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class ProfileUpdateRequest(BaseModel):
    """PUT /auth/profile（个人设置：仅传入字段更新）。"""

    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    email: str | None = Field(default=None, min_length=3, max_length=254)


class ChangePasswordRequest(BaseModel):
    """POST /auth/change-password（个人设置改密）。"""

    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class ChangePasswordResponse(BaseModel):
    message: str


class RefreshResponse(BaseModel):
    access_token: str
    expires_in: int


class MeResponse(BaseModel):
    user_id: UUID
    username: str
    display_name: str
    email: str
    org_id: UUID | None
    tenant_id: UUID
    is_platform_admin: bool
    roles: list[str]
    permissions: list[str]
