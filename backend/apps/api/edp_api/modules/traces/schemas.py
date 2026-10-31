"""traces 请求/响应模型（设计文档附录 B.10 逐字段，EDP-013）。

- POST /traces：B.10 请求体（trace_id 客户端提供、tool_calls[] 随行）→
  201 {trace_id, status, created_at}；同 trace_id 重发 → 200 幂等返回既有；
- GET /traces：轨迹摘要列表（简投影，不含 tool_calls/大 JSON 字段）+
  游标分页（agent_id/task_id/capability_id/since 过滤）；
- GET /traces/{trace_id}：完整轨迹含 tool_calls[]（seq 升序）。
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

TraceStatus = Literal["RUNNING", "SUCCEEDED", "FAILED", "TIMEOUT", "ABORTED"]


class ToolCallIn(BaseModel):
    """POST /traces 请求内的工具调用项（B.10；call_id 服务端生成、
    called_at 缺省 now 不在请求中）。"""

    seq: int = Field(ge=1)
    tool_name: str = Field(min_length=1, max_length=255)
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    status_code: int | None = Field(default=None, ge=100, le=599)
    error: dict[str, Any] | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    called_at: datetime | None = None


class TraceCreateRequest(BaseModel):
    """POST /traces 请求（B.10 逐字段；Agent Runtime 一次执行一条，
    工具调用随行写入）。"""

    trace_id: UUID
    agent_id: str = Field(min_length=1, max_length=255)
    task_id: str | None = Field(default=None, max_length=255)
    capability_id: UUID | None = None
    started_at: datetime
    finished_at: datetime | None = None
    status: TraceStatus
    input_context: dict[str, Any] | None = None
    output_structured: dict[str, Any] | None = None
    token_usage: dict[str, Any] | None = None
    evidence_refs: list[UUID] = Field(default_factory=list)
    tool_calls: list[ToolCallIn] = Field(default_factory=list)


class TraceCreatedResponse(BaseModel):
    """POST /traces 响应（201 新建 / 200 幂等重发，B.10 逐字段）。"""

    trace_id: UUID
    status: str
    created_at: datetime


class TraceListItem(BaseModel):
    """GET /traces 列表项（B.10 简投影——不含 tool_calls 与
    input_context/output_structured/token_usage 等大 JSON）。"""

    model_config = ConfigDict(from_attributes=True)

    trace_id: UUID
    agent_id: str
    task_id: str | None
    capability_id: UUID | None
    started_at: datetime
    finished_at: datetime | None
    status: str


class ToolCallItem(BaseModel):
    """GET /traces/{trace_id} 响应内的工具调用明细项（A.9 业务列全量）。"""

    model_config = ConfigDict(from_attributes=True)

    call_id: UUID
    seq: int
    tool_name: str
    input: dict[str, Any] | None
    output: dict[str, Any] | None
    status_code: int | None
    error: dict[str, Any] | None
    latency_ms: int | None
    called_at: datetime


class TraceDetail(BaseModel):
    """GET /traces/{trace_id} 响应：完整轨迹 + tool_calls[]（seq 升序）。"""

    model_config = ConfigDict(from_attributes=True)

    trace_id: UUID
    agent_id: str
    task_id: str | None
    capability_id: UUID | None
    started_at: datetime
    finished_at: datetime | None
    status: str
    input_context: dict[str, Any] | None
    output_structured: dict[str, Any] | None
    token_usage: dict[str, Any] | None
    evidence_refs: list[UUID]
    tool_calls: list[ToolCallItem] = Field(default_factory=list)
    created_at: datetime
