"""ebms 路由（附录 B.9，EDP-012 + W4 四端点）：风险事件与经营查询。

- GET /api/v1/ebms/exceptions：severity（risk_level 等值）/status（OPEN 默认 /
  RESOLVED）过滤 + 游标分页；
- GET /api/v1/ebms/reports/summary：objectives/kpis/recent_changes_summary
  三段聚合（period 缺省 = objectives 最大期）；
- GET /api/v1/ebms/decisions/pending：OPEN cases（risk + created_at 排序）
  前 limit 条 + total_pending 全量计数（limit 1..20 默认 5）；
- GET /api/v1/ebms/todos：pending_decisions/pending_actions/
  exceptions_to_confirm 三段待办聚合；
- GET /api/v1/ebms/objectives：经营目标完整列表（同 summary.objectives
  全量版，无 period 过滤）。

鉴权双轨（HUMAN ebms:read / SERVICE readonly）沿 exceptions 端点。响应
B.9 形状（items + next_cursor）：``Page.total`` 仅 events 填充，exceptions
端点经 ``response_model_exclude`` 剔除，同时保留 ``case_id: null`` 等 B.9
字段。

router 级挂 tenant_scoped（认证 → 租户状态 → bind_tenant → RLS）；路由单独挂
require_ebms_read() 以取回 Principal。
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import ErrorCode, error_responses
from edp_api.core.pagination import Page
from edp_api.core.security.principal import Principal
from edp_api.modules.ebms import service as ebms_service
from edp_api.modules.ebms.dependencies import require_ebms_read
from edp_api.modules.ebms.schemas import (
    ExceptionItem,
    ObjectiveItem,
    PendingDecisionsResponse,
    ReportSummaryResponse,
    TodosResponse,
)
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

router = APIRouter(
    prefix="/api/v1/ebms",
    tags=["ebms"],
    dependencies=[Depends(tenant_scoped)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]

_ERROR_CODES = error_responses(
    ErrorCode.VALIDATION_ERROR,
    ErrorCode.UNAUTHENTICATED,
    ErrorCode.FORBIDDEN,
    ErrorCode.TENANT_SUSPENDED,
)


@router.get(
    "/exceptions",
    response_model=Page[ExceptionItem],
    response_model_exclude={"total"},
    summary="风险事件列表（EBMS 异常视图）",
    responses=_ERROR_CODES,
)
async def list_exceptions(
    principal: Annotated[Principal, Depends(require_ebms_read())],
    sess: DbSession,
    severity: Annotated[
        Literal["P0", "P1", "P2", "P3"] | None, Query(description="风险级别过滤")
    ] = None,
    status_filter: Annotated[
        Literal["OPEN", "RESOLVED"],
        Query(alias="status", description="处理状态（默认 OPEN：无已决策案例）"),
    ] = "OPEN",
    limit: Annotated[int, Query(ge=1, le=ebms_service.MAX_LIMIT)] = (
        ebms_service.DEFAULT_LIMIT
    ),
    cursor: Annotated[str | None, Query()] = None,
) -> Page[ExceptionItem]:
    """风险事件列表（occurred_at DESC）；case_id 为案例关联派生（B.9）。"""
    return await ebms_service.query_exceptions(
        sess,
        severity=severity,
        status=status_filter,
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/reports/summary",
    response_model=ReportSummaryResponse,
    summary="经营简报（目标 + KPI + 最新风险动态）",
    responses=_ERROR_CODES,
)
async def report_summary(
    principal: Annotated[Principal, Depends(require_ebms_read())],
    sess: DbSession,
    period: Annotated[
        str | None, Query(description="目标周期（YYYY-MM；缺省取数据中最大期）")
    ] = None,
) -> ReportSummaryResponse:
    """B.9 reports/summary：objectives（period 匹配）/ kpis（每 code 最近值）/
    recent_changes_summary（风险事件最近 5 条）。"""
    return await ebms_service.query_report_summary(sess, period=period)


@router.get(
    "/decisions/pending",
    response_model=PendingDecisionsResponse,
    summary="待决案例（TOP DECISION）",
    responses=_ERROR_CODES,
)
async def list_pending_decisions(
    principal: Annotated[Principal, Depends(require_ebms_read())],
    sess: DbSession,
    limit: Annotated[
        int,
        Query(ge=1, le=ebms_service.PENDING_MAX_LIMIT, description="返回条数上限"),
    ] = ebms_service.PENDING_DEFAULT_LIMIT,
) -> PendingDecisionsResponse:
    """OPEN cases 按 risk（P0 最先）+ created_at 排序前 limit 条；
    total_pending 为 OPEN 全量计数（B.9）。"""
    return await ebms_service.query_pending_decisions(sess, limit=limit)


@router.get(
    "/todos",
    response_model=TodosResponse,
    summary="待办聚合（决策 + 行动 + 异常确认）",
    responses=_ERROR_CODES,
)
async def list_todos(
    principal: Annotated[Principal, Depends(require_ebms_read())],
    sess: DbSession,
) -> TodosResponse:
    """B.9 todos：pending_decisions（OPEN top 5）/ pending_actions（非终态，
    due_date 升序空值在后）/ exceptions_to_confirm（无关联案例的风险事件）。"""
    return await ebms_service.query_todos(sess)


@router.get(
    "/objectives",
    response_model=list[ObjectiveItem],
    summary="经营目标列表",
    responses=_ERROR_CODES,
)
async def list_objectives(
    principal: Annotated[Principal, Depends(require_ebms_read())],
    sess: DbSession,
) -> list[ObjectiveItem]:
    """经营目标完整列表（同 reports/summary.objectives 全量版，无 period
    过滤，B.9）。"""
    return await ebms_service.query_objectives(sess)
