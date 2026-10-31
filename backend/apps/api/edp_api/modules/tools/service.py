"""tools 服务（EDP-015）：六接口查询组装（Read-Only 三层之应用/数据库层）。

执行顺序（硬约束——``event.events`` 不在只读角色授权域内）：
1. app 角色阶段：解析对象（projections_service 自然键解析/领域查询）并取
   evidence_hint（event.events 最新 ``{TYPE}_SNAPSHOT``，occurred_at DESC）；
2. ``read_only_session``：事务级 ``SET LOCAL ROLE edp_agent_ro``（0010 建角色
   并 GRANT 给 edp_app；随请求事务提交/回滚自动复位）；
3. 只读角色下经 projections_service 重读领域数据组装 B.8 响应——响应数据
   来自只读角色查询，数据库层纵深对返回路径真实生效（阶段 1 的领域查询仅
   用于解析对象 id，因 hint 需按 object_id 关联且必须在切角色前完成）。

404 语义（与 T3 查询口未命中分层一致）：订单/客户/BOM/物料/供应商对象
不存在 → NOT_FOUND；物料/供应商存在但无库存行/交期行 → 200 空数组。
列表端点（订单/采购）未命中 → 200 空 items。

evidence_hint 对象映射 = 端点响应身份对象：订单→ORDER、库存→MATERIAL
（material_id 为响应主键）、采购→逐条 PURCHASE_ORDER、BOM→BOM、交期→
SUPPLIER（supplier_code 为响应身份）、客户→CUSTOMER。
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.errors import EdpError
from edp_api.modules.projections import service as projections_service
from edp_api.modules.projections.service import Customer, OrderView
from edp_api.modules.tools.schemas import (
    BomItemResponse,
    BomResponse,
    CustomerRef,
    CustomerResponse,
    EvidenceHint,
    InventoryResponse,
    LeadTimeItem,
    OrderDetail,
    OrderLineItem,
    OrderListResponse,
    OrderSummary,
    PurchaseOrderItem,
    PurchaseOrderListResponse,
    SearchObjectItem,
    SearchObjectsResponse,
    SupplierLeadTimesResponse,
    WarehouseItem,
)

DEFAULT_LIMIT = projections_service.DEFAULT_LIMIT
MAX_LIMIT = projections_service.MAX_LIMIT

_SNAPSHOT_SUFFIX = "_SNAPSHOT"

# official_only（V1.2 T21）：对象须处于 CURATED（=OFFICIAL）/ARCHIVED
# 才可被 Agent 读取（layer_status 枚举见 business-object.schema.json）
_OFFICIAL_LAYERS = ("CURATED", "ARCHIVED")
_OFFICIAL_SQL = text("""
    SELECT object_id FROM master.business_objects
    WHERE tenant_id = :tenant_id AND object_id IN :object_ids
      AND layer_status IN ('CURATED', 'ARCHIVED')
""").bindparams(bindparam("object_ids", expanding=True))

# 对象集合 → 各对象最新 SNAPSHOT 事件（app 角色阶段执行；跨模块表纯 SQL，
# 口径同 projections/ingest——模块间仅可 import 对方 service，event ORM
# 不可直接引用）。DISTINCT ON + occurred_at DESC 取每对象最新一条。
_HINT_SQL = text("""
    SELECT DISTINCT ON (object_id) object_id, event_id
    FROM event.events
    WHERE tenant_id = :tenant_id
      AND event_type = :event_type
      AND object_id IN :object_ids
    ORDER BY object_id, occurred_at DESC, event_id DESC
""").bindparams(bindparam("object_ids", expanding=True))


async def read_only_session(sess: AsyncSession) -> None:
    """事务级只读角色收紧（Read-Only 三层之数据库层，设计 8.3）：此后本事务
    仅可 SELECT master/sales/delivery/rd；提交/回滚自动复位（SET LOCAL）。"""
    await sess.execute(text("SET LOCAL ROLE edp_agent_ro"))


async def _evidence_hints(
    sess: AsyncSession,
    tenant_id: UUID,
    object_type: str,
    object_ids: list[UUID],
) -> dict[UUID, UUID | None]:
    """对象集合 → 最新 ``{object_type}_SNAPSHOT`` 事件 id（缺 → None）。"""
    ids = list(dict.fromkeys(object_ids))
    hints: dict[UUID, UUID | None] = {object_id: None for object_id in ids}
    if not ids:
        return hints
    rows = (
        await sess.execute(
            _HINT_SQL,
            {
                "tenant_id": tenant_id,
                "event_type": f"{object_type}{_SNAPSHOT_SUFFIX}",
                "object_ids": ids,
            },
        )
    ).mappings()
    for row in rows:
        hints[row["object_id"]] = row["event_id"]
    return hints


async def _official_ids(
    sess: AsyncSession, tenant_id: UUID, object_ids: list[UUID]
) -> set[UUID]:
    """对象集合中处于 OFFICIAL/ARCHIVED 的子集（V1.2 T21 official_only）。"""
    ids = list(dict.fromkeys(object_ids))
    if not ids:
        return set()
    rows = (
        await sess.execute(
            _OFFICIAL_SQL, {"tenant_id": tenant_id, "object_ids": ids}
        )
    ).mappings()
    return {row["object_id"] for row in rows}


# search-objects（T33）：app 角色阶段 join 过滤（governance 分类/标签表不
# 在 edp_agent_ro 授权域）拿 object_ids → 只读角色下重读 business_objects
# 行组装响应（Read-Only 三层约定不变）。
_SEARCH_OBJECTS_SQL = text("""
    SELECT bo.object_id
    FROM master.business_objects bo
    LEFT JOIN governance.object_classifications oc
        ON oc.object_id = bo.object_id AND oc.effective_to IS NULL
    LEFT JOIN governance.dimensions d ON d.dimension_id = oc.dimension_id
    LEFT JOIN governance.object_tags ot ON ot.object_id = bo.object_id
    LEFT JOIN governance.tags t ON t.tag_id = ot.tag_id
    WHERE bo.tenant_id = :tenant_id
      AND (CAST(:object_type AS text) IS NULL OR bo.object_type = :object_type)
      AND (CAST(:classification AS text) IS NULL OR oc.label = :classification)
      AND (CAST(:dimension AS text) IS NULL OR d.code = :dimension)
      AND (CAST(:tag AS text) IS NULL OR t.code = :tag)
      AND (:official_only = FALSE OR bo.layer_status IN ('CURATED', 'ARCHIVED'))
    GROUP BY bo.object_id
    ORDER BY max(bo.updated_at) DESC, bo.object_id DESC
    LIMIT :limit
""")

_SEARCH_OBJECT_ROWS_SQL = text("""
    SELECT object_id, object_type, source_system, source_id, attributes
    FROM master.business_objects
    WHERE tenant_id = :tenant_id AND object_id IN :object_ids
""").bindparams(bindparam("object_ids", expanding=True))


async def search_objects(
    sess: AsyncSession,
    tenant_id: UUID,
    *,
    object_type: str | None = None,
    classification: str | None = None,
    dimension: str | None = None,
    tag: str | None = None,
    official_only: bool = True,
    limit: int = DEFAULT_LIMIT,
) -> SearchObjectsResponse:
    """多维查询（V1.2 第四十六节 / T33）：dimensions/classifications/tags/
    object_type/official_only 过滤；禁止 Agent 自由 SQL。"""
    limit = max(1, min(limit, MAX_LIMIT))
    ids = (
        await sess.execute(
            _SEARCH_OBJECTS_SQL,
            {
                "tenant_id": tenant_id,
                "object_type": object_type,
                "classification": classification,
                "dimension": dimension,
                "tag": tag,
                "official_only": official_only,
                "limit": limit,
            },
        )
    ).scalars().all()
    if not ids:
        return SearchObjectsResponse(items=[])

    await read_only_session(sess)
    rows = (
        await sess.execute(
            _SEARCH_OBJECT_ROWS_SQL,
            {"tenant_id": tenant_id, "object_ids": ids},
        )
    ).mappings().all()
    return SearchObjectsResponse(
        items=[
            SearchObjectItem(
                object_id=row["object_id"],
                object_type=row["object_type"],
                source_system=row["source_system"],
                source_id=row["source_id"],
                attributes=dict(row["attributes"] or {}),
            )
            for row in rows
        ]
    )


async def _require_official(
    sess: AsyncSession,
    tenant_id: UUID,
    object_id: UUID,
    official_only: bool,
) -> None:
    """official_only 门禁：对象非 OFFICIAL/ARCHIVED → 404（Agent 读不到
    非正式数据，与不存在同义）。"""
    if not official_only:
        return
    if object_id not in await _official_ids(sess, tenant_id, [object_id]):
        raise EdpError.not_found("对象未通过数据准入（非 OFFICIAL）")


def _hint(object_id: UUID, event_id: UUID | None) -> EvidenceHint:
    return EvidenceHint(object_id=object_id, event_id=event_id)


def _as_float(value: Decimal | int | float | None) -> float | None:
    """数值归一（B.8 为 JSON 数字；Decimal 直接序列化会变字符串）。"""
    return None if value is None else float(value)


def _customer_ref(customer: Customer | None) -> CustomerRef | None:
    if customer is None:
        return None
    return CustomerRef(code=customer.code, name=customer.name, level=customer.level)


def _order_summary(view: OrderView, hints: dict[UUID, UUID | None]) -> OrderSummary:
    order = view.order
    return OrderSummary(
        order_no=order.order_no,
        object_id=order.order_id,
        customer=_customer_ref(view.customer),
        amount=_as_float(order.amount),
        currency=order.currency,
        status=order.status,
        order_date=order.order_date,
        delivery_date=order.delivery_date,
        evidence_hint=_hint(order.order_id, hints.get(order.order_id)),
    )


async def get_order(
    sess: AsyncSession,
    tenant_id: UUID,
    order_no: str,
    *,
    official_only: bool = True,
) -> OrderDetail:
    """GET /tools/orders/{order_no}：订单详情（客户/金额/状态/交期 + lines）。"""
    object_id = await projections_service.resolve_object_id(
        sess, tenant_id, "ORDER", order_no
    )
    if object_id is None:
        raise EdpError.not_found("订单不存在")
    await _require_official(sess, tenant_id, object_id, official_only)
    hints = await _evidence_hints(sess, tenant_id, "ORDER", [object_id])

    await read_only_session(sess)
    view = await projections_service.get_order_by_no(sess, tenant_id, order_no)
    if view is None:
        raise EdpError.not_found("订单不存在")
    summary = _order_summary(view, hints)
    return OrderDetail(
        **summary.model_dump(),
        lines=[
            OrderLineItem(
                product_code=line.product_code,
                material_code=line.material_code,
                quantity=_as_float(line.line.quantity),
                unit_price=_as_float(line.line.unit_price),
            )
            for line in view.lines
        ],
    )


async def list_orders(
    sess: AsyncSession,
    tenant_id: UUID,
    *,
    customer_code: str | None = None,
    status: str | None = None,
    limit: int = DEFAULT_LIMIT,
    official_only: bool = True,
) -> OrderListResponse:
    """GET /tools/orders：订单摘要列表（无 lines 明细；customer/status 过滤；
    official_only 仅返回 OFFICIAL/ARCHIVED 对象）。"""
    pre = await projections_service.list_orders(
        sess, tenant_id, customer_code=customer_code, status=status, limit=limit
    )
    official = None
    if official_only:
        official = await _official_ids(
            sess, tenant_id, [view.order.order_id for view in pre]
        )
    hints = await _evidence_hints(
        sess, tenant_id, "ORDER", [view.order.order_id for view in pre]
    )

    await read_only_session(sess)
    views = await projections_service.list_orders(
        sess, tenant_id, customer_code=customer_code, status=status, limit=limit
    )
    if official is not None:
        views = [view for view in views if view.order.order_id in official]
    return OrderListResponse(
        items=[_order_summary(view, hints) for view in views], next_cursor=None
    )


async def get_inventory(
    sess: AsyncSession,
    tenant_id: UUID,
    material_code: str,
    *,
    official_only: bool = True,
) -> InventoryResponse:
    """GET /tools/inventory：物料库存（warehouses[] + total_available）。"""
    material_id = await projections_service.resolve_object_id(
        sess, tenant_id, "MATERIAL", material_code
    )
    if material_id is None:
        raise EdpError.not_found("物料不存在")
    await _require_official(sess, tenant_id, material_id, official_only)
    hints = await _evidence_hints(sess, tenant_id, "MATERIAL", [material_id])

    await read_only_session(sess)
    view = await projections_service.list_inventory_by_material_code(
        sess, tenant_id, material_code
    )
    if view is None:
        raise EdpError.not_found("物料不存在")
    warehouses = [
        WarehouseItem(
            warehouse=row.warehouse,
            available=float(row.quantity_available),
            reserved=float(row.quantity_reserved),
        )
        for row in view.warehouses
    ]
    return InventoryResponse(
        material_code=view.material.code,
        material_id=view.material.material_id,
        warehouses=warehouses,
        total_available=sum(item.available for item in warehouses),
        snapshot_at=max((row.snapshot_at for row in view.warehouses), default=None),
        evidence_hint=_hint(
            view.material.material_id, hints.get(view.material.material_id)
        ),
    )


async def list_purchase_orders(
    sess: AsyncSession,
    tenant_id: UUID,
    *,
    material_code: str | None = None,
    status: str | None = None,
    limit: int = DEFAULT_LIMIT,
    official_only: bool = True,
) -> PurchaseOrderListResponse:
    """GET /tools/purchase-orders：采购单列表（material_code/status 过滤；
    official_only 仅返回 OFFICIAL/ARCHIVED 对象）。"""
    pre = await projections_service.list_purchase_orders(
        sess, tenant_id, material_code=material_code, status=status, limit=limit
    )
    official = None
    if official_only:
        official = await _official_ids(
            sess, tenant_id, [view.po.po_id for view in pre]
        )
    hints = await _evidence_hints(
        sess, tenant_id, "PURCHASE_ORDER", [view.po.po_id for view in pre]
    )

    await read_only_session(sess)
    views = await projections_service.list_purchase_orders(
        sess, tenant_id, material_code=material_code, status=status, limit=limit
    )
    if official is not None:
        views = [view for view in views if view.po.po_id in official]
    return PurchaseOrderListResponse(
        items=[
            PurchaseOrderItem(
                po_no=view.po.po_no,
                object_id=view.po.po_id,
                supplier_code=view.supplier.code if view.supplier else None,
                quantity=_as_float(view.po.quantity),
                expected_date=view.po.expected_date,
                status=view.po.status,
                evidence_hint=_hint(view.po.po_id, hints.get(view.po.po_id)),
            )
            for view in views
        ],
        next_cursor=None,
    )


async def get_bom(
    sess: AsyncSession,
    tenant_id: UUID,
    product_code: str,
    *,
    official_only: bool = True,
) -> BomResponse:
    """GET /tools/bom：产品 ACTIVE BOM（bom_version + items[]）。"""
    pre = await projections_service.get_active_bom(sess, tenant_id, product_code)
    if pre is None:
        raise EdpError.not_found("产品 BOM 不存在")
    await _require_official(sess, tenant_id, pre.bom.bom_id, official_only)
    hints = await _evidence_hints(sess, tenant_id, "BOM", [pre.bom.bom_id])

    await read_only_session(sess)
    view = await projections_service.get_active_bom(sess, tenant_id, product_code)
    if view is None:
        raise EdpError.not_found("产品 BOM 不存在")
    return BomResponse(
        product_code=view.product.code,
        bom_version=view.bom.version,
        items=[
            BomItemResponse(
                material_code=item.material.code if item.material else None,
                quantity_per=_as_float(item.item.quantity),
            )
            for item in view.items
        ],
        evidence_hint=_hint(view.bom.bom_id, hints.get(view.bom.bom_id)),
    )


async def list_supplier_lead_times(
    sess: AsyncSession,
    tenant_id: UUID,
    supplier_code: str,
    *,
    official_only: bool = True,
) -> SupplierLeadTimesResponse:
    """GET /tools/supplier-lead-times：供应商交期（lead_times[] + updated_at）。"""
    supplier_id = await projections_service.resolve_object_id(
        sess, tenant_id, "SUPPLIER", supplier_code
    )
    if supplier_id is None:
        raise EdpError.not_found("供应商不存在")
    await _require_official(sess, tenant_id, supplier_id, official_only)
    hints = await _evidence_hints(sess, tenant_id, "SUPPLIER", [supplier_id])

    await read_only_session(sess)
    view = await projections_service.list_lead_times(sess, tenant_id, supplier_code)
    if view is None:
        raise EdpError.not_found("供应商不存在")
    return SupplierLeadTimesResponse(
        supplier_code=view.supplier.code,
        lead_times=[
            LeadTimeItem(
                material_code=item.material.code if item.material else None,
                lead_time_days=item.lead_time.lead_time_days,
            )
            for item in view.items
        ],
        updated_at=max(
            (item.lead_time.updated_at for item in view.items), default=None
        ),
        evidence_hint=_hint(
            view.supplier.supplier_id, hints.get(view.supplier.supplier_id)
        ),
    )


async def get_customer(
    sess: AsyncSession,
    tenant_id: UUID,
    customer_code: str,
    *,
    official_only: bool = True,
) -> CustomerResponse:
    """GET /tools/customers/{code}：客户主数据（name/level/attributes）。"""
    object_id = await projections_service.resolve_object_id(
        sess, tenant_id, "CUSTOMER", customer_code
    )
    if object_id is None:
        raise EdpError.not_found("客户不存在")
    await _require_official(sess, tenant_id, object_id, official_only)
    hints = await _evidence_hints(sess, tenant_id, "CUSTOMER", [object_id])

    await read_only_session(sess)
    customer = await projections_service.get_customer_by_code(
        sess, tenant_id, customer_code
    )
    if customer is None:
        raise EdpError.not_found("客户不存在")
    return CustomerResponse(
        customer_code=customer.code,
        name=customer.name,
        level=customer.level,
        attributes=customer.attributes or {},
        evidence_hint=_hint(customer.customer_id, hints.get(customer.customer_id)),
    )
