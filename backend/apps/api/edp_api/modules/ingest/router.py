"""ingest 文件导入路由（V1.2 T30）：Excel/CSV 通道 → RAW → 管道全链。

- POST /admin/ingest/file：请求体 = CSV 文本（text/csv；utf-8 / utf-8-sig；
  Excel 工作簿请先另存 CSV——xlsx 解析不在本阶段，记偏差）；
- 模板列：object_type / source_id / occurred_at（ISO 8601；naive 按 UTC），
  其余列 = payload 字段（空串跳过；数值自动推断 int/float）；
- 行数上限 1000；模板/行校验失败逐行 errors（不整批失败）；
- 权限：adapters:write（HUMAN）/ write:adapters（SERVICE）——与 sync 轨道一致。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import EdpError, ErrorCode, error_responses
from edp_api.core.security.principal import Principal
from edp_api.core.security.rbac import make_require_access
from edp_api.modules.ingest import service as ingest_service
from edp_api.modules.ingest.schemas import ImportStats
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped

router = APIRouter(
    prefix="/api/v1/admin/ingest",
    tags=["ingest"],
    dependencies=[Depends(tenant_scoped)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]

_WRITE_ERRORS = (
    ErrorCode.UNAUTHENTICATED,
    ErrorCode.FORBIDDEN,
    ErrorCode.TENANT_SUSPENDED,
    ErrorCode.VALIDATION_ERROR,
)


@router.post(
    "/file",
    response_model=ImportStats,
    summary="CSV 批量导入（请求体 = CSV 文本；模板列 object_type/source_id/occurred_at）",
    responses=error_responses(*_WRITE_ERRORS),
)
async def import_file(
    request: Request,
    principal: Annotated[
        Principal, Depends(make_require_access("adapters", "write"))
    ],
    sess: DbSession,
) -> ImportStats:
    content = await request.body()
    if len(content) > ingest_service.MAX_FILE_BYTES:
        raise EdpError.validation_error(
            f"文件过大（上限 {ingest_service.MAX_FILE_BYTES} 字节）"
        )
    try:
        text_content = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise EdpError.validation_error("文件编码须为 UTF-8（含 BOM）") from exc
    return await ingest_service.import_csv(sess, principal, text_content)
