"""人员状态同步 API 模型。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PersonLifecycleEventIn(BaseModel):
    event_id: str = Field(min_length=1, max_length=200)
    event_type: Literal["person.offboarded", "person.reinstated"]
    event_version: Literal[1] = 1
    tenant_id: str = Field(min_length=1, max_length=128)
    source_system: str = Field(min_length=1, max_length=64)
    object_type: Literal["Person"]
    object_id: str = Field(min_length=1, max_length=200)
    revision: int = Field(ge=1)
    occurred_at: datetime
    effective_at: datetime
    correlation_id: str = Field(min_length=1, max_length=200)
    trace_id: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=500)
    person: dict[str, Any]
    status: Literal["active", "inactive"]
    employment_action: Literal["offboard", "rehire"]
    occurred_by: str = Field(min_length=1, max_length=200)


class PersonLifecycleDeliveryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    delivery_id: int
    event_id: str
    target_system: str
    status: str
    attempt_count: int
    last_error: str | None = None
    delivered_at: datetime | None = None
    next_attempt_at: datetime | None = None


class PersonLifecycleEventResponse(BaseModel):
    event_id: str
    status: str
    duplicate: bool = False
    revision: int
    event_type: str
    object_id: str
    effective_at: datetime
    deliveries: list[PersonLifecycleDeliveryResponse] = Field(default_factory=list)


class PersonLifecycleRetryResponse(BaseModel):
    event_id: str
    status: str
    retried_targets: list[str]
