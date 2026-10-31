"""registry 路由（附录 B.2）：POST /objects（upsert）、GET /objects（组合键
查询）、GET /objects/{id}、GET /objects/{id}/history。

全部挂 tenant_scoped（认证 → 租户状态 → bind_tenant → RLS）；写 = API Key
scope write:registry 或 JWT registry:write，读 = readonly scope 或
registry:read（双轨判定见 dependencies.py）。
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import EdpError, ErrorCode, error_responses
from edp_api.core.pagination import Page
from edp_api.core.security.principal import Principal
from edp_api.modules.registry import service as registry_service
from edp_api.modules.registry.dependencies import require_read, require_write
from edp_api.modules.registry.schemas import (
    HistoryResponse,
    ObjectCreatedResponse,
    ObjectResponse,
    ObjectUpsertRequest,
)
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

router = APIRouter(
    prefix="/api/v1/objects",
    tags=["registry"],
    dependencies=[Depends(tenant_scoped)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "",
    response_model=ObjectCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="注册或更新业务对象（upsert）",
    responses=error_responses(
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.TENANT_SUSPENDED,
        ErrorCode.CONFLICT,
    ),
)
async def upsert_object(
    payload: ObjectUpsertRequest,
    response: Response,
    principal: Annotated[Principal, Depends(require_write("registry"))],
    sess: DbSession,
) -> ObjectCreatedResponse:
    """首次注册 201 / 重复注册 upsert 200（revision 递增）；409 附 current_revision。"""
    obj, created = await registry_service.upsert_object(sess, principal, payload)
    if not created:
        response.status_code = status.HTTP_200_OK
    return ObjectCreatedResponse(
        object_id=obj.object_id,
        revision=obj.revision,
        status=obj.status,
        created_at=obj.created_at,
    )


@router.get(
    "",
    response_model=Page[ObjectResponse],
    response_model_exclude_none=True,
    summary="组合键查询业务对象列表",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED, ErrorCode.FORBIDDEN, ErrorCode.TENANT_SUSPENDED
    ),
)
async def list_objects(
    principal: Annotated[Principal, Depends(require_read("registry"))],
    sess: DbSession,
    object_type: str | None = Query(default=None),
    source_system: str | None = Query(default=None),
    source_id: str | None = Query(default=None),
    owner_domain: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=registry_service.DEFAULT_LIMIT, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> Page[ObjectResponse]:
    """组合键/类型/域/状态过滤 + 游标分页（updated_at DESC, object_id tiebreak）。"""
    return await registry_service.query_objects(
        sess,
        object_type=object_type.strip().upper() if object_type else None,
        source_system=source_system,
        source_id=source_id,
        owner_domain=owner_domain,
        status=status_filter,
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/{object_id}",
    response_model=ObjectResponse,
    summary="查询单个业务对象",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.TENANT_SUSPENDED,
        ErrorCode.NOT_FOUND,
    ),
)
async def get_object(
    object_id: UUID,
    principal: Annotated[Principal, Depends(require_read("registry"))],
    sess: DbSession,
) -> ObjectResponse:
    """点查；跨租户/不存在统一 404 NOT_FOUND（不泄露存在性）。"""
    obj = await registry_service.get_object(sess, object_id)
    if obj is None:
        raise EdpError.not_found("对象不存在")
    return ObjectResponse.model_validate(obj)


@router.get(
    "/{object_id}/history",
    response_model=HistoryResponse,
    summary="查询业务对象版本轨迹",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.TENANT_SUSPENDED,
        ErrorCode.NOT_FOUND,
    ),
)
async def object_history(
    object_id: UUID,
    principal: Annotated[Principal, Depends(require_read("registry"))],
    sess: DbSession,
) -> HistoryResponse:
    """revision 变更轨迹（W1 源 event.outbox，W2 切审计日志）。"""
    obj = await registry_service.get_object(sess, object_id)
    if obj is None:
        raise EdpError.not_found("对象不存在")
    entries = await registry_service.object_history(sess, object_id)
    return HistoryResponse(object_id=object_id, revisions=entries)
