"""ORM mapping for the internal LeadIntakeV1 intake ledger."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Identity, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class LeadIntake(Base):
    __tablename__ = "lead_intakes"
    __table_args__ = {"schema": "event"}

    lead_intake_id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    intake_id: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)
