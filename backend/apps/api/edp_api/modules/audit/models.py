"""audit ORM 映射：platform.audit_logs（表由迁移 0001 建立，分区由 0008/0009
维护）。

沿袭既有约定：ORM 不参与迁移（DDL 单一事实来源 = 迁移链）；列不声明
ForeignKey。分区表物理 PK 为 (audit_id, occurred_at)——ORM 按组合主键如实
映射（audit_id BIGSERIAL 由序列生成、occurred_at 走 server_default now()，
两者经 RETURNING 回填，flush 前均为未定值）。INSERT 经父表路由至当月分区
（0008 预建，应用启动滚动补建）；REVOKE UPDATE/DELETE 的仅追加语义与 ORM
无关（本模块只 INSERT/SELECT）。
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AuditLog(Base):
    """审计日志（控制面，不启用 RLS；按月分区，仅追加）。"""

    __tablename__ = "audit_logs"
    __table_args__ = {"schema": "platform"}

    audit_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=func.now()
    )
    tenant_id: Mapped[UUID | None] = mapped_column(Uuid)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(Text, nullable=False)
    request_id: Mapped[UUID | None] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
