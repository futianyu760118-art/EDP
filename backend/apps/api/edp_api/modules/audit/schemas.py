"""audit 请求/响应模型（B.6 查询面；字段名与前端 AuditLogItem 契约对齐——
audit_id 为 BIGSERIAL 整数、occurred_at ISO 时间串）。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditLogItem(BaseModel):
    """GET /audit-logs 列表项（B.6）。"""

    model_config = ConfigDict(from_attributes=True)

    audit_id: int
    occurred_at: datetime
    actor_type: str
    actor_id: str
    action: str
    resource_type: str
    resource_id: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class AuditLogFilters(BaseModel):
    """GET /audit-logs 过滤参数汇总（路由以 Query 参数承载，此处固化契约）。"""

    actor_id: str | None = None
    resource_type: str | None = None
    action: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = None
