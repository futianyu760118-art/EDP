"""adapters_admin 路由（附录 B.12 最小版）：触发同步 / 状态查询 / 任务历史 / 清单。

router 级挂 tenant_scoped（认证 → 租户状态 → bind_tenant → RLS）；写 =
adapters:write（JWT）或 write:adapters scope，读 = adapters:read 或
readonly scope（双轨判定见 dependencies.py）。同步为 202 异步执行——任务
登记于 ops.tasks（W5 T5），状态查询/历史读任务行（请求会话，受 RLS）。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import EdpError, ErrorCode, error_responses
from edp_api.core.security.principal import Principal
from edp_api.modules.adapters_admin import service as adapters_service
from edp_api.modules.adapters_admin.dependencies import require_read, require_write
from edp_api.modules.adapters_admin.schemas import (
    AdapterJobsResponse,
    AdapterListResponse,
    AdapterStatusResponse,
    AdapterSyncResponse,
    SyncTriggerRequest,
)
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

router = APIRouter(
    prefix="/api/v1/admin/adapters",
    tags=["adapters"],
    dependencies=[Depends(tenant_scoped)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/{adapter_name}/sync",
    response_model=AdapterSyncResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="触发适配器同步（异步执行）",
    responses=error_responses(
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.TENANT_SUSPENDED,
        ErrorCode.NOT_FOUND,
        ErrorCode.CONFLICT,
        descriptions={
            ErrorCode.CONFLICT: "任务冲突（TASK_CONFLICT——同 task_type 已有任务执行中）"
        },
    ),
)
async def trigger_sync(
    adapter_name: str,
    payload: SyncTriggerRequest,
    principal: Annotated[Principal, Depends(require_write("adapters"))],
    sess: DbSession,
) -> AdapterSyncResponse:
    """202 登记 ops.tasks 任务行（RUNNING）后异步执行（run_sync_per_record
    逐记录独立事务）；未注册 404。mode=replay 全量重放（UUIDv5 幂等 →
    duplicated）；since 仅 replay 消费。
    """
    try:
        task = await adapters_service.trigger_sync(
            sess,
            principal.tenant_id,
            adapter_name,
            payload.mode,
            payload.since,
            actor=principal.id,
        )
    except LookupError:
        raise EdpError.not_found("适配器不存在") from None
    return AdapterSyncResponse(
        sync_id=str(task.task_id), status=task.status, started_at=task.started_at
    )


@router.get(
    "/{adapter_name}/status",
    response_model=AdapterStatusResponse,
    summary="查询适配器最近一次同步状态",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.TENANT_SUSPENDED,
        ErrorCode.NOT_FOUND,
    ),
)
async def adapter_status(
    adapter_name: str,
    principal: Annotated[Principal, Depends(require_read("adapters"))],
    sess: DbSession,
) -> AdapterStatusResponse:
    """最近任务（RUNNING/SUCCEEDED/FAILED + stats）；未跑过 last_sync=null。"""
    try:
        return await adapters_service.adapter_status(
            sess, principal.tenant_id, adapter_name
        )
    except LookupError:
        raise EdpError.not_found("适配器不存在") from None


@router.get(
    "/{adapter_name}/jobs",
    response_model=AdapterJobsResponse,
    summary="适配器同步任务历史（ops.tasks 落库，游标分页）",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.TENANT_SUSPENDED,
        ErrorCode.NOT_FOUND,
    ),
)
async def adapter_jobs(
    adapter_name: str,
    principal: Annotated[Principal, Depends(require_read("adapters"))],
    sess: DbSession,
    limit: Annotated[int, Query(ge=1, le=adapters_service.MAX_JOBS_LIMIT)] = (
        adapters_service.DEFAULT_JOBS_LIMIT
    ),
    cursor: Annotated[str | None, Query()] = None,
) -> AdapterJobsResponse:
    """该适配器历史 sync 任务（started_at DESC + task_id DESC tiebreak）；
    未注册 404。"""
    try:
        items, next_cursor = await adapters_service.list_jobs(
            sess, principal.tenant_id, adapter_name, limit=limit, cursor=cursor
        )
    except LookupError:
        raise EdpError.not_found("适配器不存在") from None
    return AdapterJobsResponse(items=items, next_cursor=next_cursor)


@router.get(
    "",
    response_model=AdapterListResponse,
    summary="适配器清单与运行状态",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED, ErrorCode.FORBIDDEN, ErrorCode.TENANT_SUSPENDED
    ),
)
async def list_adapters(
    principal: Annotated[Principal, Depends(require_read("adapters"))],
    sess: DbSession,
) -> AdapterListResponse:
    """注册表适配器清单（mode/运行状态/探活/水位时间）。"""
    items = await adapters_service.list_adapters(sess, principal.tenant_id)
    return AdapterListResponse(items=items, next_cursor=None)
