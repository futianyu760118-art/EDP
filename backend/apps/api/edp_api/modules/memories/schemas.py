"""memories 请求/响应模型（设计文档附录 B.11 逐字段，EDP-014）。

- POST /memories：capability_id/source_type/source_id/content → 201
  {memory_id, status: CANDIDATE, created_at}；
- GET /memories：status/capability_id 过滤 + 游标分页（列表项含评审字段，
  供 W6 中枢评审界面使用）；
- PATCH /memories/{id}/review：{status: APPROVED|REJECTED, comment?} →
  200 {memory_id, status, reviewed_by, reviewed_at}。
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

MemoryStatus = Literal["CANDIDATE", "APPROVED", "REJECTED"]
ReviewStatus = Literal["APPROVED", "REJECTED"]


class MemoryCreateRequest(BaseModel):
    """POST /memories 请求（B.11）。"""

    capability_id: UUID | None = None
    source_type: str = Field(min_length=1, max_length=64)
    source_id: UUID
    content: dict[str, Any]


class MemoryCreatedResponse(BaseModel):
    """POST /memories 响应（201，B.11 逐字段）。"""

    memory_id: UUID
    status: str
    created_at: datetime


class MemoryListItem(BaseModel):
    """GET /memories 列表项（B.11 简投影 + 评审字段）。"""

    model_config = ConfigDict(from_attributes=True)

    memory_id: UUID
    capability_id: UUID | None
    source_type: str
    source_id: UUID
    content: dict[str, Any]
    status: str
    reviewed_by: str | None
    reviewed_at: datetime | None
    created_at: datetime


class MemoryReviewRequest(BaseModel):
    """PATCH /memories/{id}/review 请求（Human-Only）。"""

    status: ReviewStatus
    comment: str | None = Field(default=None, max_length=2000)


class MemoryReviewResponse(BaseModel):
    """PATCH /memories/{id}/review 响应（200，B.11 逐字段）。"""

    memory_id: UUID
    status: str
    reviewed_by: str
    reviewed_at: datetime
