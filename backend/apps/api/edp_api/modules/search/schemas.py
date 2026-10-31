"""search 响应模型（W6 T1）：三组命中的最小投影。

投影口径：id + 主显示字段 + 类型字段（object_type/event_type/source_system）
+ 时间戳；不携带 attrs/snapshot/data 大字段（与 evidence 列表简投影同一
口径，详情经各自模块端点承载）。
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ObjectHit(BaseModel):
    """对象命中（master.business_objects 简投影）。"""

    object_id: UUID
    source_id: str
    object_type: str
    updated_at: datetime


class EventHit(BaseModel):
    """事件命中（event.events 简投影）。"""

    event_id: UUID
    event_type: str
    occurred_at: datetime


class EvidenceHit(BaseModel):
    """证据命中（evidence.records 简投影；source_system 充当来源 kind）。"""

    evidence_id: UUID
    source_record_id: str
    source_system: str
    captured_at: datetime


class SearchResponse(BaseModel):
    """GET /api/v1/search 响应：三组命中 + total（三组返回行数合计）。"""

    query: str
    objects: list[ObjectHit] = Field(default_factory=list)
    events: list[EventHit] = Field(default_factory=list)
    evidence: list[EvidenceHit] = Field(default_factory=list)
    total: int
