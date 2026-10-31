"""decisions 路由（附录 B.5，EDP-018 最小版 + W4 EDP-028 闭环聚合）：
案例创建/列表/详情 + 决策记录。

- POST /cases：SERVICE scope write:decision / HUMAN decision:decide → 201；
  source_id 已建案例 → 409 CONFLICT（uq_cases_tenant_source，W4）；
- GET /cases：双轨读（HUMAN decision:read / SERVICE readonly）游标分页；
- GET /cases/{case_id}：详情（evidence_refs + decisions + W4 闭环聚合可选
  字段 event/steps/actions/evidence_chain——`response_model_exclude_none`
  下按需出现）；跨租户统一 404；
- POST /cases/{case_id}/records：**Human-Only**（非 HUMAN → 403
  GUARD_POLICY_DENIED + GUARD_DENIED 审计；HUMAN 需 decision:decide）。

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
from edp_api.modules.decisions import service as decisions_service
from edp_api.modules.decisions.dependencies import (
    require_case_create,
    require_decision_decide,
    require_decision_read,
)
from edp_api.modules.decisions.schemas import (
    CaseCreatedResponse,
    CaseCreateRequest,
    CaseDetailResponse,
    CaseListItem,
    DecisionCreatedResponse,
    DecisionCreateRequest,
)
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

router = APIRouter(
    prefix="/api/v1/decisions",
    tags=["decisions"],
    dependencies=[Depends(tenant_scoped)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]

_READ_ERRORS = (
    ErrorCode.UNAUTHENTICATED,
    ErrorCode.FORBIDDEN,
    ErrorCode.TENANT_SUSPENDED,
)
_WRITE_ERRORS = (*_READ_ERRORS, ErrorCode.VALIDATION_ERROR)


@router.post(
    "/cases",
    response_model=CaseCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建决策案例（case_no 日序号 + 证据链）",
    responses=error_responses(*_WRITE_ERRORS, ErrorCode.CONFLICT),
)
async def create_case(
    payload: CaseCreateRequest,
    principal: Annotated[Principal, Depends(require_case_create())],
    sess: DbSession,
) -> CaseCreatedResponse:
    """创建案例；source_id 事件/evidence_ids 证据不存在 → 400
    VALIDATION_ERROR；source_id 已建案例 → 409 CONFLICT（0012 唯一索引）。"""
    case = await decisions_service.create_case(sess, principal, payload)
    return CaseCreatedResponse(
        case_id=case.case_id,
        case_no=case.case_no,
        status=case.status,
        created_at=case.created_at,
    )


@router.get(
    "/cases",
    response_model=Page[CaseListItem],
    response_model_exclude_none=True,
    summary="决策案例列表（status/risk_level 过滤）",
    responses=error_responses(*_READ_ERRORS),
)
async def list_cases(
    principal: Annotated[Principal, Depends(require_decision_read())],
    sess: DbSession,
    status_filter: Annotated[
        Literal["OPEN", "DECIDED", "CANCELLED"] | None,
        Query(alias="status", description="案例状态过滤"),
    ] = None,
    risk_level: Annotated[
        Literal["P0", "P1", "P2", "P3"] | None, Query(description="风险级别过滤")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=decisions_service.MAX_LIMIT)] = (
        decisions_service.DEFAULT_LIMIT
    ),
    cursor: Annotated[str | None, Query()] = None,
) -> Page[CaseListItem]:
    """游标分页（created_at DESC, case_id tiebreak）；列表为简投影。"""
    return await decisions_service.query_cases(
        sess,
        status=status_filter,
        risk_level=risk_level,
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/cases/{case_id}",
    response_model=CaseDetailResponse,
    response_model_exclude_none=True,
    summary="决策案例详情（闭环聚合：证据引用/决策记录/event/steps/actions/证据链）",
    responses=error_responses(*_READ_ERRORS, ErrorCode.NOT_FOUND),
)
async def get_case(
    case_id: UUID,
    principal: Annotated[Principal, Depends(require_decision_read())],
    sess: DbSession,
) -> CaseDetailResponse:
    """详情（B.5 + W4 EDP-028 闭环聚合）：event/steps/actions/evidence_chain
    为可选字段（无源事件等场景缺省）；不存在/跨租户统一 404 NOT_FOUND
    （不泄露存在性）。"""
    detail = await decisions_service.get_case_detail(sess, case_id)
    if detail is None:
        raise EdpError.not_found("决策案例不存在")
    return detail


@router.post(
    "/cases/{case_id}/records",
    response_model=DecisionCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="提交决策记录（Human-Only）",
    responses=error_responses(
        *_WRITE_ERRORS,
        ErrorCode.GUARD_POLICY_DENIED,
        ErrorCode.NOT_FOUND,
        ErrorCode.CONFLICT,
    ),
)
async def submit_record(
    case_id: UUID,
    payload: DecisionCreateRequest,
    principal: Annotated[Principal, Depends(require_decision_decide())],
    sess: DbSession,
) -> DecisionCreatedResponse:
    """人工提交决策 → case 置 DECIDED；非 HUMAN → 403 GUARD_POLICY_DENIED。"""
    result = await decisions_service.submit_record(sess, principal, case_id, payload)
    if result is None:
        raise EdpError.not_found("决策案例不存在")
    record, case = result
    return DecisionCreatedResponse(
        decision_id=record.decision_id,
        case_id=case.case_id,
        decision_time=record.decision_time,
        case_status=case.status,
    )
