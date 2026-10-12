"""value ORM 映射（V1.2 0016 迁移 value.value_ledger）。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Numeric, Text, Uuid, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ValueLedger(Base):
    """价值账本（V1.1 第十三节）：改善前后价值事实（按结果收费基础）。"""

    __tablename__ = "value_ledger"
    __table_args__ = {"schema": "value"}

    value_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    baseline_ref: Mapped[str | None] = mapped_column(Text)
    initiative_ref: Mapped[str | None] = mapped_column(Text)
    metric_ref: Mapped[str | None] = mapped_column(Text)
    before_value: Mapped[float | None] = mapped_column(Numeric(18, 4))
    after_value: Mapped[float | None] = mapped_column(Numeric(18, 4))
    delta: Mapped[float | None] = mapped_column(Numeric(18, 4))
    financial_value: Mapped[float | None] = mapped_column(Numeric(18, 4))
    evidence_refs: Mapped[list] = mapped_column(ARRAY(Uuid), nullable=False, default=list)
    verified_by: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)
