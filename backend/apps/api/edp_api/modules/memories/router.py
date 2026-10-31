"""memories 路由（附录 B.11，EDP-014）：候选创建 / 过滤查询 / 人工评审。

- POST /memories：API Key ``write:memory``（HUMAN 无 memory:write → 403）
  → 201 {memory_id, status: CANDIDATE, created_at}；capability_id 不存在
  （含跨租户）→ 400 VALIDATION_ERROR；
- GET /memories：双轨读（JWT ``memory:read`` / readonly），status/
  capability_id 过滤 + 游标分页；
- PATCH /memories/{memory_id}/review：**Human-Only**——非 HUMAN 落
  GUARD_DENIED 审计后 403 GUARD_POLICY_DENIED；HUMAN 需 ``memory:review``；
  已评审 → 409 CONFLICT；不存在/跨租户统一 404。

router 级挂 tenant_scoped（认证 → 租户状态 → bind_tenant → RLS）；每条路由
单独挂鉴权依赖以取回 Principal。
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import EdpError, ErrorCode, error_responses
from edp_api.core.pagination import Page
from edp_api.core.security.principal import Principal
from edp_api.modules.memories import service as memories_service
from edp_api.modules.memories.dependencies import (
    require_memory_read,
    require_memory_review,
    require_memory_write,
)
from edp_api.modules.memories.schemas import (
    MemoryCreatedResponse,
    MemoryCreateRequest,
    MemoryListItem,
    MemoryReviewRequest,
    MemoryReviewResponse,
)
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

router = APIRouter(
    prefix="/api/v1/memories",
    tags=["memories"],
    dependencies=[Depends(tenant_scoped)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]

_READ_ERRORS = (
    ErrorCode.UNAUTHENTICATED,
    ErrorCode.FORBIDDEN,
    ErrorCode.TENANT_SUSPENDED,
)


@router.post(
    "",
    response_model=MemoryCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建记忆候选（Agent 中枢）",
    responses=error_responses(
        *_READ_ERRORS, ErrorCode.VALIDATION_ERROR
    ),
)
async def create_memory(
    payload: MemoryCreateRequest,
    principal: Annotated[Principal, Depends(require_memory_write())],
    sess: DbSession,
) -> MemoryCreatedResponse:
    """创建候选 → 201（status=CANDIDATE）；capability 不存在 → 400。"""
    memory = await memories_service.create_memory(sess, principal, payload)
    return MemoryCreatedResponse(
        memory_id=memory.memory_id,
        status=memory.status,
        created_at=memory.created_at,
    )


@router.get(
    "",
    response_model=Page[MemoryListItem],
    response_model_exclude_none=True,
    summary="记忆列表（status/capability_id 过滤）",
    responses=error_responses(*_READ_ERRORS),
)
async def list_memories(
    principal: Annotated[Principal, Depends(require_memory_read())],
    sess: DbSession,
    status_filter: Annotated[
        Literal["CANDIDATE", "APPROVED", "REJECTED"] | None,
        Query(alias="status", description="评审状态过滤"),
    ] = None,
    capability_id: Annotated[
        UUID | None, Query(description="所属能力过滤")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=memories_service.MAX_LIMIT)] = (
        memories_service.DEFAULT_LIMIT
    ),
    cursor: Annotated[str | None, Query()] = None,
) -> Page[MemoryListItem]:
    """游标分页（created_at DESC, memory_id tiebreak）。"""
    items, next_cursor = await memories_service.query_memories(
        sess,
        status=status_filter,
        capability_id=capability_id,
        limit=limit,
        cursor=cursor,
    )
    return Page(items=items, next_cursor=next_cursor)


@router.patch(
    "/{memory_id}/review",
    response_model=MemoryReviewResponse,
    summary="人工评审记忆候选（Human-Only）",
    responses=error_responses(
        *_READ_ERRORS,
        ErrorCode.GUARD_POLICY_DENIED,
        ErrorCode.NOT_FOUND,
        ErrorCode.CONFLICT,
    ),
)
async def review_memory(
    memory_id: UUID,
    payload: MemoryReviewRequest,
    principal: Annotated[Principal, Depends(require_memory_review())],
    sess: DbSession,
) -> MemoryReviewResponse:
    """Human-Only 评审 → 200；已评审 → 409；不存在/跨租户统一 404。"""
    memory = await memories_service.review_memory(
        sess, principal, memory_id, payload
    )
    if memory is None:
        raise EdpError.not_found("记忆不存在")
    return MemoryReviewResponse(
        memory_id=memory.memory_id,
        status=memory.status,
        reviewed_by=memory.reviewed_by or principal.id,
        reviewed_at=memory.reviewed_at,
    )
