"""events 路由（附录 B.3）：POST /events/batch（Idempotency-Key 必填）、
GET /events（过滤 + 游标分页）、GET /events/{id}（点查）。

全部挂 tenant_scoped（认证 → 租户状态 → bind_tenant → RLS）；写 = API Key
scope write:event 或 JWT event:write，读 = readonly scope 或 event:read
（双轨判定见 dependencies.py）。
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import EdpError, ErrorCode, error_responses
from edp_api.core.pagination import Page
from edp_api.core.security.principal import Principal
from edp_api.modules.events import service as events_service
from edp_api.modules.events.dependencies import require_read, require_write
from edp_api.modules.events.schemas import (
    BatchRequest,
    BatchResponse,
    EventResponse,
)
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

router = APIRouter(
    prefix="/api/v1/events",
    tags=["events"],
    dependencies=[Depends(tenant_scoped)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/batch",
    response_model=BatchResponse,
    response_model_exclude_none=True,
    summary="批量事件入库（幂等重放）",
    responses=error_responses(
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.TENANT_SUSPENDED,
    ),
)
async def batch_ingest(
    payload: BatchRequest,
    principal: Annotated[Principal, Depends(require_write("event"))],
    sess: DbSession,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description=(
                "幂等键（必填）：同租户同 Key 重放返回存档响应并置 deduplicated=true；"
                "缺失返回 400"
            ),
        ),
    ] = None,
) -> BatchResponse:
    """批量入库（200）；同 Idempotency-Key 重放返回存档响应 + deduplicated=true；
    缺失 Idempotency-Key → 400 VALIDATION_ERROR。"""
    key = (idempotency_key or "").strip()
    if not key:
        raise EdpError.validation_error("缺少 Idempotency-Key 请求头")
    return await events_service.ingest_batch(sess, principal, key, payload.events)


@router.get(
    "",
    response_model=Page[EventResponse],
    summary="查询事件列表（过滤 + 游标分页）",
    responses=error_responses(
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.TENANT_SUSPENDED,
    ),
)
async def list_events(
    principal: Annotated[Principal, Depends(require_read("event"))],
    sess: DbSession,
    object_id: Annotated[UUID | None, Query()] = None,
    event_type: Annotated[str | None, Query()] = None,
    event_type_prefix: Annotated[
        str | None,
        Query(description="事件类型前缀过滤（LIKE prefix%；与 event_type 互斥）"),
    ] = None,
    risk_level: Annotated[Literal["P0", "P1", "P2", "P3"] | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = events_service.DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[EventResponse]:
    """过滤（object_id/event_type 精确/event_type_prefix 前缀 LIKE/risk_level/
    since/until 闭区间）+ 游标分页（occurred_at DESC, event_id tiebreak）；
    event_type 与 event_type_prefix 同传 → 400（互斥），空前缀串按 None。"""
    prefix = (event_type_prefix or "").strip() or None
    if event_type and prefix:
        raise EdpError.validation_error(
            "event_type 与 event_type_prefix 互斥，同传请仅保留其一"
        )
    return await events_service.query_events(
        sess,
        object_id=object_id,
        event_type=event_type,
        event_type_prefix=prefix,
        risk_level=risk_level,
        since=since,
        until=until,
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/{event_id}",
    response_model=EventResponse,
    summary="查询单个事件",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.TENANT_SUSPENDED,
        ErrorCode.NOT_FOUND,
    ),
)
async def get_event(
    event_id: UUID,
    principal: Annotated[Principal, Depends(require_read("event"))],
    sess: DbSession,
) -> EventResponse:
    """点查（含 delivery_status/object_source_id 派生字段，与列表同口径）；
    跨租户/不存在统一 404 NOT_FOUND（不泄露存在性）。"""
    response = await events_service.get_event_response(sess, event_id)
    if response is None:
        raise EdpError.not_found("事件不存在")
    return response
