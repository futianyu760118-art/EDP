"""evidence ORM 映射：evidence.records + evidence.links（表由迁移 0004 建立）。

沿袭既有约定：ORM 不参与迁移（DDL 单一事实来源 = 迁移链）；列不声明
ForeignKey（跨表外键以迁移 DDL 为准——object_id/event_id 引用目标在其他
模块 metadata 中，跨 metadata 声明会在 flush 排序时解析失败）。
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class EvidenceRecord(Base):
    """证据记录（source_record_id 指回源系统原始记录，追溯链终点；
    checksum = compute_checksum(snapshot)，篡改经 verify 探测；FORCE RLS）。"""

    __tablename__ = "records"
    __table_args__ = {"schema": "evidence"}

    evidence_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    source_system: Mapped[str] = mapped_column(Text, nullable=False)
    source_record_id: Mapped[str] = mapped_column(Text, nullable=False)
    object_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    event_id: Mapped[UUID | None] = mapped_column(Uuid)
    content_type: Mapped[str] = mapped_column(
        Text, nullable=False, default="application/json"
    )
    checksum: Mapped[str] = mapped_column(Text, nullable=False)
    checksum_algo: Mapped[str] = mapped_column(Text, nullable=False, default="SHA256")
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class EvidenceLink(Base):
    """证据链关联（通用逆向追溯：ref_type+ref_id → evidence；FORCE RLS）。"""

    __tablename__ = "links"
    __table_args__ = {"schema": "evidence"}

    link_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    evidence_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    ref_type: Mapped[str] = mapped_column(Text, nullable=False)
    ref_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)
