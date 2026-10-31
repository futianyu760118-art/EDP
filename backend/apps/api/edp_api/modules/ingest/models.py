"""ingest ORM 映射：platform.systems（表由迁移 0001 建立、0008 补水位列）。

只映射管道需要的 systems（源系统登记 + 同步水位）；ORM 不参与迁移——DDL
单一事实来源是迁移链。跨表外键约束以迁移 DDL 为准（ORM 列不声明
ForeignKey，沿袭各模块约定：platform.tenants 引用目标在别的 metadata 中）。
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class System(Base):
    """源系统登记（platform.systems；FORCE RLS——调用方会话需 bind_tenant，
    显式 tenant_id 条件为无 RLS 环境双保险）。last_watermark 由 run_sync
    收尾写回（0008 迁移新增列）。"""

    __tablename__ = "systems"
    __table_args__ = {"schema": "platform"}

    system_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint: Mapped[str | None] = mapped_column(Text)
    adapter_mode: Mapped[str] = mapped_column(Text, nullable=False, default="mock")
    auth_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ACTIVE")
    last_watermark: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)
