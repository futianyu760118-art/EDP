"""lineage 请求/响应模型（V1.2 T20；契约 contracts/governance/lineage.schema.json）。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class LineageItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    lineage_id: UUID
    source_record_id: str
    transformation_id: UUID | None
    cleaning_rule_version: str | None
    standardization_rule_version: str | None
    classification_version: str | None
    source_review_ref: UUID | None
    management_review_ref: UUID | None
    official_version: str
    timestamp: datetime
    operator: str


class LineageDetail(LineageItem):
    object: dict[str, Any] | None = None
