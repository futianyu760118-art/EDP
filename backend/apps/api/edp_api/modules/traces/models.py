"""traces ORM 映射：trace.traces / trace.tool_calls（迁移 0004 建立）。

沿袭既有约定：ORM 不参与迁移（DDL 单一事实来源 = 迁移链）；列不声明
ForeignKey（跨表外键以迁移 DDL 为准）；列名与 DDL 逐字一致。

traces 带 A.9 标注的 "+ 审计字段"（created_at/updated_at/created_by/
updated_by）；tool_calls 未标注——仅业务列（call_id/seq/tool_name/input/
output/status_code/error/latency_ms/called_at）。llm_prompt/llm_response
（A.9 列）在 B.10 请求契约外，落 NULL 暂不映射写入路径。``evidence_refs``
为 UUID[]（postgresql.ARRAY(Uuid)）。
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Integer, Text, Uuid, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Trace(Base):
    """执行轨迹行（trace.traces；PK = trace_id 客户端提供，B.10 幂等键；
    status 五态由 DDL CHECK 约束；evidence_refs UUID[]；FORCE RLS——
    会话需 bind_tenant）。"""

    __tablename__ = "traces"
    __table_args__ = {"schema": "trace"}

    trace_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    agent_id: Mapped[str] = mapped_column(Text, nullable=False)
    task_id: Mapped[str | None] = mapped_column(Text)
    capability_id: Mapped[UUID | None] = mapped_column(Uuid)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="RUNNING")
    input_context: Mapped[dict | None] = mapped_column(JSONB)
    llm_prompt: Mapped[str | None] = mapped_column(Text)
    llm_response: Mapped[str | None] = mapped_column(Text)
    output_structured: Mapped[dict | None] = mapped_column(JSONB)
    token_usage: Mapped[dict | None] = mapped_column(JSONB)
    evidence_refs: Mapped[list[UUID]] = mapped_column(
        ARRAY(Uuid), nullable=False, default=list
    )
    error: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class ToolCall(Base):
    """工具调用明细行（trace.tool_calls；idx_tool_calls_trace 支撑按轨迹
    取明细 seq 升序；无审计列；FORCE RLS）。call_id 服务端生成 uuid4。"""

    __tablename__ = "tool_calls"
    __table_args__ = {"schema": "trace"}

    call_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    trace_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    input: Mapped[dict | None] = mapped_column(JSONB)
    output: Mapped[dict | None] = mapped_column(JSONB)
    status_code: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[dict | None] = mapped_column(JSONB)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    called_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
