"""governance 请求/响应模型（V1.2 治理面；契约 governance/*.schema.json）。"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

RuleType = Literal[
    "FORMAT",
    "NORMALIZATION",
    "DEDUPLICATION",
    "MAPPING",
    "RANGE_CHECK",
    "REFERENTIAL_CHECK",
    "BUSINESS_RULE",
    "UNIT_CONVERSION",
    "CURRENCY_NORMALIZATION",
    "ENTITY_RESOLUTION",
]
Severity = Literal["BLOCK", "WARN", "INFO"]
ClassifySource = Literal["RULE_BASED", "HUMAN_MAINTAINED", "AI_ASSISTED"]
ReviewDecision = Literal[
    "APPROVED",
    "APPROVED_WITH_WARNING",
    "RETURN_FOR_CORRECTION",
    "REJECTED",
    "SUSPENDED",
    "ESCALATED",
]

OBJECT_TYPE_PATTERN = r"^[A-Z][A-Z0-9_]{0,63}$"


class CleaningRuleCreate(BaseModel):
    """清洗规则注册（契约 cleaning-rule.schema.json 子集；版本由服务层 +1）。"""

    rule_name: str = Field(min_length=1, max_length=128)
    object_type: str = Field(pattern=OBJECT_TYPE_PATTERN)
    field: str | None = Field(default=None, max_length=128)
    rule_type: RuleType
    condition: str | None = None
    transformation: dict[str, Any] = Field(default_factory=dict)
    severity: Severity = "WARN"
    owner: str = Field(min_length=1, max_length=64)
    effective_from: datetime | None = None
    auto_fix: bool = True
    review_required: bool = False

    @field_validator("object_type", mode="before")
    @classmethod
    def _normalize_object_type(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().upper()
        return value


class CleaningRuleItem(BaseModel):
    """规则列表/详情项。"""

    model_config = ConfigDict(from_attributes=True)

    rule_id: UUID
    rule_name: str
    object_type: str
    field: str | None
    rule_type: str
    condition: str | None
    transformation: dict[str, Any]
    severity: str
    owner: str
    version: int
    effective_from: datetime
    effective_to: datetime | None
    auto_fix: bool
    review_required: bool


class EntityAliasCreate(BaseModel):
    object_type: str = Field(pattern=OBJECT_TYPE_PATTERN)
    alias: str = Field(min_length=1, max_length=255)
    canonical_ref: UUID | None = None
    source: ClassifySource = "HUMAN_MAINTAINED"
    confidence: float | None = Field(default=None, ge=0, le=1)


class EntityAliasItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    alias_id: UUID
    object_type: str
    alias: str
    canonical_ref: UUID | None
    source: str
    confidence: float | None
    approved_by: str | None
    approved_at: datetime | None


class DimensionCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    name: str = Field(min_length=1, max_length=128)


class DimensionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dimension_id: UUID
    code: str
    name: str


class TaxonomyCreate(BaseModel):
    dimension_id: UUID
    parent_id: UUID | None = None
    label: str = Field(min_length=1, max_length=128)


class TaxonomyItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    taxonomy_id: UUID
    dimension_id: UUID
    parent_id: UUID | None
    label: str


class TagCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9-]{0,63}$")
    name: str = Field(min_length=1, max_length=128)


class TagItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tag_id: UUID
    code: str
    name: str


class ClassificationCreate(BaseModel):
    object_id: UUID
    dimension_id: UUID | None = None
    taxonomy_id: UUID | None = None
    label: str = Field(min_length=1, max_length=128)
    source: ClassifySource = "HUMAN_MAINTAINED"
    rule_ref: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class ClassificationItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    classification_id: UUID
    object_id: UUID
    dimension_id: UUID | None
    taxonomy_id: UUID | None
    label: str
    source: str
    rule_ref: str | None
    confidence: float | None
    version: int
    effective_from: datetime
    effective_to: datetime | None
    approved_by: str | None
    approved_at: datetime | None


class RawRecordItem(BaseModel):
    """RAW 只读项（不可改；列表不含 raw_payload 大字段）。"""

    model_config = ConfigDict(from_attributes=True)

    raw_record_id: UUID
    source_system: str
    source_record_id: str
    object_type: str
    source_timestamp: datetime
    batch_id: str | None
    checksum: str
    schema_version: str | None
    received_at: datetime


class TagAttachRequest(BaseModel):
    """对象标签挂接（T33 search_objects 前置）。"""

    object_id: UUID
    tag_id: UUID


class TagAttachItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    object_tag_id: UUID
    object_id: UUID
    tag_id: UUID
    created_at: datetime


class AdmissionListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    admission_id: UUID
    object_id: UUID
    state: str
    review_result: str | None
    quality_score: float | None
    version: int
    updated_at: datetime


class AdmissionDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    admission_id: UUID
    object_id: UUID
    state: str
    review_result: str | None
    quality_score: float | None
    machine_result: dict[str, Any] | None
    source_human_reviewer: str | None
    source_reviewed_at: datetime | None
    management_human_reviewer: str | None
    management_reviewed_at: datetime | None
    archived_at: datetime | None
    dimensions: dict[str, Any] | None
    classifications: dict[str, Any] | None
    tags: dict[str, Any] | None
    evidence_refs: list[UUID]
    checksum: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class ReviewRequest(BaseModel):
    """A2/A3 人工审核请求（decision 六结果 + 意见）。"""

    decision: ReviewDecision
    comment: str | None = Field(default=None, max_length=2000)
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=50)


class ReviewItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    review_id: UUID
    stage: str
    machine_result: dict[str, Any] | None
    human_decision: str
    human_reviewer: str
    comment: str | None
    reviewed_at: datetime
    evidence_refs: list[UUID]


class AdmissionReviewedResponse(BaseModel):
    admission_id: UUID
    state: str
    review_result: str | None
    quality_score: float | None
    updated_at: datetime
