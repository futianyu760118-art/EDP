"""ebms 服务：EBMS 查询聚合（B.9，EDP-012 + W4 四端点）。

exceptions（EDP-012）：风险事件（``risk_level IS NOT NULL``）按 occurred_at
DESC 游标分页；``severity`` → risk_level 等值；``status``（spec §6.1）：
OPEN（默认）= 无已 DECIDED 的关联案例、RESOLVED = 存在已 DECIDED 的关联案例
（EXISTS 相关子查询，与 join 行无关）；``case_id`` 经 decision.cases **标量
子查询**派生（``tenant/source_id=cast(event_id)`` 匹配 + ``created_at DESC
LIMIT 1``——与 0012 唯一索引 uq_cases_tenant_source 双保险：索引挡写入重复、
子查询挡读取倍增）；``order_no`` =
``coalesce(data->>'order_no', business_objects.source_id)``；``summary`` =
``coalesce(data->>'summary', data->>'reason', event_type)``。

W4 四端点（EDP-012 残余，B.9 逐字段）：
- reports/summary：objectives（period 匹配 + status=ACTIVE；period 缺省取
  数据中最大期）+ kpis（kpi_definitions join kpi_values，每 code 取 period
  最近值）+ recent_changes_summary（风险事件最近 5 条 ``订单 {order_no}
  {summary}`` 文案，order_no/summary 沿 exceptions 的 coalesce 派生）；
- decisions/pending：OPEN cases 按 risk（P0→0/P1→1/P2→2/其余→3）+
  created_at ASC 排序，limit 1..20 默认 5；total_pending = OPEN 全量计数；
- todos：pending_decisions（OPEN cases top 5）/ pending_actions（非终态
  ``NOT IN ('VERIFIED','CANCELLED','REJECTED')``，due_date 升序空值在后）/
  exceptions_to_confirm（风险事件 LEFT JOIN cases ON source_id 无案例者）；
- objectives：objectives 完整列表（无 period/status 过滤）。

跨模块表（event.events、decision.cases、master.business_objects、
management.*、action.actions）以 core ``table()`` 构造参与纯 SQL 读——模块间
仅可 import 对方 service，ORM 不可直接引用（口径同 tools/ingest 的跨模块读）；
RLS 会话已 bind_tenant，跨租户行不可见。

游标锚 ``{"o","i"}`` 与 events 一致（occurred_at DESC, event_id DESC
tiebreak）；非法 cursor 视为首页。
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Numeric,
    Text,
    Uuid,
    and_,
    case,
    cast,
    column,
    func,
    or_,
    select,
    table,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.pagination import Page, decode_cursor, encode_cursor
from edp_api.modules.ebms.schemas import (
    ExceptionItem,
    KpiItem,
    ObjectiveItem,
    PendingDecisionItem,
    PendingDecisionsResponse,
    ReportSummaryResponse,
    TodoExceptionItem,
    TodoPendingActionItem,
    TodoPendingDecisionItem,
    TodosResponse,
)

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
PENDING_DEFAULT_LIMIT = 5
PENDING_MAX_LIMIT = 20
RECENT_CHANGES_LIMIT = 5

STATUS_OPEN = "OPEN"
STATUS_RESOLVED = "RESOLVED"

_EVENTS = table(
    "events",
    column("event_id", Uuid),
    column("tenant_id", Uuid),
    column("event_type", Text),
    column("object_id", Uuid),
    column("result_type", Text),
    column("risk_level", Text),
    column("occurred_at", DateTime(timezone=True)),
    column("data", JSONB),
    schema="event",
)

_CASES = table(
    "cases",
    column("case_id", Uuid),
    column("tenant_id", Uuid),
    column("case_no", Text),
    column("question", Text),
    column("options", JSONB),
    column("risk_level", Text),
    column("source_id", Text),
    column("status", Text),
    column("created_at", DateTime(timezone=True)),
    schema="decision",
)

_BUSINESS_OBJECTS = table(
    "business_objects",
    column("object_id", Uuid),
    column("source_id", Text),
    schema="master",
)

_OBJECTIVES = table(
    "objectives",
    column("objective_id", Uuid),
    column("tenant_id", Uuid),
    column("title", Text),
    column("target_value", Numeric),
    column("current_value", Numeric),
    column("period", Text),
    column("status", Text),
    schema="management",
)

_KPI_DEFINITIONS = table(
    "metrics",
    column("metric_id", Uuid),
    column("tenant_id", Uuid),
    column("code", Text),
    column("name", Text),
    column("unit", Text),
    schema="metric",
)

_KPI_VALUES = table(
    "metric_values",
    column("value_id", Uuid),
    column("tenant_id", Uuid),
    column("metric_id", Uuid),
    column("period", Text),
    column("value", Numeric),
    schema="metric",
)

_ACTIONS = table(
    "actions",
    column("action_id", Uuid),
    column("tenant_id", Uuid),
    column("title", Text),
    column("status", Text),
    column("due_date", DateTime(timezone=True)),
    schema="action",
)

# 行动终态（todos.pending_actions 排除集；B.9「待执行/待验证行动」口径）
ACTION_TERMINAL_STATUSES = ("VERIFIED", "CANCELLED", "REJECTED")


def _decided_case_exists():
    """关联案例已 DECIDED 的 EXISTS 子查询（显式 correlate events——子查询内
    decision.cases 独立于主查询的 join，多案例时语义仍为「存在已决策案例」）。"""
    return (
        select(1)
        .select_from(_CASES)
        .where(
            _CASES.c.source_id == cast(_EVENTS.c.event_id, Text),
            _CASES.c.tenant_id == _EVENTS.c.tenant_id,
            _CASES.c.status == "DECIDED",
        )
        .correlate(_EVENTS)
        .exists()
    )


def _case_id_scalar():
    """case_id 标量子查询：source 事件 → 关联案例（created_at DESC LIMIT 1）。

    与 0012 部分唯一索引 uq_cases_tenant_source 双保险（索引挡写入重复，
    子查询挡读取倍增——左连版本在约束缺失时会把单事件倍增多行）；显式
    correlate events。
    """
    return (
        select(_CASES.c.case_id)
        .where(
            _CASES.c.source_id == cast(_EVENTS.c.event_id, Text),
            _CASES.c.tenant_id == _EVENTS.c.tenant_id,
        )
        .order_by(_CASES.c.created_at.desc(), _CASES.c.case_id.desc())
        .limit(1)
        .correlate(_EVENTS)
        .scalar_subquery()
        .label("case_id")
    )


def _exceptions_query():
    """查询骨架：case_id 标量子查询派生、左连对象表供 order_no 回退。"""
    order_no = func.coalesce(
        _EVENTS.c.data["order_no"].astext, _BUSINESS_OBJECTS.c.source_id
    ).label("order_no")
    summary = func.coalesce(
        _EVENTS.c.data["summary"].astext,
        _EVENTS.c.data["reason"].astext,
        _EVENTS.c.event_type,
    ).label("summary")
    return (
        select(
            _EVENTS.c.event_id,
            _EVENTS.c.result_type,
            _EVENTS.c.risk_level,
            _EVENTS.c.object_id,
            order_no,
            summary,
            _EVENTS.c.occurred_at,
            _case_id_scalar(),
        )
        .select_from(_EVENTS)
        .outerjoin(
            _BUSINESS_OBJECTS, _BUSINESS_OBJECTS.c.object_id == _EVENTS.c.object_id
        )
    )


async def query_exceptions(
    sess: AsyncSession,
    *,
    severity: str | None = None,
    status: str = STATUS_OPEN,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[ExceptionItem]:
    """风险事件列表（B.9）：severity/status 过滤 + 游标分页（不填充 total）。"""
    limit = max(1, min(limit, MAX_LIMIT))
    conditions = [_EVENTS.c.risk_level.is_not(None)]
    if severity:
        conditions.append(_EVENTS.c.risk_level == severity)
    decided_exists = _decided_case_exists()
    conditions.append(decided_exists if status == STATUS_RESOLVED else ~decided_exists)

    stmt = _exceptions_query().where(*conditions)

    decoded = decode_cursor(cursor)
    if decoded is not None:
        anchor = _parse_anchor(decoded)
        if anchor is not None:
            occurred_at, event_id_anchor = anchor
            stmt = stmt.where(
                or_(
                    _EVENTS.c.occurred_at < occurred_at,
                    and_(
                        _EVENTS.c.occurred_at == occurred_at,
                        _EVENTS.c.event_id < event_id_anchor,
                    ),
                )
            )

    stmt = stmt.order_by(
        _EVENTS.c.occurred_at.desc(), _EVENTS.c.event_id.desc()
    ).limit(limit + 1)
    rows = (await sess.execute(stmt)).mappings().all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"o": last["occurred_at"].isoformat(), "i": str(last["event_id"])}
        )
    return Page(
        items=[ExceptionItem.model_validate(dict(row)) for row in page_rows],
        next_cursor=next_cursor,
    )


def _parse_anchor(decoded: dict) -> tuple[datetime, UUID] | None:
    """cursor 载荷 → (occurred_at, event_id)；缺字段/格式非法 → None。"""
    try:
        return datetime.fromisoformat(str(decoded["o"])), UUID(str(decoded["i"]))
    except (KeyError, TypeError, ValueError):
        return None


# ---- W4：reports/summary / decisions/pending / todos / objectives ----


def _risk_order(column_ref):
    """risk 排序键：P0→0 / P1→1 / P2→2 / 其余（P3 与 NULL）→3。"""
    return case(
        (column_ref == "P0", 0),
        (column_ref == "P1", 1),
        (column_ref == "P2", 2),
        else_=3,
    )


def _objectives_stmt() -> select:
    """objectives 投影（objective_id/title/target_value/current_value/status）。"""
    return select(
        _OBJECTIVES.c.objective_id,
        _OBJECTIVES.c.title,
        _OBJECTIVES.c.target_value,
        _OBJECTIVES.c.current_value,
        _OBJECTIVES.c.status,
    )


async def query_objectives(sess: AsyncSession) -> list[ObjectiveItem]:
    """经营目标完整列表（B.9 /objectives；无 period/status 过滤）。

    排序 period DESC（近期优先）+ objective_id（确定性）。
    """
    stmt = _objectives_stmt().order_by(
        _OBJECTIVES.c.period.desc(), _OBJECTIVES.c.objective_id
    )
    rows = (await sess.execute(stmt)).mappings().all()
    return [ObjectiveItem.model_validate(dict(row)) for row in rows]


async def query_report_summary(
    sess: AsyncSession, *, period: str | None = None
) -> ReportSummaryResponse:
    """经营简报（B.9 reports/summary）三段聚合。

    - period 缺省 = objectives 数据中最大 period（无数据 → None + 空 objectives）；
    - objectives：period 精确匹配 + status=ACTIVE（B.9 示例语义，计划卡口径）；
    - kpis：与 period 参数无关，每 code 取 kpi_values 中 period 最近值；
    - recent_changes_summary：风险事件最近 5 条 ``订单 {order_no} {summary}``。
    """
    if period is None:
        period = (
            await sess.execute(select(func.max(_OBJECTIVES.c.period)))
        ).scalar_one_or_none()

    objectives: list[ObjectiveItem] = []
    if period is not None:
        stmt = (
            _objectives_stmt()
            .where(_OBJECTIVES.c.period == period, _OBJECTIVES.c.status == "ACTIVE")
            .order_by(_OBJECTIVES.c.objective_id)
        )
        rows = (await sess.execute(stmt)).mappings().all()
        objectives = [ObjectiveItem.model_validate(dict(row)) for row in rows]

    return ReportSummaryResponse(
        period=period,
        objectives=objectives,
        kpis=await _latest_kpis(sess),
        recent_changes_summary=await _recent_changes_summary(sess),
    )


async def _latest_kpis(sess: AsyncSession) -> list[KpiItem]:
    """每 code 取 period 最近值（Metric Registry：metric.metrics join
    metric.metric_values——V1.2 T26 起 EBMS 指标全量走 Registry，前端零公式）。

    「最近」按 period 文本序（ISO 周 YYYY-Www 字典序 = 时间序）；无值的定义
    不在列（inner join）。排序 code ASC（响应稳定）。
    """
    latest = (
        select(
            _KPI_VALUES.c.metric_id.label("metric_id"),
            func.max(_KPI_VALUES.c.period).label("max_period"),
        )
        .group_by(_KPI_VALUES.c.metric_id)
        .subquery()
    )
    stmt = (
        select(
            _KPI_DEFINITIONS.c.code,
            _KPI_DEFINITIONS.c.name,
            _KPI_VALUES.c.value,
            _KPI_DEFINITIONS.c.unit,
            _KPI_VALUES.c.period,
        )
        .select_from(_KPI_DEFINITIONS)
        .join(
            _KPI_VALUES,
            and_(
                _KPI_VALUES.c.metric_id == _KPI_DEFINITIONS.c.metric_id,
                _KPI_VALUES.c.tenant_id == _KPI_DEFINITIONS.c.tenant_id,
            ),
        )
        .join(
            latest,
            and_(
                latest.c.metric_id == _KPI_VALUES.c.metric_id,
                latest.c.max_period == _KPI_VALUES.c.period,
            ),
        )
        .order_by(_KPI_DEFINITIONS.c.code)
    )
    rows = (await sess.execute(stmt)).mappings().all()
    return [KpiItem.model_validate(dict(row)) for row in rows]


async def _recent_changes_summary(sess: AsyncSession) -> list[str]:
    """风险事件最近 5 条文案：``订单 {order_no} {summary}``（B.9 示例风格）。

    order_no/summary 沿 exceptions 的 coalesce 派生（data.order_no → 对象
    source_id；data.summary → data.reason → event_type）。
    """
    order_no = func.coalesce(
        _EVENTS.c.data["order_no"].astext, _BUSINESS_OBJECTS.c.source_id
    ).label("order_no")
    summary = func.coalesce(
        _EVENTS.c.data["summary"].astext,
        _EVENTS.c.data["reason"].astext,
        _EVENTS.c.event_type,
    ).label("summary")
    stmt = (
        select(order_no, summary)
        .select_from(_EVENTS)
        .outerjoin(
            _BUSINESS_OBJECTS, _BUSINESS_OBJECTS.c.object_id == _EVENTS.c.object_id
        )
        .where(_EVENTS.c.risk_level.is_not(None))
        .order_by(_EVENTS.c.occurred_at.desc(), _EVENTS.c.event_id.desc())
        .limit(RECENT_CHANGES_LIMIT)
    )
    rows = (await sess.execute(stmt)).mappings().all()
    return [f"订单 {row['order_no']} {row['summary']}" for row in rows]


def _open_cases_order():
    """OPEN cases 通用排序：risk（P0 最先）+ created_at ASC + case_id 兜底。"""
    return (
        _risk_order(_CASES.c.risk_level),
        _CASES.c.created_at.asc(),
        _CASES.c.case_id.asc(),
    )


async def query_pending_decisions(
    sess: AsyncSession, *, limit: int = PENDING_DEFAULT_LIMIT
) -> PendingDecisionsResponse:
    """待决案例（B.9 decisions/pending）：risk + created_at 排序前 limit 条 +
    OPEN 全量计数（total_pending）。limit 收敛 1..20（路由层已校验）。"""
    limit = max(1, min(limit, PENDING_MAX_LIMIT))
    total = (
        await sess.execute(
            select(func.count()).select_from(_CASES).where(_CASES.c.status == "OPEN")
        )
    ).scalar_one()
    stmt = (
        select(
            _CASES.c.case_id,
            _CASES.c.case_no,
            _CASES.c.question,
            _CASES.c.risk_level,
            _CASES.c.options,
            _CASES.c.created_at,
        )
        .where(_CASES.c.status == "OPEN")
        .order_by(*_open_cases_order())
        .limit(limit)
    )
    rows = (await sess.execute(stmt)).mappings().all()
    return PendingDecisionsResponse(
        items=[PendingDecisionItem.model_validate(dict(row)) for row in rows],
        total_pending=total,
    )


async def query_todos(sess: AsyncSession) -> TodosResponse:
    """待办聚合（B.9 todos）三段：待决决策 / 非终态行动 / 异常待确认。"""
    decisions_stmt = (
        select(_CASES.c.case_id, _CASES.c.risk_level, _CASES.c.created_at)
        .where(_CASES.c.status == "OPEN")
        .order_by(*_open_cases_order())
        .limit(PENDING_DEFAULT_LIMIT)
    )
    decision_rows = (await sess.execute(decisions_stmt)).mappings().all()

    actions_stmt = (
        select(
            _ACTIONS.c.action_id,
            _ACTIONS.c.title,
            _ACTIONS.c.status,
            _ACTIONS.c.due_date,
        )
        .where(_ACTIONS.c.status.not_in(ACTION_TERMINAL_STATUSES))
        .order_by(_ACTIONS.c.due_date.asc().nulls_last(), _ACTIONS.c.action_id.asc())
    )
    action_rows = (await sess.execute(actions_stmt)).mappings().all()

    case_exists = (
        select(1)
        .select_from(_CASES)
        .where(
            _CASES.c.source_id == cast(_EVENTS.c.event_id, Text),
            _CASES.c.tenant_id == _EVENTS.c.tenant_id,
        )
        .correlate(_EVENTS)
        .exists()
    )
    exceptions_stmt = (
        select(_EVENTS.c.event_id, _EVENTS.c.risk_level)
        .where(_EVENTS.c.risk_level.is_not(None), ~case_exists)
        .order_by(_EVENTS.c.occurred_at.desc(), _EVENTS.c.event_id.desc())
    )
    exception_rows = (await sess.execute(exceptions_stmt)).mappings().all()

    return TodosResponse(
        pending_decisions=[
            TodoPendingDecisionItem.model_validate(dict(row)) for row in decision_rows
        ],
        pending_actions=[
            TodoPendingActionItem.model_validate(dict(row)) for row in action_rows
        ],
        exceptions_to_confirm=[
            TodoExceptionItem.model_validate(dict(row)) for row in exception_rows
        ],
    )
