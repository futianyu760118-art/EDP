"""metric 请求/响应模型（V1.2 T23；契约 metric.schema.json）。"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

CODE_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"


class MetricCreateRequest(BaseModel):
    """注册指标口径（新版本自动收旧 effective_to；definition_owner 为业务域）。"""

    code: str = Field(pattern=CODE_PATTERN)
    name: str = Field(min_length=1, max_length=128)
    business_definition: str | None = Field(default=None, max_length=2000)
    formula: str | None = Field(default=None, max_length=2000)
    source: str | None = Field(default=None, max_length=128)
    owner: str = Field(min_length=1, max_length=64)
    definition_owner: str | None = Field(default=None, max_length=64)
    definition_source: Literal["M01_KERNEL", "DOMAIN"] | None = "DOMAIN"
    target_owner: str | None = Field(default=None, max_length=64)
    snapshot_policy: str | None = Field(default=None, max_length=64)
    period_rule: str | None = Field(default=None, max_length=64)
    dimension: list[str] = Field(default_factory=list, max_length=50)
    unit: str | None = Field(default=None, max_length=32)


class MetricItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    metric_id: UUID
    code: str
    name: str
    business_definition: str | None
    formula: str | None
    owner: str
    definition_owner: str | None
    definition_source: str | None
    target_owner: str | None
    period_rule: str | None
    unit: str | None
    version: int
    effective_from: datetime
    effective_to: datetime | None


class MetricValueCreate(BaseModel):
    period: str = Field(min_length=1, max_length=64)
    value: float
    source: str | None = Field(default=None, max_length=128)


class MetricValueItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    value_id: UUID
    metric_id: UUID
    period: str
    value: float
    source: str | None
    computed_at: datetime
