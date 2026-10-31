"""result 请求/响应模型（V1.2 T17；契约 contracts/result/result.schema.json）。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

RESULT_TYPE_PATTERN = r"^[A-Za-z][A-Za-z0-9._:-]{1,127}$"


class ResultCreateRequest(BaseModel):
    """POST /results：evidence_refs 必填非空（Result→Evidence 100% 硬约束）。"""

    result_type: str = Field(pattern=RESULT_TYPE_PATTERN)
    object_id: UUID
    domain: str = Field(min_length=1, max_length=64)
    period: str | None = Field(default=None, max_length=128)
    metric_refs: list[str] = Field(default_factory=list, max_length=50)
    value: dict[str, Any] = Field(default_factory=dict)
    status: str = Field(min_length=1, max_length=64)
    source_refs: list[str] = Field(default_factory=list, max_length=50)
    evidence_refs: list[UUID] = Field(min_length=1, max_length=50)
    generated_by: str = Field(min_length=1, max_length=128)


class ResultCreatedResponse(BaseModel):
    result_id: UUID
    status: str
    generated_at: datetime


class ResultListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    result_id: UUID
    result_type: str
    object_id: UUID
    domain: str
    period: str | None
    status: str
    verified_status: str | None
    generated_at: datetime


class ResultDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    result_id: UUID
    result_type: str
    object_id: UUID
    domain: str
    period: str | None
    metric_refs: list
    value: dict[str, Any]
    status: str
    source_refs: list
    evidence_refs: list[UUID]
    generated_by: str
    generated_at: datetime
    verified_status: str | None
    verified_by: str | None
    verified_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class VerifyResponse(BaseModel):
    result_id: UUID
    verified_status: str
    verified_by: str
    verified_at: datetime
