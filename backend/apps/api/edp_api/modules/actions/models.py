"""actions ORM 映射：action.actions（表由迁移 0004 建立，A.6 全列）。

沿袭既有约定：ORM 不参与迁移（DDL 单一事实来源 = 迁移链）；列不声明
ForeignKey（跨表外键以迁移 DDL 为准）；列名与 DDL 逐字一致。
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Text, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Action(Base):
    """行动任务（状态机 9 态见 service.TRANSITIONS；FORCE RLS）。

    status 由 DDL CHECK 约束 9 态；completion_time 于 to=COMPLETED 回填、
    verified_at/verified_by 于 to=VERIFIED 回填（转移语义见 service 层）。
    """

    __tablename__ = "actions"
    __table_args__ = {"schema": "action"}

    action_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    case_id: Mapped[UUID | None] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    action_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PROPOSED")
    owner: Mapped[str | None] = mapped_column(Text)
    owner_role: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completion_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)
