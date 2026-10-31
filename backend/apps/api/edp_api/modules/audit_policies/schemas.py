"""audit_policies 请求/响应模型（EDP-032 最小版）。

- POST /admin/audit-policies：{name, description?, resource_types?,
  actions?, actor_types?, notify_channel?} → 201 完整对象（三维数组
  缺省 [] = 通配）；
- GET /admin/audit-policies?status=：游标分页（created_at DESC）；
- PATCH /{policy_id}：局部更新（name 不可改——重命名走新建策略）；
- DELETE /{policy_id} → 204。
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from edp_api.core.pagination import Page

PolicyStatus = Literal["ACTIVE", "DISABLED"]
ActorType = Literal["HUMAN", "AI", "SERVICE"]


class PolicyCreateRequest(BaseModel):
    """POST /admin/audit-policies 请求；三维匹配数组缺省 []（=通配）。"""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    resource_types: list[str] = Field(default_factory=list, max_length=100)
    actions: list[str] = Field(default_factory=list, max_length=100)
    actor_types: list[ActorType] = Field(default_factory=list, max_length=3)
    notify_channel: str | None = Field(default=None, max_length=255)


class PolicyUpdateRequest(BaseModel):
    """PATCH /{policy_id} 请求（局部更新；name 不可改）。"""

    description: str | None = Field(default=None, max_length=2000)
    resource_types: list[str] | None = Field(default=None, max_length=100)
    actions: list[str] | None = Field(default=None, max_length=100)
    actor_types: list[ActorType] | None = Field(default=None, max_length=3)
    notify_channel: str | None = Field(default=None, max_length=255)
    status: PolicyStatus | None = None


class PolicyItem(BaseModel):
    """策略完整对象（创建 201 / PATCH 200 / 列表项同形）。"""

    model_config = ConfigDict(from_attributes=True)

    policy_id: UUID
    name: str
    description: str | None
    resource_types: list[str]
    actions: list[str]
    actor_types: list[str]
    notify_channel: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None


PolicyPage = Page[PolicyItem]
