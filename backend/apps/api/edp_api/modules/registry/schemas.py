"""registry 请求/响应模型（设计文档附录 B.2 逐字段）。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 源系统记录标识：字母数字开头，允许 . _ : @ # / -（覆盖 "SO-2026-00123" 等）
SOURCE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:@#/-]{0,127}$"
# 对象类型：大写枚举放开为 str，before 校验器归一为大写后按本模式约束
OBJECT_TYPE_PATTERN = r"^[A-Z][A-Z0-9_]{0,63}$"


class IdempotencySpec(BaseModel):
    """幂等/乐观锁说明：expected_revision 携带调用方所见的基准版本。"""

    expected_revision: int | None = Field(default=None, ge=1)


class ObjectUpsertRequest(BaseModel):
    object_type: str = Field(pattern=OBJECT_TYPE_PATTERN)
    owner_domain: str = Field(min_length=1, max_length=64)
    source_system: str = Field(min_length=1, max_length=64)
    source_id: str = Field(min_length=1, pattern=SOURCE_ID_PATTERN)
    idempotency: IdempotencySpec = Field(default_factory=IdempotencySpec)
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("object_type", mode="before")
    @classmethod
    def _normalize_object_type(cls, value: Any) -> Any:
        """大写枚举放开为 str：输入归一为大写（"order" → "ORDER"）。"""
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("owner_domain", "source_system")
    @classmethod
    def _strip_domain_fields(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value


class ObjectCreatedResponse(BaseModel):
    """POST /objects 响应（201 创建 / 200 更新复用；B.2）。"""

    object_id: UUID
    revision: int
    status: str
    created_at: datetime


class ObjectResponse(BaseModel):
    """GET /objects/{id} 与列表项（全字段）。"""

    model_config = ConfigDict(from_attributes=True)

    object_id: UUID
    tenant_id: UUID
    object_type: str
    owner_domain: str
    source_system: str
    source_id: str
    revision: int
    status: str
    merged_into: UUID | None
    attributes: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class HistoryEntry(BaseModel):
    revision: int
    action: str
    actor_id: str | None
    occurred_at: datetime


class HistoryResponse(BaseModel):
    object_id: UUID
    revisions: list[HistoryEntry]
