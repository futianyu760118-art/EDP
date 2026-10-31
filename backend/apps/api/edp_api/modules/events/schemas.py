"""events 请求/响应模型（设计文档附录 B.3 逐字段）。"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

RiskLevel = Literal["P0", "P1", "P2", "P3"]
ActorType = Literal["HUMAN", "SERVICE", "AI"]

# 事件类型：小写点分命名空间（order.created / capability.result.order_risk）
EVENT_TYPE_PATTERN = r"^[A-Za-z][A-Za-z0-9._:-]{1,127}$"


class EventIn(BaseModel):
    """批量入库事件项（B.3）。

    event_id：客户端可自带 UUID，但服务端**忽略之**——event_id 恒由服务端
    derive_event_id(tenant_ns, source_system|source_id|occurred_at|event_type)
    派生（幂等唯一事实来源，防客户端伪造不一致；见 service.ingest_batch：
    B.3 批次事件不携带源记录 source_id，派生时以 object_id 充当该槽位）。
    """

    event_id: UUID | None = None
    event_type: str = Field(pattern=EVENT_TYPE_PATTERN)
    object_id: UUID
    source_system: str = Field(min_length=1, max_length=64)
    occurred_at: datetime
    actor_type: ActorType | None = None
    actor_id: str | None = Field(default=None, max_length=128)
    result_type: str | None = Field(default=None, max_length=128)
    risk_level: RiskLevel | None = None
    score: float | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_system", mode="before")
    @classmethod
    def _strip_source_system(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value


class BatchRequest(BaseModel):
    """POST /events/batch 请求：1~1000 条事件。"""

    events: list[EventIn] = Field(min_length=1, max_length=1000)


class EventBatchError(BaseModel):
    """逐事件拒绝原因（不整批失败）：index 为批次内下标。"""

    index: int
    code: str = "VALIDATION_ERROR"
    message: str


class BatchResponse(BaseModel):
    """POST /events/batch 响应（B.3）；errors 仅 rejected>0 时出现。"""

    accepted: int
    duplicated: int
    rejected: int
    deduplicated: bool = False
    errors: list[EventBatchError] | None = None


class EventResponse(BaseModel):
    """GET /events/{id} 与列表项（全字段）。"""

    model_config = ConfigDict(from_attributes=True)

    event_id: UUID
    tenant_id: UUID
    event_type: str
    object_id: UUID
    source_system: str
    occurred_at: datetime
    actor_type: str | None
    actor_id: str | None
    result_type: str | None
    risk_level: str | None
    score: float | None
    data: dict[str, Any]
    idempotency_key: str | None
    created_at: datetime
    # W3 契约扩展（spec §6.2）：列表填充；详情继承 ORM 实测耗时
    ingest_latency_ms: int | None = None
    delivery_status: str | None = None
    object_source_id: str | None = None
