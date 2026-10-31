"""quality ORM 映射：ops.tasks（表由迁移 0013 建立）。

沿袭既有约定：ORM 不参与迁移（DDL 单一事实来源 = 迁移链）；列不声明
ForeignKey（跨表外键以迁移 DDL 为准）；列名与 DDL 逐字一致。

T3 仅落 ORM 供 T4/T5 复用（quality_recheck 任务轨道 / evidence_reindex /
adapter_sync 的 _jobs 写透）——报告端点不读写该表。task_type 三值与
status 三态取值域由 DDL CHECK 约束；stats/logs JSONB 默认 '{}'/'[]'；
FORCE RLS——会话需 bind_tenant。
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class OpsTask(Base):
    """运维任务行（ops.tasks；W5 起写者：quality rechecks（T4）/ evidence
    reindex（T6）/ adapter_sync（T5）——登记于 RUNNING、完成时回写终态）。"""

    __tablename__ = "tasks"
    __table_args__ = {"schema": "ops"}

    task_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    task_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="RUNNING")
    scope: Mapped[str | None] = mapped_column(Text)
    ref_name: Mapped[str | None] = mapped_column(Text)
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    logs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)
