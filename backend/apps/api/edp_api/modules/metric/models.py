"""metric ORM 映射（V1.2 0016 迁移；DDL 单一事实来源 = 迁移链）。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Integer, Numeric, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Metric(Base):
    """指标口径注册（V1.1 第十一节 + V1.2 第五节边界字段；版本化生效区间）。"""

    __tablename__ = "metrics"
    __table_args__ = {"schema": "metric"}

    metric_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    business_definition: Mapped[str | None] = mapped_column(Text)
    formula: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str] = mapped_column(Text, nullable=False)
    definition_owner: Mapped[str | None] = mapped_column(Text)
    definition_source: Mapped[str | None] = mapped_column(Text)
    target_owner: Mapped[str | None] = mapped_column(Text)
    snapshot_policy: Mapped[str | None] = mapped_column(Text)
    period_rule: Mapped[str | None] = mapped_column(Text)
    dimension: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    unit: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class MetricValue(Base):
    """指标计量值（(tenant, metric, period) 唯一）。"""

    __tablename__ = "metric_values"
    __table_args__ = {"schema": "metric"}

    value_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    metric_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    period: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    source: Mapped[str | None] = mapped_column(Text)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)
