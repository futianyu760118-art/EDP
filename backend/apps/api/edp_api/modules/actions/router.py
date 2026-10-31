"""actions 路由（附录 B.5，EDP-020）：行动任务状态机四端点。

- POST /actions：HUMAN ``action:execute`` / SERVICE ``write:action`` → 201；
- GET /actions：双轨读（HUMAN ``action:read`` / SERVICE ``readonly``）游标
  分页，简投影附 allowed_to；
- GET /actions/{action_id}：完整对象 + allowed_to；跨租户统一 404；
- PATCH /actions/{action_id}/status：写轨同 POST；非法转移 422（extra
  含 allowed_to）、from 过期 409、Human-Only 边非 HUMAN 403
  GUARD_POLICY_DENIED（GUARD_DENIED 审计由 service 落）。

router 级挂 tenant_scoped（认证 → 租户状态 → bind_tenant → RLS）；每条路由
单独挂鉴权依赖以取回 Principal。
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import EdpError, ErrorCode, error_responses
from edp_api.core.pagination import Page
from edp_api.core.security.principal import Principal
from edp_api.modules.actions import service as actions_service
from edp_api.modules.actions.dependencies import (
    require_action_execute,
    require_action_read,
)
from edp_api.modules.actions.schemas import (
    ActionCreatedResponse,
    ActionCreateRequest,
    ActionDetailResponse,
    ActionListItem,
    ActionTransitionRequest,
    ActionTransitionResponse,
    TransitionItem,
)
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

router = APIRouter(
    prefix="/api/v1/actions",
    tags=["actions"],
    dependencies=[Depends(tenant_scoped)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]

_READ_ERRORS = (
    ErrorCode.UNAUTHENTICATED,
    ErrorCode.FORBIDDEN,
    ErrorCode.TENANT_SUSPENDED,
)
_WRITE_ERRORS = (*_READ_ERRORS, ErrorCode.VALIDATION_ERROR)
_TRANSITION_ERRORS = (
    *_WRITE_ERRORS,
    ErrorCode.NOT_FOUND,
    ErrorCode.CONFLICT,
    ErrorCode.INVALID_TRANSITION,
    ErrorCode.GUARD_POLICY_DENIED,
)


@router.post(
    "",
    response_model=ActionCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建行动任务（→ PROPOSED）",
    responses=error_responses(*_WRITE_ERRORS),
)
async def create_action(
    payload: ActionCreateRequest,
    principal: Annotated[Principal, Depends(require_action_execute())],
    sess: DbSession,
) -> ActionCreatedResponse:
    """创建行动；case_id 提供但不存在 → 400 VALIDATION_ERROR。"""
    action = await actions_service.create_action(sess, principal, payload)
    return ActionCreatedResponse(
        action_id=action.action_id,
        status=action.status,
        created_at=action.created_at,
    )


@router.get(
    "",
    response_model=Page[ActionListItem],
    response_model_exclude_none=True,
    summary="行动列表（status/owner/case_id 过滤，简投影附 allowed_to）",
    responses=error_responses(*_READ_ERRORS),
)
async def list_actions(
    principal: Annotated[Principal, Depends(require_action_read())],
    sess: DbSession,
    status_filter: Annotated[
        Literal[
            "PROPOSED",
            "ASSIGNED",
            "ACCEPTED",
            "APPROVED",
            "EXECUTING",
            "COMPLETED",
            "VERIFIED",
            "CANCELLED",
            "REJECTED",
        ]
        | None,
        Query(alias="status", description="行动状态过滤"),
    ] = None,
    owner: Annotated[str | None, Query(max_length=128)] = None,
    case_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=actions_service.MAX_LIMIT)] = (
        actions_service.DEFAULT_LIMIT
    ),
    cursor: Annotated[str | None, Query()] = None,
) -> Page[ActionListItem]:
    """游标分页（created_at DESC, action_id DESC tiebreak）；简投影。"""
    return await actions_service.query_actions(
        sess,
        status=status_filter,
        owner=owner,
        case_id=case_id,
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/{action_id}",
    response_model=ActionDetailResponse,
    summary="行动详情（完整对象 + allowed_to）",
    responses=error_responses(*_READ_ERRORS, ErrorCode.NOT_FOUND),
)
async def get_action(
    action_id: UUID,
    principal: Annotated[Principal, Depends(require_action_read())],
    sess: DbSession,
) -> ActionDetailResponse:
    """详情；不存在/跨租户统一 404 NOT_FOUND（不泄露存在性）。"""
    action = await actions_service.get_action(sess, action_id)
    if action is None:
        raise EdpError.not_found("行动任务不存在")
    detail = ActionDetailResponse.model_validate(action)
    detail.allowed_to = [
        TransitionItem(**item) for item in actions_service.allowed_to(action.status)
    ]
    return detail


@router.patch(
    "/{action_id}/status",
    response_model=ActionTransitionResponse,
    summary="状态机转移（乐观锁 from_status；Human-Only 边见 TRANSITIONS）",
    responses=error_responses(*_TRANSITION_ERRORS),
)
async def transition_action(
    action_id: UUID,
    payload: ActionTransitionRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_action_execute())],
    sess: DbSession,
) -> ActionTransitionResponse:
    """转移；非法 422（extra.allowed_to）/ from 过期 409 / Human-Only 边
    非 HUMAN 403 GUARD_POLICY_DENIED（GUARD_DENIED 审计由 service 落）。"""
    action = await actions_service.transition_action(
        sess, principal, action_id, payload, path=request.url.path
    )
    if action is None:
        raise EdpError.not_found("行动任务不存在")
    return ActionTransitionResponse(
        action_id=action.action_id,
        status=action.status,
        updated_at=action.updated_at,
    )
