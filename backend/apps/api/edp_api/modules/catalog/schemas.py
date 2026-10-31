"""catalog 请求/响应模型（设计文档附录 B.7 逐字段，EDP-011）。

- POST /systems：name/type/endpoint/auth_config → 201 {system_id, name,
  status, created_at}；GET /systems：列表简投影 + 游标分页（status 过滤）；
- POST /capabilities：name/domain/input_schema/output_schema/risk_level/
  permission/endpoint/owner → 201 {capability_id, name, status, created_at}
  （status 落 DDL 默认 ACTIVE，创建不接受）；
- PUT /capabilities/{id}：局部更新（仅传入字段覆盖：endpoint/input_schema/
  output_schema/status）→ 200 完整能力对象；
- POST /skills：capability_id/prompt/model_version/status → 201 {skill_id,
  capability_id, status, created_at}；GET /skills：列表（capability_id/
  status 过滤）。
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

SystemStatus = Literal["ACTIVE", "DISABLED"]
CapabilityStatus = Literal["DRAFT", "ACTIVE", "RETIRED"]
SkillStatus = Literal["DRAFT", "ACTIVE", "RETIRED"]
RiskLevel = Literal["L0", "L1", "L2", "L3"]
CapabilityPermission = Literal["HUMAN_ONLY", "READ_ONLY", "AUTO_ALLOWED"]


class SystemCreateRequest(BaseModel):
    """POST /systems 请求（B.7 + V1.3 T50 adapter_config 扩展）。"""

    name: str = Field(min_length=1, max_length=128)
    type: str = Field(min_length=1, max_length=64)
    endpoint: str | None = Field(default=None, max_length=512)
    auth_config: dict[str, Any] = Field(default_factory=dict)
    adapter_config: dict[str, Any] | None = Field(
        default=None,
        description="驱动配置（DB 拉取：dsn + tables 表规格列表）；提供即装配真实适配器",
    )


class SystemCreatedResponse(BaseModel):
    """POST /systems 响应（201，B.7 逐字段）。"""

    system_id: UUID
    name: str
    status: str
    created_at: datetime


class SystemListItem(BaseModel):
    """GET /systems 列表项（B.7 简投影 + T50 adapter_mode）。"""

    model_config = ConfigDict(from_attributes=True)

    system_id: UUID
    name: str
    type: str
    endpoint: str | None
    adapter_mode: str | None = None
    status: str
    created_at: datetime


class SystemResponse(BaseModel):
    """GET/PUT /systems/{id} 完整对象（含驱动配置，管理页编辑用）。"""

    model_config = ConfigDict(from_attributes=True)

    system_id: UUID
    name: str
    type: str
    endpoint: str | None
    auth_config: dict[str, Any]
    adapter_config: dict[str, Any] | None
    adapter_mode: str
    status: str
    created_at: datetime
    updated_at: datetime


class SystemUpdateRequest(BaseModel):
    """PUT /systems/{id} 局部更新（仅传入字段覆盖）。"""

    type: str | None = Field(default=None, min_length=1, max_length=64)
    endpoint: str | None = Field(default=None, max_length=512)
    auth_config: dict[str, Any] | None = None
    adapter_config: dict[str, Any] | None = None
    status: SystemStatus | None = None


class SystemTestResponse(BaseModel):
    """POST /systems/{id}/test 响应（探活结果）。"""

    ok: bool
    detail: str


class CapabilityCreateRequest(BaseModel):
    """POST /capabilities 请求（B.7；status 落 DDL 默认 ACTIVE 不接受）。"""

    name: str = Field(min_length=1, max_length=255)
    domain: str = Field(min_length=1, max_length=64)
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    risk_level: RiskLevel
    permission: CapabilityPermission
    endpoint: str | None = Field(default=None, max_length=512)
    owner: str | None = Field(default=None, max_length=128)


class CapabilityCreatedResponse(BaseModel):
    """POST /capabilities 响应（201，B.7 逐字段）。"""

    capability_id: UUID
    name: str
    status: str
    created_at: datetime


class CapabilityListItem(BaseModel):
    """GET /capabilities 列表项（B.7 简投影，不含 schema）。"""

    model_config = ConfigDict(from_attributes=True)

    capability_id: UUID
    name: str
    domain: str
    risk_level: str
    permission: str
    endpoint: str | None
    owner: str | None
    status: str
    created_at: datetime


class CapabilityResponse(BaseModel):
    """能力完整对象：GET /capabilities/{id} 详情 + PUT 更新后返回。"""

    model_config = ConfigDict(from_attributes=True)

    capability_id: UUID
    name: str
    domain: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    risk_level: str
    permission: str
    endpoint: str | None
    owner: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class CapabilityUpdateRequest(BaseModel):
    """PUT /capabilities/{id} 请求（B.7 局部更新语义——仅传入字段覆盖）。"""

    endpoint: str | None = Field(default=None, max_length=512)
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    status: CapabilityStatus | None = None


class SkillCreateRequest(BaseModel):
    """POST /skills 请求（B.7）。"""

    capability_id: UUID
    prompt: str = Field(min_length=1)
    model_version: str = Field(min_length=1, max_length=128)
    status: SkillStatus = "DRAFT"


class SkillCreatedResponse(BaseModel):
    """POST /skills 响应（201，B.7 逐字段）。"""

    skill_id: UUID
    capability_id: UUID
    status: str
    created_at: datetime


class SkillListItem(BaseModel):
    """GET /skills 列表项（B.7 简投影）。"""

    model_config = ConfigDict(from_attributes=True)

    skill_id: UUID
    capability_id: UUID
    model_version: str
    status: str
    created_at: datetime
