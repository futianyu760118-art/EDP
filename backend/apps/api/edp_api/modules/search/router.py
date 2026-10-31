"""search 路由（W6 T1）：GET /api/v1/search 全局搜索三组聚合。

认证用户即可（JWT 或 API Key 双轨，统一挂 tenant_scoped：认证 → 租户
状态 → bind_tenant → RLS）——聚合为只读最小投影，不设资源 scope/权限码，
租户过滤全靠 RLS。q 必填（trim 后 ≥1 字符，否则 400）；limit 默认 10、
上限 50（每组上限）。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import EdpError, ErrorCode, error_responses
from edp_api.core.security.principal import Principal
from edp_api.modules.search import service as search_service
from edp_api.modules.search.schemas import SearchResponse
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

router = APIRouter(
    prefix="/api/v1/search",
    tags=["search"],
    dependencies=[Depends(tenant_scoped)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get(
    "",
    response_model=SearchResponse,
    summary="全局搜索（对象/事件/证据三组聚合）",
    responses=error_responses(
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.UNAUTHENTICATED,
        ErrorCode.TENANT_SUSPENDED,
    ),
)
async def global_search(
    principal: Annotated[Principal, Depends(tenant_scoped)],
    sess: DbSession,
    q: Annotated[
        str | None, Query(description="关键词（trim 后至少 1 个字符，否则 400）")
    ] = None,
    limit: Annotated[
        int, Query(ge=1, le=search_service.MAX_LIMIT, description="每组返回上限")
    ] = search_service.DEFAULT_LIMIT,
) -> SearchResponse:
    """objects（source_id/object_type）/ events（event_type 或
    data->>'summary'）/ evidence（source_record_id/source_system）三组
    ILIKE 聚合，各组时间序 DESC LIMIT limit；total = 三组返回行数合计。"""
    keyword = (q or "").strip()
    if not keyword:
        raise EdpError.validation_error("q 必填（trim 后至少 1 个字符）")
    return await search_service.search_all(sess, keyword, limit)
