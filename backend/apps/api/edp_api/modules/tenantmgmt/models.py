"""tenantmgmt ORM 映射：platform schema 租户域表（表由迁移 0001/0005 建立）。

W1 映射 tenants / tenant_members / tenant_quotas；W2（EDP-024）追加 users
行映射（UserRow）——租户开通需落初始管理员，沿袭 ingest 模块按需映射
platform.systems 的先例（platform.models.User 属另一 registry，互不干扰；
同 metadata 内 TenantMember 的 "platform.users" 外键由此可解析，flush 排序
tenants → users → tenant_members 成立）。ORM 不参与迁移——DDL 单一事实
来源是设计文档附录 A 的迁移链。
"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    """租户主表（平台根实体，控制面——不启用 RLS）。"""

    __tablename__ = "tenants"
    __table_args__ = {"schema": "platform"}

    tenant_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    plan: Mapped[str] = mapped_column(Text, nullable=False, default="STANDARD")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PROVISIONING")
    tenant_shard: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancel_scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class TenantMember(Base):
    """租户成员（用户↔租户绑定 + 租户内角色 member_roles；FORCE RLS）。"""

    __tablename__ = "tenant_members"
    __table_args__ = {"schema": "platform"}

    member_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("platform.tenants.tenant_id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("platform.users.user_id"), nullable=False
    )
    member_roles: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ACTIVE")
    invited_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class TenantQuota(Base):
    """租户配额（控制面，不启用 RLS）。"""

    __tablename__ = "tenant_quotas"
    __table_args__ = {"schema": "platform"}

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("platform.tenants.tenant_id"), primary_key=True
    )
    api_rate_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    batch_max_events: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    query_timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=5000)
    pool_share: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("2.0")
    )
    storage_gb: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    events_per_month: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1000000
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class TenantUsageDaily(Base):
    """租户日用量（platform.tenant_usage_daily；控制面计量表，无 RLS）。

    唯一键 (tenant_id, usage_date)（uq_usage_daily）；写入入口 = 本模块
    service.bump_usage_daily（events 批量入库与 ingest 管道经 service 调用，
    模块间仅 service）。列与迁移 0001 + 0010 一致。
    """

    __tablename__ = "tenant_usage_daily"
    __table_args__ = {"schema": "platform"}

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    api_calls: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    events_in: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    events_duplicated: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    storage_gb: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    throttled_429: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class UserRow(Base):
    """用户行（platform.users；FORCE RLS——开通流程在租户行落库并 bind_tenant
    新租户后写入，见 service.create_tenant）。仅映射开通路径所需列集，
    列定义与 platform.models.User / 迁移 0001 保持一致。"""

    __tablename__ = "users"
    __table_args__ = {"schema": "platform"}

    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    org_id: Mapped[UUID | None] = mapped_column(Uuid)
    principal_type: Mapped[str] = mapped_column(Text, nullable=False, default="HUMAN")
    is_platform_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)
