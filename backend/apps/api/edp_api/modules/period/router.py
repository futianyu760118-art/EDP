"""period 路由（V1.2 T24）：AEOS 经营窗口 + 周期枚举（metric:read 轨道）。

时间维度不硬编码在 EBMS 页面——统一由 EDP Period Service 提供。
"""

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import ErrorCode, error_responses
from edp_api.core.security.principal import Principal
from edp_api.modules.metric.dependencies import require_metric_read
from edp_api.modules.period import service as period_service
from edp_api.modules.period.schemas import PeriodKindItem, PeriodWindowOut
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

router = APIRouter(
    prefix="/api/v1/periods",
    tags=["periods"],
    dependencies=[Depends(tenant_scoped)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]

_READ_ERRORS = (
    ErrorCode.UNAUTHENTICATED,
    ErrorCode.FORBIDDEN,
    ErrorCode.TENANT_SUSPENDED,
)

_KIND_LABELS = {
    "DAILY": "自然日",
    "WEEKLY": "ISO 自然周（YYYY-Www）",
    "MONTHLY": "自然月",
    "AEOS": "AEOS 经营周期（上月16日～当月15日）",
    "CUSTOM": "自定义周期（由消费方显式指定起止）",
    "ROLLING_7D": "滚动7天",
    "ROLLING_30D": "滚动30天",
}


@router.get(
    "/aeos",
    response_model=PeriodWindowOut,
    summary="AEOS 经营窗口（缺省当前日期；date 可指定）",
    responses=error_responses(*_READ_ERRORS),
)
async def get_aeos_window(
    principal: Annotated[Principal, Depends(require_metric_read())],
    sess: DbSession,
    date_param: Annotated[
        date | None, Query(alias="date", description="指定日期（缺省=今天 UTC）")
    ] = None,
) -> PeriodWindowOut:
    day = date_param or datetime.now(UTC).date()
    window = period_service.aeos_window_for(day)
    return PeriodWindowOut(
        kind=window.kind, label=window.label, start=window.start, end=window.end
    )


@router.get(
    "/kinds",
    response_model=list[PeriodKindItem],
    summary="周期类型枚举（含边界说明）",
    responses=error_responses(*_READ_ERRORS),
)
async def list_period_kinds(
    principal: Annotated[Principal, Depends(require_metric_read())],
    sess: DbSession,
) -> list[PeriodKindItem]:
    return [
        PeriodKindItem(kind=kind, description=_KIND_LABELS[kind])
        for kind in period_service.PERIOD_KINDS
    ]
