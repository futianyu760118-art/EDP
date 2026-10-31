"""traces 路由（附录 B.10，EDP-013）：Agent 执行轨迹写入与查询。

- POST /traces：API Key ``write:trace``（HUMAN 无角色持有 trace:write →
  403）→ 201 {trace_id, status, created_at}；同 trace_id 重发 → 200 幂等
  返回既有（不重写 tool_calls）；capability_id 不存在 → 400；
- GET /traces：JWT ``trace:read`` / readonly，agent_id/task_id/
  capability_id/since 过滤 + 游标分页（started_at DESC, trace_id DESC），
  列表为简投影；
- GET /traces/{trace_id}：完整轨迹含 tool_calls[]（seq 升序）；跨租户
  统一 404。

router 级挂 tenant_scoped（认证 → 租户状态 → bind_tenant → RLS）；每条路由
单独挂鉴权依赖以取回 Principal。
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import EdpError, ErrorCode, error_responses
from edp_api.core.pagination import Page
from edp_api.core.security.principal import Principal
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped
from edp_api.modules.traces import service as traces_service
from edp_api.modules.traces.dependencies import require_read, require_write
from edp_api.modules.traces.schemas import (
    TraceCreatedResponse,
    TraceCreateRequest,
    TraceDetail,
    TraceListItem,
)

router = APIRouter(
    prefix="/api/v1",
    tags=["traces"],
    dependencies=[Depends(tenant_scoped)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]

_READ_ERRORS = (
    ErrorCode.UNAUTHENTICATED,
    ErrorCode.FORBIDDEN,
    ErrorCode.TENANT_SUSPENDED,
)
_WRITE_ERRORS = (*_READ_ERRORS, ErrorCode.VALIDATION_ERROR, ErrorCode.CONFLICT)


@router.post(
    "/traces",
    response_model=TraceCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="写入执行轨迹（Agent Runtime 一次执行一条，tool_calls 随行）",
    responses=error_responses(*_WRITE_ERRORS),
)
async def create_trace(
    payload: TraceCreateRequest,
    principal: Annotated[Principal, Depends(require_write())],
    sess: DbSession,
) -> TraceCreatedResponse:
    """新 trace → 201；同 trace_id 重发 → 200 幂等返回既有（Agent 重试
    安全，不重写 tool_calls）；capability_id 不存在 → 400。"""
    body, created = await traces_service.create_trace(sess, principal, payload)
    if not created:
        return JSONResponse(status_code=200, content=body.model_dump(mode="json"))
    return body


@router.get(
    "/traces",
    response_model=Page[TraceListItem],
    response_model_exclude_none=True,
    summary="轨迹摘要列表（过滤 + 游标分页）",
    responses=error_responses(*_READ_ERRORS),
)
async def list_traces(
    principal: Annotated[Principal, Depends(require_read())],
    sess: DbSession,
    agent_id: Annotated[str | None, Query(description="Agent 标识过滤")] = None,
    task_id: Annotated[str | None, Query(description="任务标识过滤")] = None,
    capability_id: Annotated[UUID | None, Query(description="能力过滤")] = None,
    since: Annotated[
        datetime | None, Query(description="起始时间下界（started_at >= since）")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=traces_service.MAX_LIMIT)] = (
        traces_service.DEFAULT_LIMIT
    ),
    cursor: Annotated[str | None, Query()] = None,
) -> Page[TraceListItem]:
    """游标分页（started_at DESC, trace_id DESC tiebreak）；列表为简投影
    （不含 tool_calls 与大 JSON 字段）。"""
    items, next_cursor = await traces_service.query_traces(
        sess,
        agent_id=agent_id,
        task_id=task_id,
        capability_id=capability_id,
        since=since,
        limit=limit,
        cursor=cursor,
    )
    return Page(items=items, next_cursor=next_cursor)


@router.get(
    "/traces/{trace_id}",
    response_model=TraceDetail,
    summary="完整轨迹（含 tool_calls 明细）",
    responses=error_responses(*_READ_ERRORS, ErrorCode.NOT_FOUND),
)
async def get_trace(
    trace_id: UUID,
    principal: Annotated[Principal, Depends(require_read())],
    sess: DbSession,
) -> TraceDetail:
    """完整轨迹含 tool_calls[]（seq 升序）；不存在/跨租户统一 404
    NOT_FOUND（不泄露存在性）。"""
    detail = await traces_service.get_trace(sess, trace_id)
    if detail is None:
        raise EdpError.not_found("轨迹不存在")
    return detail
