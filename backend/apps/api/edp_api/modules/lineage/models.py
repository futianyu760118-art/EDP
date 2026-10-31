"""lineage ORM 映射（V1.2 0015 迁移 governance.lineage；契约
contracts/governance/lineage.schema.json）。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Text, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Lineage(Base):
    """数据血缘：Source → Raw → Rule → Review → Official 全链要素。"""

    __tablename__ = "lineage"
    __table_args__ = {"schema": "governance"}

    lineage_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    source_record_id: Mapped[str] = mapped_column(Text, nullable=False)
    transformation_id: Mapped[UUID | None] = mapped_column(Uuid)
    cleaning_rule_version: Mapped[str | None] = mapped_column(Text)
    standardization_rule_version: Mapped[str | None] = mapped_column(Text)
    classification_version: Mapped[str | None] = mapped_column(Text)
    source_review_ref: Mapped[UUID | None] = mapped_column(Uuid)
    management_review_ref: Mapped[UUID | None] = mapped_column(Uuid)
    official_version: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    operator: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
