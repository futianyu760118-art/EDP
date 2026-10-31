"""registry ORM 映射：master.business_objects（表由迁移 0002 建立）。

只映射 W1 registry 需要的表；ORM 不参与迁移——DDL 单一事实来源是设计文档
附录 A 的迁移链，跨表外键约束以迁移 DDL 为准（ORM 列不声明 ForeignKey：
platform.tenants 等引用目标在别的模块 metadata 中，跨 metadata 声明会在
flush 排序时解析失败）。event.outbox 的映射与写入口归 events 模块
（T12 收敛）：registry 经 events.service.append_outbox /
outbox_for_aggregate 访问，不持有私有副本。
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class BusinessObject(Base):
    """业务对象注册元表（全局锚点；自然键 = tenant+source_system+object_type+
    source_id，uq_bo_natural_key；FORCE RLS；revision 为乐观锁版本号）。"""

    __tablename__ = "business_objects"
    __table_args__ = {"schema": "master"}

    object_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    object_type: Mapped[str] = mapped_column(Text, nullable=False)
    owner_domain: Mapped[str] = mapped_column(Text, nullable=False)
    source_system: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ACTIVE")
    merged_into: Mapped[UUID | None] = mapped_column(Uuid)
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)
