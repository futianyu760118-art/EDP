"""quality 路由（EDP-030）：/admin/quality 报告、覆盖率与任务轨道。

- GET ``/reports?date=``（quality:read）→ 四段聚合 + kpi/dimensions；
  date 接受并回显（缺省 = 请求日），计算恒实时（不回溯——预聚合 W6
  评估，偏差登记 §13.3）；
- GET ``/coverage``（quality:read）→ reports 的 coverage 字段同形
  （Go/No-Go ≥95% 周报数据源）；
- POST ``/rechecks``（quality:run，T4）→ 建 quality_recheck 任务行
  （RUNNING）→ 202 {task_id, status}；后台执行对应段计算（scope 单段 /
  ALL 四段），stats/logs 逐段落库，完成写 quality.recheck_succeeded/
  failed 事件（执行语义见 service docstring）；
- GET ``/tasks/{task_id}``（quality:read，T4）→ 任务详情（status/stats/
  logs 轮询；RLS——跨租户行不可见统一 404）。

drills 路由（EDP-502 后端 / W5 T7）：GET ``/api/v1/admin/drills``
（quality:run——W5-21-c 收紧：内容由 quality:read 改 run 轨道，去掉
MANAGER/ANALYST；基础设施元数据最小权限收口，W5 终审裁定）→ W5 三项
演练只读归档（drill-records.json；口径见 service docstring）。

outbox 路由（W6 / W5-05 收口）：GET ``/api/v1/admin/outbox/status``
（quality:read）→ event.outbox 聚合（积压龄/近 1h 发布/死信；数据源
events.service.outbox_status，口径见 service docstring）。

router 级挂 tenant_scoped（认证 → 租户状态 → bind_tenant → RLS）；无
SERVICE scope 轨道（鉴权口径见 dependencies 模块 docstring）。
"""

from datetime import UTC, date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import EdpError, ErrorCode, error_responses
from edp_api.core.security.principal import Principal
from edp_api.modules.quality import service as quality_service
from edp_api.modules.quality.dependencies import require_quality_read, require_quality_run
from edp_api.modules.quality.schemas import (
    CoverageReport,
    DrillRecordsOut,
    OutboxStatusOut,
    QualityReport,
    QualityTaskOut,
    RecheckAccepted,
    RecheckRequest,
)
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

router = APIRouter(
    prefix="/api/v1/admin/quality",
    tags=["quality"],
    dependencies=[Depends(tenant_scoped)],
)

drills_router = APIRouter(
    prefix="/api/v1/admin/drills",
    tags=["drills"],
    dependencies=[Depends(tenant_scoped)],
)

outbox_router = APIRouter(
    prefix="/api/v1/admin",
    tags=["outbox"],
    dependencies=[Depends(tenant_scoped)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]

_READ_ERRORS = (
    ErrorCode.UNAUTHENTICATED,
    ErrorCode.FORBIDDEN,
    ErrorCode.TENANT_SUSPENDED,
)
_RUN_ERRORS = (
    ErrorCode.UNAUTHENTICATED,
    ErrorCode.FORBIDDEN,
    ErrorCode.TENANT_SUSPENDED,
)


@router.get(
    "/reports",
    response_model=QualityReport,
    summary="质量报告（对账/覆盖率/孤儿/checksum 抽检四段 + kpi/dimensions）",
    responses=error_responses(*_READ_ERRORS),
)
async def quality_reports(
    principal: Annotated[Principal, Depends(require_quality_read())],
    sess: DbSession,
    report_date: Annotated[
        date | None,
        Query(
            alias="date",
            description="报告日期（接受并回显；计算恒实时，不回溯）",
        ),
    ] = None,
) -> QualityReport:
    """四段实时聚合 + kpi/dimensions 扩展（口径见 service docstring）；
    checksum 失配行同事务落 quality.checksum_failed 事件。"""
    echoed = (
        report_date.isoformat()
        if report_date is not None
        else datetime.now(UTC).date().isoformat()
    )
    return await quality_service.build_report(sess, principal, report_date=echoed)


@router.get(
    "/coverage",
    response_model=CoverageReport,
    summary="对象覆盖率简报（reports 的 coverage 字段同形）",
    responses=error_responses(*_READ_ERRORS),
)
async def quality_coverage(
    principal: Annotated[Principal, Depends(require_quality_read())],
    sess: DbSession,
) -> CoverageReport:
    """已接入对象/注册对象（overall + by_type；空集约定 100.0）。"""
    return await quality_service.build_coverage(sess)


@router.post(
    "/rechecks",
    status_code=202,
    response_model=RecheckAccepted,
    summary="触发质量重校验（异步：登记任务行后后台执行）",
    responses=error_responses(
        *_RUN_ERRORS,
        ErrorCode.CONFLICT,
        descriptions={
            ErrorCode.CONFLICT: "任务冲突（TASK_CONFLICT——同 task_type 已有任务执行中）"
        },
    ),
)
async def quality_rechecks(
    principal: Annotated[Principal, Depends(require_quality_run())],
    sess: DbSession,
    payload: RecheckRequest,
) -> RecheckAccepted:
    """quality:run（ADMIN 轨道）：建 quality_recheck 任务行（RUNNING）→
    202；进度与终态经 GET /tasks/{task_id} 轮询（stats/logs 逐段落库），
    完成写 quality.recheck_succeeded/failed 事件（单副本执行语义见
    service docstring）。"""
    task = await quality_service.start_recheck(sess, principal, scope=payload.scope)
    return RecheckAccepted(task_id=task.task_id, status=task.status)


@router.get(
    "/tasks/{task_id}",
    response_model=QualityTaskOut,
    summary="质量任务详情（status/stats/logs 轮询；跨租户统一 404）",
    responses=error_responses(ErrorCode.NOT_FOUND, *_READ_ERRORS),
)
async def quality_task(
    task_id: UUID,
    principal: Annotated[Principal, Depends(require_quality_read())],
    sess: DbSession,
) -> QualityTaskOut:
    """quality:read：任务行（RLS 会话——跨租户行不可见 → 404，不泄露
    存在性）。"""
    task = await quality_service.get_task(sess, task_id)
    if task is None:
        raise EdpError.not_found("任务不存在")
    return QualityTaskOut.model_validate(task)


@drills_router.get(
    "",
    response_model=DrillRecordsOut,
    summary="演练记录（W5 三项：HA 切换/PITR/租户级恢复——只读归档）",
    responses=error_responses(*_RUN_ERRORS),
)
async def drill_records(
    principal: Annotated[Principal, Depends(require_quality_run())],
) -> DrillRecordsOut:
    """quality:run（W5-21-c 收紧：PLATFORM_ADMIN/ADMIN——MANAGER/ANALYST
    403；内容为基础设施元数据、无凭据，最小权限原则收口，W5 终审裁定）：
    读 drill-records.json（默认仓库相对路径，相对 cwd
    解析；EDP_DRILLS_FILE 可覆盖——容器内经卷挂载 + env 指向，staging
    compose 注释 T14 处理）→ {items}；文件缺失/坏 JSON → {items: []}
    （不报错，前端空态）。executed_at null = 未执行（PLANNED）。"""
    return DrillRecordsOut(items=quality_service.list_drills())


@outbox_router.get(
    "/outbox/status",
    response_model=OutboxStatusOut,
    summary="事务性发件箱状态（积压/近 1h 发布/死信聚合）",
    responses=error_responses(*_READ_ERRORS),
)
async def outbox_status(
    principal: Annotated[Principal, Depends(require_quality_read())],
    sess: DbSession,
) -> OutboxStatusOut:
    """quality:read：event.outbox 聚合（W5-05 收口）——运营报告/健康页
    Outbox 积压卡数据源；RLS 会话限本租户，空表 → pending 0 /
    oldest_pending_age_seconds 与 last_published_at null。"""
    return await quality_service.build_outbox_status(sess)
