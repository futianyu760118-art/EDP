"""value 请求/响应模型（V1.2 T25；契约 value-ledger.schema.json）。"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ValueLedgerCreate(BaseModel):
    baseline_ref: str | None = Field(default=None, max_length=255)
    initiative_ref: str | None = Field(default=None, max_length=255)
    metric_ref: str | None = Field(default=None, max_length=64)
    before_value: float | None = None
    after_value: float | None = None
    delta: float | None = None
    financial_value: float | None = None
    evidence_refs: list[UUID] = Field(default_factory=list, max_length=50)


class ValueLedgerItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    value_id: UUID
    baseline_ref: str | None
    initiative_ref: str | None
    metric_ref: str | None
    before_value: float | None
    after_value: float | None
    delta: float | None
    financial_value: float | None
    evidence_refs: list[UUID]
    verified_by: str | None
    verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ValueLedgerVerifyResponse(BaseModel):
    value_id: UUID
    verified_by: str
    verified_at: datetime
