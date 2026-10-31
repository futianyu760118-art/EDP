"""memories ORM 映射：memory.memories（迁移 0004 建立）。

沿袭既有约定：ORM 不参与迁移（DDL 单一事实来源 = 迁移链）；列不声明
ForeignKey（跨表外键以迁移 DDL 为准）；列名与 DDL 逐字一致。
status CANDIDATE/APPROVED/REJECTED 由 DDL CHECK 约束；FORCE RLS——
会话需 bind_tenant。
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Memory(Base):
    """记忆候选行（memory.memories；idx_memories_status/capability 支撑
    过滤；评审流转 W6 由中枢界面触发，本模块提供 Human-Only 评审 API）。"""

    __tablename__ = "memories"
    __table_args__ = {"schema": "memory"}

    memory_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    capability_id: Mapped[UUID | None] = mapped_column(Uuid)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="CANDIDATE")
    reviewed_by: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)
