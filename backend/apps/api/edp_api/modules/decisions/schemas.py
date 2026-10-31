"""decisions 请求/响应模型（设计文档附录 B.5 逐字段，EDP-018 最小版 + W4
EDP-028 闭环聚合扩展）。

- POST /decisions/cases：question/context/options/risk_level/source_type/
  source_id/evidence_ids → 201 {case_id, case_no, status, created_at}；
- GET /decisions/cases：列表简投影 + 游标分页（status/risk_level 过滤）；
- GET /decisions/cases/{case_id}：详情含 evidence_refs（links join 投影）+
  decisions（决策记录列表）+ W4 闭环聚合可选字段（event/steps/actions/
  evidence_chain——`response_model_exclude_none` 下按需出现，向后兼容）；
- POST /decisions/cases/{case_id}/records：Human-Only → 201 {decision_id,
  case_id, decision_time, case_status}。
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

RiskLevel = Literal["P0", "P1", "P2", "P3"]
CaseStatus = Literal["OPEN", "DECIDED", "CANCELLED"]
DecisionType = Literal["HUMAN", "AI_SUGGESTED"]


class CaseOptionIn(BaseModel):
    """案例选项（B.5 options[{key,label}]）。"""

    key: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=255)


class CaseCreateRequest(BaseModel):
    """POST /decisions/cases 请求（B.5）。"""

    question: str = Field(min_length=1, max_length=2000)
    context: dict[str, Any] = Field(default_factory=dict)
    options: list[CaseOptionIn] = Field(default_factory=list, max_length=50)
    risk_level: RiskLevel | None = None
    source_type: str | None = Field(default=None, max_length=128)
    source_id: str | None = Field(default=None, max_length=255)
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=100)


class CaseCreatedResponse(BaseModel):
    """POST /decisions/cases 响应（201）。"""

    case_id: UUID
    case_no: str
    status: str
    created_at: datetime


class CaseListItem(BaseModel):
    """GET /decisions/cases 列表项（B.5 简投影）。"""

    model_config = ConfigDict(from_attributes=True)

    case_id: UUID
    case_no: str | None
    question: str
    risk_level: str | None
    status: str
    created_at: datetime


class EvidenceRefItem(BaseModel):
    """案例关联证据引用（B.5 evidence_refs[{evidence_id, checksum, source_system}]）。"""

    evidence_id: UUID
    checksum: str
    source_system: str


class DecisionItem(BaseModel):
    """决策记录项（B.5 decisions[]）。"""

    model_config = ConfigDict(from_attributes=True)

    decision_id: UUID
    chosen_option: str
    decision_type: str
    decided_by: str
    decision_time: datetime
    comment: str | None


class CaseEventSummary(BaseModel):
    """source 事件摘要（W4 EDP-028）：按 cases.source_id join event.events。

    summary 复用 ebms exceptions 的 coalesce 派生（data.summary →
    data.reason → event_type）；source_id 为空/非 UUID/事件不可见（RLS）
    时整个 event 字段缺省。
    """

    event_id: UUID
    event_type: str
    result_type: str | None = None
    risk_level: str | None = None
    summary: str
    occurred_at: datetime


StepType = Literal["EVENT", "CASE_CREATED", "DECISION", "ACTION"]


class CaseStepItem(BaseModel):
    """闭环步骤节点（W4 EDP-028，时间升序时间线）。

    EVENT=source 事件 / CASE_CREATED=案例创建 / DECISION=决策记录
    （human_only=True）/ ACTION=行动创建节点 + 当前状态快照节点（human_only
    按当前 status 是否存在 Human-Only 出边标注——APPROVED/COMPLETED 为 True；
    逐转移明细经审计页 ACTION_UPDATE 可查，最小版留痕）。
    """

    step_type: StepType
    occurred_at: datetime
    actor: str
    title: str
    detail: str | None = None
    human_only: bool | None = None


class ActionTransitionRef(BaseModel):
    """行动允许转移引用（形状对齐 actions.TransitionItem；模块间仅可依赖
    service，故本地重声明）。"""

    to_status: str
    human_only: bool


class CaseActionItem(BaseModel):
    """案例关联行动（W4 EDP-028）：status/owner/due_date/allowed_to。"""

    action_id: UUID
    title: str
    status: str
    owner: str | None = None
    due_date: datetime | None = None
    allowed_to: list[ActionTransitionRef] = Field(default_factory=list)


ChainLayer = Literal["RESULT", "DECISION", "EVIDENCE", "SOURCE"]


class EvidenceChainItem(BaseModel):
    """证据链节点（W4 EDP-028，设计 7.6 逆向追溯四层）。

    RESULT=回流结果证据（links ref RESULT，ref_id=source 事件）/
    DECISION=决策记录证据（ref DECISION，ref_id=case）/ EVIDENCE=ref_type=CASE
    证据集合 / SOURCE=各证据 (source_system, source_record_id) 投影去重
    （无 evidence_id/checksum）；verify 由前端按 evidence_id 调既有
    GET /evidence/{id}/verify。
    """

    layer: ChainLayer
    evidence_id: UUID | None = None
    checksum: str | None = None
    source_system: str | None = None
    source_record_id: str | None = None
    title: str


class CaseDetailResponse(BaseModel):
    """GET /decisions/cases/{case_id} 响应（B.5 + W4 EDP-028 闭环聚合）。

    既有字段（case_id~decisions）形状与路径不动；event/steps/actions/
    evidence_chain 为向后兼容新增（`response_model_exclude_none` 下可选）。
    """

    case_id: UUID
    question: str
    context: dict[str, Any]
    options: list[dict[str, Any]]
    risk_level: str | None
    status: str
    evidence_refs: list[EvidenceRefItem] = Field(default_factory=list)
    decisions: list[DecisionItem] = Field(default_factory=list)
    event: CaseEventSummary | None = None
    steps: list[CaseStepItem] = Field(default_factory=list)
    actions: list[CaseActionItem] = Field(default_factory=list)
    evidence_chain: list[EvidenceChainItem] = Field(default_factory=list)


class DecisionCreateRequest(BaseModel):
    """POST /decisions/cases/{case_id}/records 请求（B.5；Human-Only）。"""

    chosen_option: str = Field(min_length=1, max_length=128)
    decision_type: DecisionType = "HUMAN"
    comment: str | None = Field(default=None, max_length=2000)


class DecisionCreatedResponse(BaseModel):
    """POST /decisions/cases/{case_id}/records 响应（201）。"""

    decision_id: UUID
    case_id: UUID
    decision_time: datetime
    case_status: str
