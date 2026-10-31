"""actions 请求/响应模型（设计文档附录 B.5 逐字段，EDP-020）。

- POST /actions：{case_id, title, action_type, owner?, owner_role?,
  due_date?, description?} → 201 {action_id, status:"PROPOSED", created_at}；
- GET /actions：列表简投影（B.5 items + allowed_to）+ 游标分页
  （status/owner/case_id 过滤）；
- GET /actions/{action_id}：完整行动对象 + allowed_to；
- PATCH /actions/{action_id}/status：{from_status, to_status, comment?} →
  200 {action_id, status, updated_at}；非法转移 422、from 过期 409、
  Human-Only 转移非 HUMAN 403（均见 service 层）。
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# 9 态（与迁移 0004 CHECK 约束一致；转移表见 service.TRANSITIONS）
ActionStatus = Literal[
    "PROPOSED",
    "ASSIGNED",
    "ACCEPTED",
    "APPROVED",
    "EXECUTING",
    "COMPLETED",
    "VERIFIED",
    "CANCELLED",
    "REJECTED",
]


class ActionCreateRequest(BaseModel):
    """POST /actions 请求（B.5）；case_id 提供但不存在 → 400。"""

    case_id: UUID | None = None
    title: str = Field(min_length=1, max_length=255)
    action_type: str = Field(min_length=1, max_length=128)
    owner: str | None = Field(default=None, max_length=128)
    owner_role: str | None = Field(default=None, max_length=128)
    due_date: datetime | None = None
    description: str | None = Field(default=None, max_length=4000)


class ActionCreatedResponse(BaseModel):
    """POST /actions 响应（201）。"""

    action_id: UUID
    status: str
    created_at: datetime


class TransitionItem(BaseModel):
    """当前状态允许的转移项：{to_status, human_only}（to_status 字典序稳定）。"""

    to_status: str
    human_only: bool


class ActionListItem(BaseModel):
    """GET /actions 列表项（B.5 简投影 + allowed_to）。"""

    action_id: UUID
    title: str
    status: str
    owner: str | None
    due_date: datetime | None
    allowed_to: list[TransitionItem]


class ActionDetailResponse(BaseModel):
    """GET /actions/{action_id} 响应：完整行动对象 + allowed_to。"""

    model_config = ConfigDict(from_attributes=True)

    action_id: UUID
    case_id: UUID | None
    title: str
    description: str | None
    action_type: str
    status: str
    owner: str | None
    owner_role: str | None
    due_date: datetime | None
    completion_time: datetime | None
    verified_at: datetime | None
    verified_by: str | None
    created_at: datetime
    updated_at: datetime
    allowed_to: list[TransitionItem] = Field(default_factory=list)


class ActionTransitionRequest(BaseModel):
    """PATCH /actions/{action_id}/status 请求（B.5；乐观锁 from_status）。"""

    from_status: ActionStatus
    to_status: ActionStatus
    comment: str | None = Field(default=None, max_length=2000)


class ActionTransitionResponse(BaseModel):
    """PATCH /actions/{action_id}/status 响应（200）。"""

    action_id: UUID
    status: str
    updated_at: datetime
