"""platform 模块 ORM 映射：身份与授权域表（表由迁移 0001/0005 建立）。

只映射 W1 需要的表（users / roles / permissions / api_keys /
idempotency_keys）；ORM 不参与迁移。users / api_keys / idempotency_keys
受 FORCE RLS 约束；roles / permissions 为全局模板（无 RLS）。
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Text, Uuid, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    """用户（全局身份；租户归属经 tenant_members；FORCE RLS）。"""

    __tablename__ = "users"
    __table_args__ = {"schema": "platform"}

    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    # 不声明 ForeignKey（沿袭约定：DDL 单一事实来源 = 迁移；本模块
    # metadata 无 tenants/organizations 表——声明会在 flush 触发全局
    # mapper 配置时 NoReferencedTableError）
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    # 不声明 ForeignKey（沿袭约定：DDL 单一事实来源 = 迁移；声明会要求
    # organizations 表入本模块 metadata，懒配置时 NoReferencedTableError）
    org_id: Mapped[UUID | None] = mapped_column(Uuid)
    principal_type: Mapped[str] = mapped_column(
        Text, nullable=False, default="HUMAN"
    )
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class Role(Base):
    """角色（全局模板，不启用 RLS）。"""

    __tablename__ = "roles"
    __table_args__ = {"schema": "platform"}

    role_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class Permission(Base):
    """权限（全局模板，不启用 RLS；无审计字段——与 A.1 DDL 一致）。"""

    __tablename__ = "permissions"
    __table_args__ = {"schema": "platform"}

    permission_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    resource: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)


class ApiKey(Base):
    """API 密钥（服务主体；FORCE RLS——认证路径走 lookup_api_key 例外）。"""

    __tablename__ = "api_keys"
    __table_args__ = {"schema": "platform"}

    key_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # 不声明 ForeignKey（同 users.tenant_id 约定）
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    principal_type: Mapped[str] = mapped_column(
        Text, nullable=False, default="SERVICE"
    )
    principal_id: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class IdempotencyKey(Base):
    """接口层幂等登记（W1 登记项；FORCE RLS；复合 PK (tenant_id, key)——
    幂等键按租户命名空间隔离，0007 起生效；读写入口 =
    本模块 service.load/store_idempotent_response，events 经 service 调用）。"""

    __tablename__ = "idempotency_keys"
    __table_args__ = {"schema": "platform"}

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    response_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
