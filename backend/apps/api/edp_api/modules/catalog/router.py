"""catalog 路由（附录 B.7，EDP-011）：注册中心 systems/capabilities/skills。

- POST /systems：JWT ``registry:write`` / API Key ``write:registry`` → 201
  {system_id, name, status, created_at}；同名（uq_systems_name）→ 409；
- GET /systems：双轨读，status 过滤 + 游标分页；
- POST /capabilities：同写双轨 → 201 {capability_id, name, status,
  created_at}；同名（uq_capability_name）→ 409；
- GET /capabilities：domain/status 过滤列表（简投影）；GET
  /capabilities/{id}：详情含 input/output_schema，跨租户统一 404；
- PUT /capabilities/{id}：局部更新（仅传入字段：endpoint/input_schema/
  output_schema/status，RETIRED 下线）→ 200 完整能力对象；
- POST /skills：同写双轨 → 201；capability 不存在 → 400 VALIDATION_ERROR；
- GET /skills：capability_id/status 过滤列表。

router 级挂 tenant_scoped（认证 → 租户状态 → bind_tenant → RLS）；每条路由
单独挂鉴权依赖以取回 Principal。
"""

import asyncio
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import EdpError, ErrorCode, error_responses
from edp_api.core.pagination import Page
from edp_api.core.security.principal import Principal
from edp_api.modules.adapters_admin import service as adapters_admin_service
from edp_api.modules.catalog import service as catalog_service
from edp_api.modules.catalog.dependencies import require_read, require_write
from edp_api.modules.catalog.schemas import (
    CapabilityCreatedResponse,
    CapabilityCreateRequest,
    CapabilityListItem,
    CapabilityResponse,
    CapabilityUpdateRequest,
    SkillCreatedResponse,
    SkillCreateRequest,
    SkillListItem,
    SystemCreatedResponse,
    SystemCreateRequest,
    SystemListItem,
    SystemResponse,
    SystemTestResponse,
    SystemUpdateRequest,
)
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

router = APIRouter(
    prefix="/api/v1",
    tags=["catalog"],
    dependencies=[Depends(tenant_scoped)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]

_READ_ERRORS = (
    ErrorCode.UNAUTHENTICATED,
    ErrorCode.FORBIDDEN,
    ErrorCode.TENANT_SUSPENDED,
)
_WRITE_ERRORS = (*_READ_ERRORS, ErrorCode.VALIDATION_ERROR, ErrorCode.CONFLICT)


# ---- systems ----


@router.post(
    "/systems",
    response_model=SystemCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="注册系统（源/消费方连接配置）",
    responses=error_responses(*_WRITE_ERRORS),
)
async def create_system(
    payload: SystemCreateRequest,
    principal: Annotated[Principal, Depends(require_write())],
    sess: DbSession,
) -> SystemCreatedResponse:
    """注册系统 → 201；同名（本租户 uq_systems_name）→ 409 CONFLICT。"""
    system = await catalog_service.create_system(sess, principal, payload)
    await adapters_admin_service.refresh_dynamic(sess, principal.tenant_id)
    return SystemCreatedResponse(
        system_id=system.system_id,
        name=system.name,
        status=system.status,
        created_at=system.created_at,
    )


@router.get(
    "/systems",
    response_model=Page[SystemListItem],
    response_model_exclude_none=True,
    summary="系统列表（status 过滤）",
    responses=error_responses(*_READ_ERRORS),
)
async def list_systems(
    principal: Annotated[Principal, Depends(require_read())],
    sess: DbSession,
    status_filter: Annotated[
        Literal["ACTIVE", "DISABLED"] | None,
        Query(alias="status", description="系统状态过滤"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=catalog_service.MAX_LIMIT)] = (
        catalog_service.DEFAULT_LIMIT
    ),
    cursor: Annotated[str | None, Query()] = None,
) -> Page[SystemListItem]:
    """游标分页（created_at DESC, system_id tiebreak）；列表为简投影。"""
    items, next_cursor = await catalog_service.query_systems(
        sess, status=status_filter, limit=limit, cursor=cursor
    )
    return Page(items=items, next_cursor=next_cursor)


@router.get(
    "/systems/{system_id}",
    response_model=SystemResponse,
    summary="系统详情（含驱动配置，管理页编辑用）",
    responses=error_responses(*_READ_ERRORS, ErrorCode.NOT_FOUND),
)
async def get_system(
    system_id: UUID,
    principal: Annotated[Principal, Depends(require_read())],
    sess: DbSession,
) -> SystemResponse:
    """RLS 会话：跨租户行不可见 → 404（与不存在同义）。"""
    system = await catalog_service.get_system(sess, system_id)
    if system is None:
        raise EdpError.not_found("系统不存在")
    return SystemResponse.model_validate(system)


@router.put(
    "/systems/{system_id}",
    response_model=SystemResponse,
    summary="更新系统（局部更新：type/endpoint/auth/adapter_config/status）",
    responses=error_responses(*_WRITE_ERRORS, ErrorCode.NOT_FOUND),
)
async def update_system(
    system_id: UUID,
    payload: SystemUpdateRequest,
    principal: Annotated[Principal, Depends(require_write())],
    sess: DbSession,
) -> SystemResponse:
    """adapter_config 变更同步 adapter_mode（real/mock）。"""
    system = await catalog_service.get_system(sess, system_id)
    if system is None:
        raise EdpError.not_found("系统不存在")
    updated = await catalog_service.update_system(sess, principal, system, payload)
    await adapters_admin_service.refresh_dynamic(sess, principal.tenant_id)
    return SystemResponse.model_validate(updated)


@router.delete(
    "/systems/{system_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除系统（含其驱动配置）",
    responses=error_responses(*_WRITE_ERRORS, ErrorCode.NOT_FOUND),
)
async def delete_system(
    system_id: UUID,
    principal: Annotated[Principal, Depends(require_write())],
    sess: DbSession,
) -> None:
    """删除注册行（适配器注册表随事务收尾重载，见 adapters_admin）。"""
    system = await catalog_service.get_system(sess, system_id)
    if system is None:
        raise EdpError.not_found("系统不存在")
    await catalog_service.delete_system(sess, system)
    await adapters_admin_service.refresh_dynamic(sess, principal.tenant_id)


@router.post(
    "/systems/{system_id}/test",
    response_model=SystemTestResponse,
    summary="测试连接（驱动配置装配 + 探活，只读）",
    responses=error_responses(*_WRITE_ERRORS, ErrorCode.NOT_FOUND),
)
async def test_system(
    system_id: UUID,
    principal: Annotated[Principal, Depends(require_write())],
    sess: DbSession,
) -> SystemTestResponse:
    """adapter_config 装配为 DbPullAdapter 后探活（SELECT 1，超时 5s）；
    无驱动配置 → 400 VALIDATION_ERROR。"""
    system = await catalog_service.get_system(sess, system_id)
    if system is None:
        raise EdpError.not_found("系统不存在")
    if not system.adapter_config:
        raise EdpError.validation_error("该系统无驱动配置（adapter_config）")
    adapter = adapters_admin_service.build_adapter_from_config(
        system.name, system.adapter_config
    )
    if adapter is None:
        raise EdpError.validation_error("adapter_config 非法：需 dsn 与 tables 列表")
    # 真实适配器 health_check 内跑 asyncio.run（线程契约）——to_thread 包裹
    health = await asyncio.to_thread(adapter.health_check)
    return SystemTestResponse(ok=health.ok, detail=health.detail)


# ---- capabilities ----


@router.post(
    "/capabilities",
    response_model=CapabilityCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="注册能力（Agent 中枢能力存储）",
    responses=error_responses(*_WRITE_ERRORS),
)
async def create_capability(
    payload: CapabilityCreateRequest,
    principal: Annotated[Principal, Depends(require_write())],
    sess: DbSession,
) -> CapabilityCreatedResponse:
    """注册能力 → 201（status 落默认 ACTIVE）；同名 → 409 CONFLICT。"""
    capability = await catalog_service.create_capability(sess, principal, payload)
    return CapabilityCreatedResponse(
        capability_id=capability.capability_id,
        name=capability.name,
        status=capability.status,
        created_at=capability.created_at,
    )


@router.get(
    "/capabilities",
    response_model=Page[CapabilityListItem],
    response_model_exclude_none=True,
    summary="能力列表（domain/status 过滤）",
    responses=error_responses(*_READ_ERRORS),
)
async def list_capabilities(
    principal: Annotated[Principal, Depends(require_read())],
    sess: DbSession,
    domain: Annotated[str | None, Query(description="业务域过滤")] = None,
    status_filter: Annotated[
        Literal["DRAFT", "ACTIVE", "RETIRED"] | None,
        Query(alias="status", description="能力状态过滤"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=catalog_service.MAX_LIMIT)] = (
        catalog_service.DEFAULT_LIMIT
    ),
    cursor: Annotated[str | None, Query()] = None,
) -> Page[CapabilityListItem]:
    """游标分页（created_at DESC, capability_id tiebreak）；简投影不含 schema。"""
    items, next_cursor = await catalog_service.query_capabilities(
        sess, domain=domain, status=status_filter, limit=limit, cursor=cursor
    )
    return Page(items=items, next_cursor=next_cursor)


@router.get(
    "/capabilities/{capability_id}",
    response_model=CapabilityResponse,
    summary="能力详情（含 input/output_schema）",
    responses=error_responses(*_READ_ERRORS, ErrorCode.NOT_FOUND),
)
async def get_capability(
    capability_id: UUID,
    principal: Annotated[Principal, Depends(require_read())],
    sess: DbSession,
) -> CapabilityResponse:
    """能力详情；不存在/跨租户统一 404 NOT_FOUND（不泄露存在性）。"""
    capability = await catalog_service.get_capability(sess, capability_id)
    if capability is None:
        raise EdpError.not_found("能力不存在")
    return CapabilityResponse.model_validate(capability)


@router.put(
    "/capabilities/{capability_id}",
    response_model=CapabilityResponse,
    summary="更新能力（局部更新：endpoint/schema/status）",
    responses=error_responses(
        *_READ_ERRORS,
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.NOT_FOUND,
    ),
)
async def update_capability(
    capability_id: UUID,
    payload: CapabilityUpdateRequest,
    principal: Annotated[Principal, Depends(require_write())],
    sess: DbSession,
) -> CapabilityResponse:
    """仅覆盖传入字段（endpoint/input_schema/output_schema/status，RETIRED
    下线）→ 200 完整能力对象；不存在/跨租户统一 404。"""
    capability = await catalog_service.update_capability(
        sess, principal, capability_id, payload
    )
    if capability is None:
        raise EdpError.not_found("能力不存在")
    return CapabilityResponse.model_validate(capability)


# ---- skills ----


@router.post(
    "/skills",
    response_model=SkillCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="注册技能（Prompt/模型版本）",
    responses=error_responses(*_WRITE_ERRORS),
)
async def create_skill(
    payload: SkillCreateRequest,
    principal: Annotated[Principal, Depends(require_write())],
    sess: DbSession,
) -> SkillCreatedResponse:
    """注册技能 → 201；capability_id 不存在（含跨租户）→ 400。"""
    skill = await catalog_service.create_skill(sess, principal, payload)
    return SkillCreatedResponse(
        skill_id=skill.skill_id,
        capability_id=skill.capability_id,
        status=skill.status,
        created_at=skill.created_at,
    )


@router.get(
    "/skills",
    response_model=Page[SkillListItem],
    response_model_exclude_none=True,
    summary="技能列表（capability_id/status 过滤）",
    responses=error_responses(*_READ_ERRORS),
)
async def list_skills(
    principal: Annotated[Principal, Depends(require_read())],
    sess: DbSession,
    capability_id: Annotated[
        UUID | None, Query(description="所属能力过滤")
    ] = None,
    status_filter: Annotated[
        Literal["DRAFT", "ACTIVE", "RETIRED"] | None,
        Query(alias="status", description="技能状态过滤"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=catalog_service.MAX_LIMIT)] = (
        catalog_service.DEFAULT_LIMIT
    ),
    cursor: Annotated[str | None, Query()] = None,
) -> Page[SkillListItem]:
    """游标分页（created_at DESC, skill_id tiebreak）；列表为简投影。"""
    items, next_cursor = await catalog_service.query_skills(
        sess,
        capability_id=capability_id,
        status=status_filter,
        limit=limit,
        cursor=cursor,
    )
    return Page(items=items, next_cursor=next_cursor)
