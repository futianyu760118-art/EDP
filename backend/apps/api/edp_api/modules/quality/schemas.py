"""quality 请求/响应模型（EDP-030，B.13 + MSW 扩展 kpi/dimensions + T4 任务轨道）。

- GET /admin/quality/reports?date=：四段聚合 + kpi/dimensions——形状对齐
  frontend ``mocks/types.ts`` 的 QualityReport（kpi 五字段 / dimensions
  {domain,label,score_pct}[]）；source_count 在真实口径下可空（real/无
  水位降级行），mock 数据全量非空；
- GET /admin/quality/coverage：reports 的 coverage 字段同形；
- POST /admin/quality/rechecks（T4）：{scope} → 202 {task_id, status}；
- GET /admin/quality/tasks/{task_id}（T4）：QualityTaskOut——mocks
  QualityTask（task_id/task_type/status/started_at/logs）的超集，scope/
  ref_name/stats/finished_at 为 mock 缺的可选补齐（前端结构类型按子集
  消费，字段名与 mock 实测对齐）；
- GET /admin/drills（T7，EDP-502 后端）：DrillRecord/DrillRecordsOut——
  W5 三项演练（switchover/pitr/tenant_restore）只读归档，executed_at
  null 透传（未执行 PLANNED 态）。
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReconciliationRow(BaseModel):
    """对账行：(source_system, object_type) 分组。

    source_count 为 None = real/无水位降级（deviation_pct=0.0、ok=true）。
    """

    source_system: str
    object_type: str
    source_count: int | None
    edp_count: int
    deviation_pct: float
    ok: bool


class CoverageByType(BaseModel):
    """分类型覆盖率（by_type 行）。"""

    object_type: str
    coverage_pct: float


class CoverageReport(BaseModel):
    """覆盖率简报：overall + by_type 双口径（空集约定 overall=100.0）。"""

    overall_pct: float
    by_type: list[CoverageByType]


class OrphansReport(BaseModel):
    """孤儿计数：事件悬挂 + 证据悬挂（object_id 无对应注册对象）。"""

    event_orphans: int
    evidence_orphans: int


class ChecksumSampling(BaseModel):
    """P0/P1 证据 checksum 抽检计数（每日上限 120 或全量取小）。"""

    sampled: int
    failed: int


class QualityKpi(BaseModel):
    """质量页 KPI 带（MSW 扩展真数据派生；字段名逐字对齐 mocks/types.ts）。"""

    overall_pct: float
    sla_pct: float
    completeness_pct: float
    pending_exceptions: int
    high_priority: int


class DimensionScore(BaseModel):
    """维度评分行（四段派生；domain ∈ reconciliation/coverage/orphans/
    checksum）。"""

    domain: str
    label: str
    score_pct: float


class QualityReport(BaseModel):
    """B.13 质量报告（date 接受并回显；四段计算恒实时）。"""

    date: str = Field(description="报告日期（请求 date 原样回显；缺省=请求日）")
    reconciliation: list[ReconciliationRow]
    coverage: CoverageReport
    orphans: OrphansReport
    checksum_sampling: ChecksumSampling
    kpi: QualityKpi
    dimensions: list[DimensionScore]


class RecheckRequest(BaseModel):
    """POST /admin/quality/rechecks 请求体（scope 缺省 ALL）。"""

    scope: Literal["RECONCILE", "ORPHAN", "CHECKSUM", "ALL"] = "ALL"


class RecheckAccepted(BaseModel):
    """202 响应：任务已登记（后台异步执行，经 GET tasks/{id} 轮询终态）。"""

    task_id: UUID
    status: str


class TaskLogLine(BaseModel):
    """任务日志行（形状对齐 mocks/types.ts QualityTask.logs）。"""

    ts: datetime
    level: Literal["INFO", "WARN", "ERROR"]
    message: str


class QualityTaskOut(BaseModel):
    """GET /admin/quality/tasks/{task_id} 响应（mocks QualityTask 超集，
    详见模块 docstring）。"""

    model_config = ConfigDict(from_attributes=True)

    task_id: UUID
    task_type: str
    status: str
    scope: str | None = None
    ref_name: str | None = None
    stats: dict[str, Any] = Field(default_factory=dict)
    logs: list[TaskLogLine] = Field(default_factory=list)
    started_at: datetime
    finished_at: datetime | None = None


class DrillRecord(BaseModel):
    """W5 演练记录单项（drill-records.json；演练线手工回填）。

    executed_at 为 null = 未执行（result=PLANNED，T14~T16 实测回填）；
    readings 为自由键值表（读数归档，前端 mono 键值表直渲染）。
    """

    drill_type: str
    executed_at: datetime | None = None
    topology: str
    rto_seconds: float | None = None
    rpo_seconds: float | None = None
    result: str
    readings: dict[str, Any] = Field(default_factory=dict)
    manual_url: str


class DrillRecordsOut(BaseModel):
    """GET /admin/drills 响应：{items: [...]}；文件缺失/坏 JSON → 空列表
    （只读归档面不报错，前端空态）。"""

    items: list[DrillRecord] = Field(default_factory=list)


class OutboxStatusOut(BaseModel):
    """GET /admin/outbox/status 响应（B.13 Outbox 积压卡；W5-05 收口）：
    event.outbox 聚合；空表 → pending 0 / age 与 last_published_at null。"""

    pending_count: int
    oldest_pending_age_seconds: int | None = None
    published_last_hour: int
    dlq_count: int
    last_published_at: str | None = None
