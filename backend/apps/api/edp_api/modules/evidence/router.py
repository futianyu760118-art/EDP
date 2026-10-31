"""evidence 路由（附录 B.4）：POST /evidence（创建）、GET /evidence（逆向
追溯列表）、GET /evidence/{id}（详情）、GET /evidence/{id}/verify（校验），
及 POST /admin/evidence/reindex（W3-04 收口：证据重索引）。

全部挂 tenant_scoped（认证 → 租户状态 → bind_tenant → RLS）；写 = API Key
scope write:evidence 或 JWT evidence:write，读 = readonly scope 或
evidence:read（双轨判定见 dependencies.py）；跨租户/不存在统一 404。

reindex 权限**复用 quality:run**（require_permission 同 T3/T4 口径，不设
SERVICE scope 轨道——依据与手法见 dependencies.py docstring）：202 后任务
进度/终态经 GET /admin/quality/tasks/{task_id} 轮询（quality:read，复用
T4 任务轨道端点——不新开查询端点）。
"""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import EdpError, ErrorCode, error_responses
from edp_api.core.pagination import Page
from edp_api.core.security.principal import Principal
from edp_api.modules.evidence import service as evidence_service
from edp_api.modules.evidence.dependencies import (
    require_read,
    require_reindex_run,
    require_write,
)
from edp_api.modules.evidence.schemas import (
    EvidenceCreatedResponse,
    EvidenceCreateRequest,
    EvidenceLinkItem,
    EvidenceListItem,
    EvidenceResponse,
    ReindexAccepted,
    ReindexRequest,
    VerifyResponse,
)
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

router = APIRouter(
    prefix="/api/v1/evidence",
    tags=["evidence"],
    dependencies=[Depends(tenant_scoped)],
)

admin_router = APIRouter(
    prefix="/api/v1/admin/evidence",
    tags=["evidence"],
    dependencies=[Depends(tenant_scoped)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "",
    response_model=EvidenceCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建证据记录（checksum 服务端计算）",
    responses=error_responses(
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.TENANT_SUSPENDED,
    ),
)
async def create_evidence(
    payload: EvidenceCreateRequest,
    principal: Annotated[Principal, Depends(require_write("evidence"))],
    sess: DbSession,
) -> EvidenceCreatedResponse:
    """快照落证据 + links 逐条入库；checksum = canonical sha256（服务端算）。"""
    record = await evidence_service.create_record(sess, principal, payload)
    return EvidenceCreatedResponse(
        evidence_id=record.evidence_id,
        checksum=record.checksum,
        captured_at=record.captured_at,
    )


@router.get(
    "",
    response_model=Page[EvidenceListItem],
    response_model_exclude_none=True,
    summary="逆向追溯查询证据列表",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED, ErrorCode.FORBIDDEN, ErrorCode.TENANT_SUSPENDED
    ),
)
async def list_evidence(
    principal: Annotated[Principal, Depends(require_read("evidence"))],
    sess: DbSession,
    ref_type: Annotated[
        Literal["CASE", "DECISION", "ACTION", "RESULT", "EVENT", "TRACE"] | None,
        Query(description="与 ref_id 成对生效（links 逆向追溯）"),
    ] = None,
    ref_id: Annotated[UUID | None, Query()] = None,
    object_id: Annotated[UUID | None, Query()] = None,
    q: Annotated[
        str | None,
        Query(
            max_length=255,
            description="模糊搜索：source_record_id/source_system ILIKE",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = evidence_service.DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[EvidenceListItem]:
    """ref_type+ref_id（links 子查询）/ object_id 过滤 + ``q`` 模糊搜索 + 游标
    分页（captured_at DESC, evidence_id tiebreak）；列表为简投影（不含
    snapshot/links，详情经 GET /{id}）。"""
    return await evidence_service.query_records(
        sess,
        ref_type=ref_type,
        ref_id=ref_id,
        object_id=object_id,
        q=q,
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/{evidence_id}",
    response_model=EvidenceResponse,
    summary="查询单个证据（含 snapshot 与 links）",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.TENANT_SUSPENDED,
        ErrorCode.NOT_FOUND,
    ),
)
async def get_evidence(
    evidence_id: UUID,
    principal: Annotated[Principal, Depends(require_read("evidence"))],
    sess: DbSession,
) -> EvidenceResponse:
    """点查（全字段含 snapshot + links）；跨租户/不存在统一 404。"""
    record = await evidence_service.get_record(sess, evidence_id)
    if record is None:
        raise EdpError.not_found("证据不存在")
    links = await evidence_service.links_for(sess, evidence_id)
    resp = EvidenceResponse.model_validate(record)
    resp.links = [EvidenceLinkItem.model_validate(link) for link in links]
    return resp


@router.get(
    "/{evidence_id}/verify",
    response_model=VerifyResponse,
    summary="校验证据完整性（重算 checksum 比对）",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.TENANT_SUSPENDED,
        ErrorCode.NOT_FOUND,
    ),
)
async def verify_evidence(
    evidence_id: UUID,
    principal: Annotated[Principal, Depends(require_read("evidence"))],
    sess: DbSession,
) -> VerifyResponse:
    """重算 canonical checksum 与存储值比对；失配 → valid=false 且同事务落
    EVIDENCE_VERIFY_FAILED 告警审计（detail.risk=P1）。"""
    result = await evidence_service.verify_record(sess, principal, evidence_id)
    if result is None:
        raise EdpError.not_found("证据不存在")
    _, valid = result
    return VerifyResponse(
        evidence_id=evidence_id,
        valid=valid,
        verified_at=datetime.now(UTC),
    )


@admin_router.post(
    "/reindex",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ReindexAccepted,
    summary="触发证据重索引（异步：全量重算 checksum，失配仅统计不回写）",
    responses=error_responses(
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.FORBIDDEN,
        ErrorCode.TENANT_SUSPENDED,
        ErrorCode.CONFLICT,
        descriptions={
            ErrorCode.CONFLICT: "任务冲突（TASK_CONFLICT——同 task_type 已有任务执行中）"
        },
    ),
)
async def evidence_reindex(
    payload: ReindexRequest,
    principal: Annotated[Principal, Depends(require_reindex_run())],
    sess: DbSession,
) -> ReindexAccepted:
    """quality:run（ADMIN 轨道，权限码复用——见 dependencies.py docstring）：
    建 evidence_reindex 任务行（RUNNING）→ 202 {task_id, status}；后台全量
    重算 canonical checksum——**失配仅计数 + 落 quality.reindex_mismatch
    事件，保留原值不回写**（checksum 语义不变）。进度/终态经
    GET /admin/quality/tasks/{task_id} 轮询（quality:read，T4 轨道复用）；
    完成写 quality.reindex_succeeded/failed（执行语义见 service docstring）。
    """
    task = await evidence_service.start_reindex(sess, principal, scope=payload.scope)
    return ReindexAccepted(task_id=task.task_id, status=task.status)
