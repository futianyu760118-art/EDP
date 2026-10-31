"""evidence 请求/响应模型（设计文档附录 B.4 逐字段）。

列表用简投影 EvidenceListItem（无 snapshot/links——大字段不进列表，详情经
GET /evidence/{id} 承载）；字段集为前端 MSW EvidenceRecord 的真子集
（T18 契约冻结时以此回归）。
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# B.4 links.ref_type 枚举（与迁移 0004 CHECK 约束一致）
RefType = Literal["CASE", "DECISION", "ACTION", "RESULT", "EVENT", "TRACE"]


class EvidenceLinkIn(BaseModel):
    """POST /evidence links 项（ref_type 六值枚举 + ref_id）。"""

    ref_type: RefType
    ref_id: UUID


class EvidenceCreateRequest(BaseModel):
    """POST /evidence 请求：snapshot 为源记录快照（checksum 服务端计算）。"""

    source_system: str = Field(min_length=1, max_length=64)
    source_record_id: str = Field(min_length=1, max_length=255)
    object_id: UUID
    event_id: UUID | None = None
    snapshot: dict[str, Any]
    captured_at: datetime
    links: list[EvidenceLinkIn] = Field(default_factory=list, max_length=50)

    @field_validator("source_system")
    @classmethod
    def _strip_source_system(cls, value: str) -> str:
        return value.strip()


class EvidenceCreatedResponse(BaseModel):
    """POST /evidence 响应（201）：evidence_id + 服务端计算的 checksum。"""

    evidence_id: UUID
    checksum: str
    captured_at: datetime


class EvidenceLinkItem(BaseModel):
    """证据链关联项（GET /evidence/{id}.links）。"""

    model_config = ConfigDict(from_attributes=True)

    ref_type: str
    ref_id: UUID


class EvidenceResponse(BaseModel):
    """GET /evidence/{id} 响应（全字段含 snapshot + links）。"""

    model_config = ConfigDict(from_attributes=True)

    evidence_id: UUID
    tenant_id: UUID
    source_system: str
    source_record_id: str
    object_id: UUID
    event_id: UUID | None
    content_type: str
    checksum: str
    checksum_algo: str
    snapshot: dict[str, Any]
    captured_at: datetime
    created_at: datetime
    updated_at: datetime
    links: list[EvidenceLinkItem] = Field(default_factory=list)


class EvidenceListItem(BaseModel):
    """GET /evidence 列表项（简投影：无 snapshot/links 大字段）。"""

    model_config = ConfigDict(from_attributes=True)

    evidence_id: UUID
    source_system: str
    source_record_id: str
    object_id: UUID
    checksum: str
    captured_at: datetime


class VerifyResponse(BaseModel):
    """GET /evidence/{id}/verify 响应：重算比对结果（失败同事务落告警审计）。"""

    evidence_id: UUID
    valid: bool
    verified_at: datetime


class ReindexRequest(BaseModel):
    """POST /admin/evidence/reindex 请求体（scope 缺省 ALL，当前仅全量）。"""

    scope: Literal["ALL"] = "ALL"


class ReindexAccepted(BaseModel):
    """202 响应：重索引任务已登记（后台异步执行，经 GET /admin/quality/
    tasks/{task_id} 轮询——quality:read，不新开任务查询端点）。"""

    task_id: UUID
    status: str
