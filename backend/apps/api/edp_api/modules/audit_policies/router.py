"""audit_policies 路由（EDP-032 最小版）：/admin/audit-policies CRUD。

- POST ````（audit:policy_write）→ 201 完整对象；重名 409 CONFLICT；
- GET ``?status=``（audit:policy_read）→ 游标分页（created_at DESC,
  policy_id DESC tiebreak）；
- PATCH ``/{policy_id}``（audit:policy_write）→ 200 完整对象；局部更新
  （name 不可改）；不存在/跨租户统一 404（不泄露存在性）；
- DELETE ``/{policy_id}``（audit:policy_write）→ 204。

router 级挂 tenant_scoped（认证 → 租户状态 → bind_tenant → RLS）；策略
管理仅 JWT 轨道（鉴权口径见 dependencies 模块 docstring）。
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import EdpError, ErrorCode, error_responses
from edp_api.core.pagination import Page
from edp_api.core.security.principal import Principal
from edp_api.modules.audit_policies import service as audit_policies_service
from edp_api.modules.audit_policies.dependencies import (
    require_policy_read,
    require_policy_write,
)
from edp_api.modules.audit_policies.schemas import (
    PolicyCreateRequest,
    PolicyItem,
    PolicyUpdateRequest,
)
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

router = APIRouter(
    prefix="/api/v1/admin/audit-policies",
    tags=["audit-policies"],
    dependencies=[Depends(tenant_scoped)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]

_READ_ERRORS = (
    ErrorCode.UNAUTHENTICATED,
    ErrorCode.FORBIDDEN,
    ErrorCode.TENANT_SUSPENDED,
)
_WRITE_ERRORS = (*_READ_ERRORS, ErrorCode.CONFLICT)
_TARGET_ERRORS = (*_WRITE_ERRORS, ErrorCode.NOT_FOUND)


@router.post(
    "",
    response_model=PolicyItem,
    status_code=status.HTTP_201_CREATED,
    summary="创建审计策略（三维匹配数组缺省 [] = 通配）",
    responses=error_responses(*_WRITE_ERRORS),
)
async def create_policy(
    payload: PolicyCreateRequest,
    principal: Annotated[Principal, Depends(require_policy_write())],
    sess: DbSession,
) -> PolicyItem:
    """创建策略 → 201（status=ACTIVE）；租户内重名 → 409 CONFLICT。"""
    policy = await audit_policies_service.create_policy(sess, principal, payload)
    return PolicyItem.model_validate(policy)


@router.get(
    "",
    response_model=Page[PolicyItem],
    response_model_exclude_none=True,
    summary="审计策略列表（status 过滤 + 游标分页）",
    responses=error_responses(*_READ_ERRORS),
)
async def list_policies(
    principal: Annotated[Principal, Depends(require_policy_read())],
    sess: DbSession,
    status_filter: Annotated[
        Literal["ACTIVE", "DISABLED"] | None,
        Query(alias="status", description="策略状态过滤"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=audit_policies_service.MAX_LIMIT)] = (
        audit_policies_service.DEFAULT_LIMIT
    ),
    cursor: Annotated[str | None, Query()] = None,
) -> Page[PolicyItem]:
    """游标分页（created_at DESC, policy_id DESC tiebreak）。"""
    return await audit_policies_service.query_policies(
        sess, status=status_filter, limit=limit, cursor=cursor
    )


@router.patch(
    "/{policy_id}",
    response_model=PolicyItem,
    summary="局部更新审计策略（name 不可改；启停经 status）",
    responses=error_responses(*_TARGET_ERRORS),
)
async def update_policy(
    policy_id: UUID,
    payload: PolicyUpdateRequest,
    principal: Annotated[Principal, Depends(require_policy_write())],
    sess: DbSession,
) -> PolicyItem:
    """局部更新 → 200 完整对象；不存在/跨租户统一 404。"""
    policy = await audit_policies_service.update_policy(
        sess, principal, policy_id, payload
    )
    if policy is None:
        raise EdpError.not_found("审计策略不存在")
    return PolicyItem.model_validate(policy)


@router.delete(
    "/{policy_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除审计策略",
    responses=error_responses(*_TARGET_ERRORS),
)
async def delete_policy(
    policy_id: UUID,
    principal: Annotated[Principal, Depends(require_policy_write())],
    sess: DbSession,
) -> None:
    """删除 → 204；不存在/跨租户统一 404。"""
    if not await audit_policies_service.delete_policy(sess, policy_id):
        raise EdpError.not_found("审计策略不存在")
