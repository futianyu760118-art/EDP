"""tools 路由（附录 B.8，EDP-015）：Agent 数据工具六接口 + orders 列表变体。

全 Read-Only 三层：① 应用层——仅注册 GET（非 GET → Starlette 405，由
core.errors 的 StarletteHTTPException 处理器统一 envelope METHOD_NOT_ALLOWED）
+ 双轨鉴权 ``require_tools_read``（SERVICE readonly scope / HUMAN tools:read，
拒绝先落 GUARD_DENIED 审计）；② 数据库层——service 内 SET LOCAL ROLE
edp_agent_ro；③ 审计层——见 dependencies.py。

router 级挂 tenant_scoped（认证 → 租户状态 → bind_tenant → RLS）；每条路由
单独挂 require_tools_read() 以取回 Principal（tenant_id 供领域查询）。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import get_db
from edp_api.core.errors import ErrorCode, error_responses
from edp_api.core.security.principal import Principal
from edp_api.modules.tenantmgmt.dependencies import tenant_scoped
from edp_api.modules.tools import service as tools_service
from edp_api.modules.tools.dependencies import require_tools_read
from edp_api.modules.tools.schemas import (
    BomResponse,
    CustomerResponse,
    InventoryResponse,
    OrderDetail,
    OrderListResponse,
    PurchaseOrderListResponse,
    SearchObjectsResponse,
    SupplierLeadTimesResponse,
)

router = APIRouter(
    prefix="/api/v1/tools",
    tags=["tools"],
    dependencies=[Depends(tenant_scoped)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]

_READ_ERRORS = (
    ErrorCode.UNAUTHENTICATED,
    ErrorCode.FORBIDDEN,
    ErrorCode.TENANT_SUSPENDED,
    ErrorCode.METHOD_NOT_ALLOWED,
    ErrorCode.RATE_LIMITED,
)
_READ_ERRORS_NOT_FOUND = (*_READ_ERRORS, ErrorCode.NOT_FOUND)


@router.get(
    "/orders",
    response_model=OrderListResponse,
    summary="订单摘要列表（customer/status 过滤）",
    responses=error_responses(*_READ_ERRORS),
)
async def list_orders(
    principal: Annotated[Principal, Depends(require_tools_read())],
    sess: DbSession,
    customer: Annotated[str | None, Query(description="客户 code 过滤")] = None,
    status: Annotated[str | None, Query(description="订单状态过滤")] = None,
    official_only: Annotated[
        bool,
        Query(description="仅返回 OFFICIAL/ARCHIVED 对象（V1.2 T21，缺省 true）"),
    ] = True,
    limit: Annotated[int, Query(ge=1, le=tools_service.MAX_LIMIT)] = (
        tools_service.DEFAULT_LIMIT
    ),
) -> OrderListResponse:
    """订单摘要列表（B.8：同详情结构数组，不含 lines 明细）。"""
    return await tools_service.list_orders(
        sess,
        principal.tenant_id,
        customer_code=customer,
        status=status,
        limit=limit,
        official_only=official_only,
    )


@router.get(
    "/orders/{order_no}",
    response_model=OrderDetail,
    summary="订单详情（含行明细与客户）",
    responses=error_responses(*_READ_ERRORS_NOT_FOUND),
)
async def get_order(
    order_no: str,
    principal: Annotated[Principal, Depends(require_tools_read())],
    sess: DbSession,
    official_only: Annotated[
        bool,
        Query(description="仅读取 OFFICIAL/ARCHIVED 对象（V1.2 T21，缺省 true）"),
    ] = True,
) -> OrderDetail:
    """订单详情；不存在/跨租户/非 OFFICIAL 统一 404 NOT_FOUND（不泄露存在性）。"""
    return await tools_service.get_order(
        sess, principal.tenant_id, order_no, official_only=official_only
    )


@router.get(
    "/inventory",
    response_model=InventoryResponse,
    summary="物料库存（仓库粒度 + 合计可用量）",
    responses=error_responses(*_READ_ERRORS_NOT_FOUND),
)
async def get_inventory(
    material_code: Annotated[str, Query(description="物料 code")],
    principal: Annotated[Principal, Depends(require_tools_read())],
    sess: DbSession,
    official_only: Annotated[
        bool,
        Query(description="仅读取 OFFICIAL/ARCHIVED 对象（V1.2 T21，缺省 true）"),
    ] = True,
) -> InventoryResponse:
    """物料库存；物料不存在 → 404，无库存行 → 200 空 warehouses。"""
    return await tools_service.get_inventory(
        sess, principal.tenant_id, material_code, official_only=official_only
    )


@router.get(
    "/purchase-orders",
    response_model=PurchaseOrderListResponse,
    summary="采购单列表（material_code/status 过滤）",
    responses=error_responses(*_READ_ERRORS),
)
async def list_purchase_orders(
    principal: Annotated[Principal, Depends(require_tools_read())],
    sess: DbSession,
    material_code: Annotated[str | None, Query(description="物料 code 过滤")] = None,
    status: Annotated[str | None, Query(description="采购单状态过滤")] = None,
    official_only: Annotated[
        bool,
        Query(description="仅返回 OFFICIAL/ARCHIVED 对象（V1.2 T21，缺省 true）"),
    ] = True,
    limit: Annotated[int, Query(ge=1, le=tools_service.MAX_LIMIT)] = (
        tools_service.DEFAULT_LIMIT
    ),
) -> PurchaseOrderListResponse:
    """采购单列表（B.8：items + next_cursor；游标分页字段本轮占位）。"""
    return await tools_service.list_purchase_orders(
        sess,
        principal.tenant_id,
        material_code=material_code,
        status=status,
        limit=limit,
        official_only=official_only,
    )


@router.get(
    "/bom",
    response_model=BomResponse,
    summary="产品 BOM（ACTIVE 版本 + 用量行）",
    responses=error_responses(*_READ_ERRORS_NOT_FOUND),
)
async def get_bom(
    product_code: Annotated[str, Query(description="产品 code")],
    principal: Annotated[Principal, Depends(require_tools_read())],
    sess: DbSession,
    official_only: Annotated[
        bool,
        Query(description="仅读取 OFFICIAL/ARCHIVED 对象（V1.2 T21，缺省 true）"),
    ] = True,
) -> BomResponse:
    """产品 ACTIVE BOM；产品/版本不存在 → 404。"""
    return await tools_service.get_bom(
        sess, principal.tenant_id, product_code, official_only=official_only
    )


@router.get(
    "/supplier-lead-times",
    response_model=SupplierLeadTimesResponse,
    summary="供应商交期（物料粒度）",
    responses=error_responses(*_READ_ERRORS_NOT_FOUND),
)
async def list_supplier_lead_times(
    supplier_code: Annotated[str, Query(description="供应商 code")],
    principal: Annotated[Principal, Depends(require_tools_read())],
    sess: DbSession,
    official_only: Annotated[
        bool,
        Query(description="仅读取 OFFICIAL/ARCHIVED 对象（V1.2 T21，缺省 true）"),
    ] = True,
) -> SupplierLeadTimesResponse:
    """供应商交期；供应商不存在 → 404，无交期行 → 200 空 lead_times。"""
    return await tools_service.list_supplier_lead_times(
        sess, principal.tenant_id, supplier_code, official_only=official_only
    )


@router.get(
    "/customers/{customer_code}",
    response_model=CustomerResponse,
    summary="客户主数据（name/level/attributes）",
    responses=error_responses(*_READ_ERRORS_NOT_FOUND),
)
async def get_customer(
    customer_code: str,
    principal: Annotated[Principal, Depends(require_tools_read())],
    sess: DbSession,
    official_only: Annotated[
        bool,
        Query(description="仅读取 OFFICIAL/ARCHIVED 对象（V1.2 T21，缺省 true）"),
    ] = True,
) -> CustomerResponse:
    """客户主数据；不存在/跨租户/非 OFFICIAL 统一 404 NOT_FOUND。"""
    return await tools_service.get_customer(
        sess, principal.tenant_id, customer_code, official_only=official_only
    )


@router.get(
    "/search-objects",
    response_model=SearchObjectsResponse,
    summary="多维对象查询（分类/维度/标签/official_only，V1.2 T33）",
    responses=error_responses(*_READ_ERRORS),
)
async def search_objects(
    principal: Annotated[Principal, Depends(require_tools_read())],
    sess: DbSession,
    object_type: Annotated[str | None, Query(max_length=64)] = None,
    classification: Annotated[str | None, Query(max_length=128)] = None,
    dimension: Annotated[str | None, Query(max_length=64)] = None,
    tag: Annotated[str | None, Query(max_length=64)] = None,
    official_only: Annotated[
        bool,
        Query(description="仅返回 OFFICIAL/ARCHIVED 对象（缺省 true）"),
    ] = True,
    limit: Annotated[int, Query(ge=1, le=tools_service.MAX_LIMIT)] = (
        tools_service.DEFAULT_LIMIT
    ),
) -> SearchObjectsResponse:
    """多维查询（V1.1 第四十六节）：禁止 Agent 自由 SQL，默认仅 OFFICIAL。"""
    return await tools_service.search_objects(
        sess,
        principal.tenant_id,
        object_type=object_type,
        classification=classification,
        dimension=dimension,
        tag=tag,
        official_only=official_only,
        limit=limit,
    )
