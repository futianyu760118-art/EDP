"""events ORM 映射：event.events + event.outbox（表由迁移 0001/0003 建立）。

ORM 不参与迁移（DDL 单一事实来源 = 设计文档附录 A 迁移链）；沿袭 registry
约定：ORM 列不声明 ForeignKey（跨表外键以迁移 DDL 为准——引用目标在其他
模块 metadata 中，跨 metadata 声明会在 flush 排序时解析失败）。

outbox 写入口收敛：本模块 service.append_outbox 是唯一写入口（registry 经
service 调用，不再持有私有映射副本）；worker 分发经 claim_pending_outbox /
record_outbox_result（同模块 service）。接口层幂等登记表
platform.idempotency_keys 归 platform 模块（models + service）。
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    Identity,
    Integer,
    Numeric,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Event(Base):
    """事件流水（event_id = UUIDv5 确定性生成，全局唯一；FORCE RLS）。"""

    __tablename__ = "events"
    __table_args__ = {"schema": "event"}

    event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    object_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    source_system: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_type: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[str | None] = mapped_column(Text)
    result_type: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str | None] = mapped_column(Text)
    score: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    ingest_latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class Outbox(Base):
    """事务性发件箱（FORCE RLS；写入口 = 本模块 service.append_outbox，
    状态流转归 T13 worker）。"""

    __tablename__ = "outbox"
    __table_args__ = {"schema": "event"}

    outbox_id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    aggregate_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)

