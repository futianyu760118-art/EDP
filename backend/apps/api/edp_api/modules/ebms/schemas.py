"""ebms 响应模型（设计文档附录 B.9 逐字段；exceptions + W4 四端点）。

字段事实来源 = B.9 各端点示例：exceptions（event_id/result_type/risk_level/
object_id/order_no/summary/occurred_at/case_id）、reports/summary、decisions/
pending、todos、objectives。

可空性口径：
- ``risk_level`` 由查询条件 ``IS NOT NULL`` 保证（B.9 示例为有值）；
- ``result_type`` 保留事件列的可空性——B.9 示例为有值、seed 数据恒有值，但
  events 列可空：若按非空校验，一条缺 result_type 的风险事件将使整个列表
  500，故按可空建模；
- ``order_no`` 由 ``coalesce(data.order_no, business_objects.source_id)`` 派生：
  对象 source_id 非空且 events.object_id 有外键约束 → 恒有值；
- ``summary`` 回退链末端为 event_type（非空）→ 恒有值；
- ``case_id`` 无关联案例（或案例未 DECIDED）时为 null；
- summary/objectives 的 ``current_value``/``unit`` 沿 A.8 列可空性建模；
- pending 的 ``case_no``/``risk_level`` 沿 decision.cases 列可空性（case_no
  由服务端生成、seed 恒有值，但 DDL 列可空）。
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ExceptionItem(BaseModel):
    """B.9 异常列表项（风险事件 + 案例关联派生）。"""

    event_id: UUID
    result_type: str | None = None
    risk_level: str
    object_id: UUID
    order_no: str
    summary: str
    occurred_at: datetime
    case_id: UUID | None = None


class ObjectiveItem(BaseModel):
    """经营目标项（A.8 objectives 投影；summary 与 /objectives 共用）。"""

    objective_id: UUID
    title: str
    target_value: float
    current_value: float | None = None
    status: str


class KpiItem(BaseModel):
    """KPI 项（kpi_definitions join kpi_values 的每 code 最近期值）。"""

    code: str
    name: str
    value: float
    unit: str | None = None
    period: str


class ReportSummaryResponse(BaseModel):
    """GET /ebms/reports/summary 响应（B.9；period 缺省 = objectives 最大期）。"""

    period: str | None = None
    objectives: list[ObjectiveItem] = Field(default_factory=list)
    kpis: list[KpiItem] = Field(default_factory=list)
    recent_changes_summary: list[str] = Field(default_factory=list)


class PendingDecisionItem(BaseModel):
    """待决案例项（B.9 decisions/pending；options 为 JSONB 原样透传）。"""

    case_id: UUID
    case_no: str | None = None
    question: str
    risk_level: str | None = None
    options: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime


class PendingDecisionsResponse(BaseModel):
    """GET /ebms/decisions/pending 响应（items + OPEN 全量计数）。"""

    items: list[PendingDecisionItem] = Field(default_factory=list)
    total_pending: int


class TodoPendingDecisionItem(BaseModel):
    """todos.pending_decisions 项（OPEN cases top 5 简投影）。"""

    case_id: UUID
    risk_level: str | None = None
    created_at: datetime


class TodoPendingActionItem(BaseModel):
    """todos.pending_actions 项（非终态行动，due_date 升序）。"""

    action_id: UUID
    title: str
    status: str
    due_date: datetime | None = None


class TodoExceptionItem(BaseModel):
    """todos.exceptions_to_confirm 项（无关联案例的风险事件）。"""

    event_id: UUID
    risk_level: str


class TodosResponse(BaseModel):
    """GET /ebms/todos 响应（三段聚合，B.9）。"""

    pending_decisions: list[TodoPendingDecisionItem] = Field(default_factory=list)
    pending_actions: list[TodoPendingActionItem] = Field(default_factory=list)
    exceptions_to_confirm: list[TodoExceptionItem] = Field(default_factory=list)
