"""governance 路由（V1.2 Phase 2）：规则/别名/分类注册 + RAW 只读 + 准入审核。

- 注册面（gov:manage 写 / gov:read 读）：cleaning-rules / entity-aliases /
  dimensions / taxonomies / tags / object-classifications / raw-records；
- 审核面（admission:review，Human-Only）：admission 列表/详情 +
  source-review（A2）/ management-review（A3）/ archive（A4）。

router 级挂 tenant_scoped（认证 → 租户状态 → bind_tenant → RLS）；每条
路由单独挂鉴权依赖以取回 Principal。
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import EdpError, ErrorCode, error_responses
from edp_api.core.pagination import Page
from edp_api.core.security.principal import Principal
from edp_api.modules.governance import service as governance_service
from edp_api.modules.governance.dependencies import (
    require_admission_review,
    require_governance_manage,
    require_governance_read,
)
from edp_api.modules.governance.schemas import (
    AdmissionDetail,
    AdmissionListItem,
    AdmissionReviewedResponse,
    ClassificationCreate,
    ClassificationItem,
    CleaningRuleCreate,
    CleaningRuleItem,
    DimensionCreate,
    DimensionItem,
    EntityAliasCreate,
    EntityAliasItem,
    RawRecordItem,
    ReviewItem,
    ReviewRequest,
    TagAttachItem,
    TagAttachRequest,
    TagCreate,
    TagItem,
    TaxonomyCreate,
    TaxonomyItem,
)
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

router = APIRouter(
    prefix="/api/v1/governance",
    tags=["governance"],
    dependencies=[Depends(tenant_scoped)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]

_READ_ERRORS = (
    ErrorCode.UNAUTHENTICATED,
    ErrorCode.FORBIDDEN,
    ErrorCode.TENANT_SUSPENDED,
)
_WRITE_ERRORS = (*_READ_ERRORS, ErrorCode.VALIDATION_ERROR, ErrorCode.CONFLICT)
_REVIEW_ERRORS = (
    *_WRITE_ERRORS,
    ErrorCode.NOT_FOUND,
    ErrorCode.INVALID_TRANSITION,
    ErrorCode.GUARD_POLICY_DENIED,
)


# ---- 清洗规则（T10） ----


@router.post(
    "/cleaning-rules",
    response_model=CleaningRuleItem,
    status_code=status.HTTP_201_CREATED,
    summary="注册清洗规则（新版本自动覆盖旧生效区间）",
    responses=error_responses(*_WRITE_ERRORS),
)
async def create_cleaning_rule(
    payload: CleaningRuleCreate,
    principal: Annotated[Principal, Depends(require_governance_manage())],
    sess: DbSession,
) -> CleaningRuleItem:
    return CleaningRuleItem.model_validate(
        await governance_service.create_cleaning_rule(sess, principal, payload)
    )


@router.get(
    "/cleaning-rules",
    response_model=Page[CleaningRuleItem],
    response_model_exclude_none=True,
    summary="清洗规则列表（object_type 过滤 + 游标分页）",
    responses=error_responses(*_READ_ERRORS),
)
async def list_cleaning_rules(
    principal: Annotated[Principal, Depends(require_governance_read())],
    sess: DbSession,
    object_type: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=governance_service.MAX_LIMIT)] = (
        governance_service.DEFAULT_LIMIT
    ),
    cursor: Annotated[str | None, Query()] = None,
) -> Page[CleaningRuleItem]:
    return await governance_service.query_cleaning_rules(
        sess, object_type=object_type, limit=limit, cursor=cursor
    )


# ---- 实体解析别名（T11） ----


@router.post(
    "/entity-aliases",
    response_model=EntityAliasItem,
    status_code=status.HTTP_201_CREATED,
    summary="注册实体别名（alias → canonical 归一）",
    responses=error_responses(*_WRITE_ERRORS),
)
async def create_entity_alias(
    payload: EntityAliasCreate,
    principal: Annotated[Principal, Depends(require_governance_manage())],
    sess: DbSession,
) -> EntityAliasItem:
    return EntityAliasItem.model_validate(
        await governance_service.create_alias(sess, principal, payload)
    )


@router.get(
    "/entity-aliases",
    response_model=Page[EntityAliasItem],
    response_model_exclude_none=True,
    summary="实体别名列表（object_type 过滤 + 游标分页）",
    responses=error_responses(*_READ_ERRORS),
)
async def list_entity_aliases(
    principal: Annotated[Principal, Depends(require_governance_read())],
    sess: DbSession,
    object_type: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=governance_service.MAX_LIMIT)] = (
        governance_service.DEFAULT_LIMIT
    ),
    cursor: Annotated[str | None, Query()] = None,
) -> Page[EntityAliasItem]:
    return await governance_service.query_aliases(
        sess, object_type=object_type, limit=limit, cursor=cursor
    )


# ---- 多维分类（T12） ----


@router.post(
    "/dimensions",
    response_model=DimensionItem,
    status_code=status.HTTP_201_CREATED,
    summary="创建维度",
    responses=error_responses(*_WRITE_ERRORS),
)
async def create_dimension(
    payload: DimensionCreate,
    principal: Annotated[Principal, Depends(require_governance_manage())],
    sess: DbSession,
) -> DimensionItem:
    return DimensionItem.model_validate(
        await governance_service.create_dimension(sess, principal, payload)
    )


@router.get(
    "/dimensions",
    response_model=list[DimensionItem],
    summary="维度列表",
    responses=error_responses(*_READ_ERRORS),
)
async def list_dimensions(
    principal: Annotated[Principal, Depends(require_governance_read())],
    sess: DbSession,
) -> list[DimensionItem]:
    return [
        DimensionItem.model_validate(item)
        for item in await governance_service.list_dimensions(sess)
    ]


@router.post(
    "/taxonomies",
    response_model=TaxonomyItem,
    status_code=status.HTTP_201_CREATED,
    summary="创建分类树节点",
    responses=error_responses(*_WRITE_ERRORS),
)
async def create_taxonomy(
    payload: TaxonomyCreate,
    principal: Annotated[Principal, Depends(require_governance_manage())],
    sess: DbSession,
) -> TaxonomyItem:
    return TaxonomyItem.model_validate(
        await governance_service.create_taxonomy(sess, principal, payload)
    )


@router.get(
    "/taxonomies",
    response_model=list[TaxonomyItem],
    summary="分类树节点列表（dimension_id 过滤）",
    responses=error_responses(*_READ_ERRORS),
)
async def list_taxonomies(
    principal: Annotated[Principal, Depends(require_governance_read())],
    sess: DbSession,
    dimension_id: Annotated[UUID | None, Query()] = None,
) -> list[TaxonomyItem]:
    return [
        TaxonomyItem.model_validate(item)
        for item in await governance_service.list_taxonomies(
            sess, dimension_id=dimension_id
        )
    ]


@router.post(
    "/tags",
    response_model=TagItem,
    status_code=status.HTTP_201_CREATED,
    summary="创建标签",
    responses=error_responses(*_WRITE_ERRORS),
)
async def create_tag(
    payload: TagCreate,
    principal: Annotated[Principal, Depends(require_governance_manage())],
    sess: DbSession,
) -> TagItem:
    return TagItem.model_validate(
        await governance_service.create_tag(sess, principal, payload)
    )


@router.get(
    "/tags",
    response_model=list[TagItem],
    summary="标签列表",
    responses=error_responses(*_READ_ERRORS),
)
async def list_tags(
    principal: Annotated[Principal, Depends(require_governance_read())],
    sess: DbSession,
) -> list[TagItem]:
    return [
        TagItem.model_validate(item) for item in await governance_service.list_tags(sess)
    ]


@router.post(
    "/object-classifications",
    response_model=ClassificationItem,
    status_code=status.HTTP_201_CREATED,
    summary="挂接对象分类（AI_ASSISTED 仅建议）",
    responses=error_responses(*_WRITE_ERRORS),
)
async def create_classification(
    payload: ClassificationCreate,
    principal: Annotated[Principal, Depends(require_governance_manage())],
    sess: DbSession,
) -> ClassificationItem:
    return ClassificationItem.model_validate(
        await governance_service.create_classification(sess, principal, payload)
    )


@router.get(
    "/classifications",
    response_model=list[ClassificationItem],
    summary="对象分类列表（object_id 过滤，仅生效中版本）",
    responses=error_responses(*_READ_ERRORS),
)
async def list_classifications(
    principal: Annotated[Principal, Depends(require_governance_read())],
    sess: DbSession,
    object_id: Annotated[UUID | None, Query()] = None,
) -> list[ClassificationItem]:
    return [
        ClassificationItem.model_validate(item)
        for item in await governance_service.list_classifications(
            sess, object_id=object_id
        )
    ]


# ---- 对象标签挂接（T33） ----


@router.post(
    "/object-tags",
    response_model=TagAttachItem,
    status_code=status.HTTP_201_CREATED,
    summary="挂接对象标签（幂等：已挂返回既有行）",
    responses=error_responses(*_WRITE_ERRORS),
)
async def attach_object_tag(
    payload: TagAttachRequest,
    principal: Annotated[Principal, Depends(require_governance_manage())],
    sess: DbSession,
) -> TagAttachItem:
    return TagAttachItem.model_validate(
        await governance_service.attach_tag(
            sess, principal, object_id=payload.object_id, tag_id=payload.tag_id
        )
    )


@router.get(
    "/object-tags",
    response_model=list[TagAttachItem],
    summary="对象标签挂接列表（object_id 过滤）",
    responses=error_responses(*_READ_ERRORS),
)
async def list_object_tags(
    principal: Annotated[Principal, Depends(require_governance_read())],
    sess: DbSession,
    object_id: Annotated[UUID | None, Query()] = None,
) -> list[TagAttachItem]:
    return [
        TagAttachItem.model_validate(item)
        for item in await governance_service.list_object_tags(sess, object_id=object_id)
    ]


# ---- RAW 只读（T08） ----


@router.get(
    "/raw-records",
    response_model=Page[RawRecordItem],
    response_model_exclude_none=True,
    summary="RAW 记录只读列表（object_type 过滤 + 游标分页）",
    responses=error_responses(*_READ_ERRORS),
)
async def list_raw_records(
    principal: Annotated[Principal, Depends(require_governance_read())],
    sess: DbSession,
    object_type: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=governance_service.MAX_LIMIT)] = (
        governance_service.DEFAULT_LIMIT
    ),
    cursor: Annotated[str | None, Query()] = None,
) -> Page[RawRecordItem]:
    return await governance_service.query_raw_records(
        sess, object_type=object_type, limit=limit, cursor=cursor
    )


# ---- 准入审核（T13/T14/T15） ----


@router.get(
    "/admission",
    response_model=Page[AdmissionListItem],
    response_model_exclude_none=True,
    summary="准入记录列表（state 过滤 + 游标分页）",
    responses=error_responses(*_READ_ERRORS),
)
async def list_admissions(
    principal: Annotated[Principal, Depends(require_governance_read())],
    sess: DbSession,
    state_filter: Annotated[
        Literal[
            "RECEIVED",
            "PROFILED",
            "CLEANED",
            "STANDARDIZED",
            "CLASSIFIED",
            "SOURCE_REVIEW",
            "SOURCE_APPROVED",
            "MANAGEMENT_REVIEW",
            "MANAGEMENT_APPROVED",
            "OFFICIAL",
            "ARCHIVED",
            "RETURNED",
            "REJECTED",
            "SUSPENDED",
            "ESCALATED",
        ]
        | None,
        Query(alias="state"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=governance_service.MAX_LIMIT)] = (
        governance_service.DEFAULT_LIMIT
    ),
    cursor: Annotated[str | None, Query()] = None,
) -> Page[AdmissionListItem]:
    return await governance_service.query_admissions(
        sess, state=state_filter, limit=limit, cursor=cursor
    )


@router.get(
    "/admission/{admission_id}",
    response_model=AdmissionDetail,
    summary="准入记录详情",
    responses=error_responses(*_READ_ERRORS, ErrorCode.NOT_FOUND),
)
async def get_admission(
    admission_id: UUID,
    principal: Annotated[Principal, Depends(require_governance_read())],
    sess: DbSession,
) -> AdmissionDetail:
    admission = await governance_service.get_admission(sess, admission_id)
    if admission is None:
        raise EdpError.not_found("准入记录不存在")
    return AdmissionDetail.model_validate(admission)


@router.get(
    "/admission/{admission_id}/reviews",
    response_model=list[ReviewItem],
    summary="准入审核记录列表（A2/A3 留痕）",
    responses=error_responses(*_READ_ERRORS, ErrorCode.NOT_FOUND),
)
async def list_reviews(
    admission_id: UUID,
    principal: Annotated[Principal, Depends(require_governance_read())],
    sess: DbSession,
) -> list[ReviewItem]:
    if await governance_service.get_admission(sess, admission_id) is None:
        raise EdpError.not_found("准入记录不存在")
    return [
        ReviewItem.model_validate(item)
        for item in await governance_service.list_reviews(sess, admission_id)
    ]


@router.post(
    "/admission/{admission_id}/source-review",
    response_model=AdmissionReviewedResponse,
    summary="A2 本系统人机共审（Human-Only；机器 FAIL 阻断）",
    responses=error_responses(*_REVIEW_ERRORS),
)
async def source_review(
    admission_id: UUID,
    payload: ReviewRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_admission_review())],
    sess: DbSession,
) -> AdmissionReviewedResponse:
    admission = await governance_service.source_review(
        sess, principal, admission_id, payload, path=request.url.path
    )
    if admission is None:
        raise EdpError.not_found("准入记录不存在")
    return _reviewed_response(admission)


@router.post(
    "/admission/{admission_id}/management-review",
    response_model=AdmissionReviewedResponse,
    summary="A3 管理系统人机复审（Human-Only；机器 FAIL 阻断；通过转 OFFICIAL）",
    responses=error_responses(*_REVIEW_ERRORS),
)
async def management_review(
    admission_id: UUID,
    payload: ReviewRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_admission_review())],
    sess: DbSession,
) -> AdmissionReviewedResponse:
    admission = await governance_service.management_review(
        sess, principal, admission_id, payload, path=request.url.path
    )
    if admission is None:
        raise EdpError.not_found("准入记录不存在")
    return _reviewed_response(admission)


@router.post(
    "/admission/{admission_id}/archive",
    response_model=AdmissionReviewedResponse,
    summary="A4 正式归档（OFFICIAL → ARCHIVED）",
    responses=error_responses(*_REVIEW_ERRORS),
)
async def archive(
    admission_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(require_admission_review())],
    sess: DbSession,
) -> AdmissionReviewedResponse:
    admission = await governance_service.archive(
        sess, principal, admission_id, path=request.url.path
    )
    if admission is None:
        raise EdpError.not_found("准入记录不存在")
    return _reviewed_response(admission)


def _reviewed_response(admission) -> AdmissionReviewedResponse:
    return AdmissionReviewedResponse(
        admission_id=admission.admission_id,
        state=admission.state,
        review_result=admission.review_result,
        quality_score=float(admission.quality_score)
        if admission.quality_score is not None
        else None,
        updated_at=admission.updated_at,
    )
