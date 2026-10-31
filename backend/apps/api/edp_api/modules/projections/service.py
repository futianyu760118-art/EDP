"""projections 服务：SourceRecord → 领域快照表投影（同事务）+ 领域查询口。

- project_record：按 object_type 分派投影器（spec §2.2 的 10 类映射）；未知
  类型静默跳过（通用对象无投影）。投影异常由调用方（管道）捕获记 warning，
  不阻断三元组落库；
- resolve_object_id：自然键 (object_type, source_id) → object_id（RLS 会话内
  查询，跨租户 = 不存在）。跨模块表 master.business_objects 走纯 SQL——
  import-linter 约定模块间仅可 import 对方 service，registry ORM 不可直接
  引用（口径同 ingest.service 的事件写入口）；
- 投影器统一模式：_upsert 主键 upsert（仅覆盖非 None 值，防缺键降级）+ 行
  明细先删后插（order_lines/bom_items/milestones，行 id = uuid5(object_id,
  "...:{idx}")）；SUPPLIER_LEAD_TIME 按 (tenant, supplier, material) 唯一键
  upsert（id = uuid5(object_id, "lead")）；
- 查询函数（get_order_by_no / list_orders / list_inventory_by_material_code /
  list_purchase_orders / get_active_bom / list_lead_times /
  get_customer_by_code）供 tools 模块使用：join master 主数据表返回视图
  dataclass（内含领域 ORM 行 + 解析后的 code），未命中返回 None/[]。RLS 会话
  已绑租户，查询仍显式带 tenant_id 条件（双保险）。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid5

from edp_adapters.base import SourceRecord
from sqlalchemy import and_, delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.modules.projections.models import (
    Bom,
    BomItem,
    Capacity,
    Customer,
    Inventory,
    Material,
    Product,
    PurchaseOrder,
    RdMilestone,
    RdProject,
    SalesOrder,
    SalesOrderLine,
    Supplier,
    SupplierLeadTime,
)

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

# 可解析对象类型（自然键 → object_id）：其余类型的 FK 经各自 payload 的 code
# 字段解析（ORDER→CUSTOMER、PO→SUPPLIER/MATERIAL 等），本集合为文档与调用方
# 校验口径。
RESOLVABLE_TYPES = frozenset({"CUSTOMER", "MATERIAL", "PRODUCT", "SUPPLIER"})

# 跨模块表 master.business_objects：纯 SQL（import-linter：模块间仅可 import
# 对方 service，registry ORM 不可直接引用）。
_RESOLVE_OBJECT_SQL = text("""
    SELECT object_id
    FROM master.business_objects
    WHERE tenant_id = :tenant_id
      AND object_type = :object_type
      AND source_id = :source_id
    LIMIT 1
""")

# 各类型 payload 中已映射到列/子表的键（其余进 attributes；owner_domain 恒剔除）
_KNOWN_CUSTOMER_KEYS = frozenset({"name", "level"})
_KNOWN_MATERIAL_KEYS = frozenset({"name", "unit"})
_KNOWN_PRODUCT_KEYS = frozenset({"name", "category", "status"})
_KNOWN_SUPPLIER_KEYS = frozenset({"name"})
_KNOWN_ORDER_KEYS = frozenset(
    {"customer_code", "amount", "currency", "status", "order_date", "delivery_date", "lines"}
)
_KNOWN_PURCHASE_ORDER_KEYS = frozenset(
    {"supplier_code", "material_code", "quantity", "expected_date", "status"}
)
_KNOWN_INVENTORY_KEYS = frozenset({"material_code", "warehouse", "available", "reserved"})
_KNOWN_PROJECT_KEYS = frozenset(
    {"product_code", "status", "stage", "readiness_level", "milestones"}
)


# ---- 纯映射助手（单测覆盖边界：None/缺键/ISO 串/金额计算） ----


def _decimal(value: Any) -> Decimal | None:
    """数值归一：int/float/str/Decimal → Decimal；None/非法 → None。"""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _parse_dt(value: Any) -> datetime | None:
    """ISO 字符串 / date / datetime → UTC aware datetime；缺失/非法 → None。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _rest(payload: dict[str, Any], known: frozenset[str]) -> dict[str, Any]:
    """剔除已映射键与 owner_domain 后的剩余字段（attributes 兜底）。"""
    return {
        key: value
        for key, value in payload.items()
        if key not in known and key != "owner_domain"
    }


def _line_amount(line: dict[str, Any]) -> Decimal | None:
    """行金额：显式 amount 优先；否则 quantity × unit_price；缺键 → None。"""
    explicit = _decimal(line.get("amount"))
    if explicit is not None:
        return explicit
    quantity = _decimal(line.get("quantity"))
    unit_price = _decimal(line.get("unit_price"))
    if quantity is None or unit_price is None:
        return None
    return quantity * unit_price


# ---- 自然键解析与 upsert 基座 ----


async def resolve_object_id(
    sess: AsyncSession, tenant_id: UUID, object_type: str, source_id: str
) -> UUID | None:
    """自然键 (object_type, source_id) → object_id；未命中 → None（不抛）。

    RLS 会话内查询（跨租户 = 不存在）；显式 tenant_id 条件为双保险。
    """
    return (
        await sess.execute(
            _RESOLVE_OBJECT_SQL,
            {
                "tenant_id": tenant_id,
                "object_type": object_type,
                "source_id": source_id,
            },
        )
    ).scalar_one_or_none()


async def _upsert(
    sess: AsyncSession,
    model: type[Any],
    values: dict[str, Any],
    *,
    pk: str,
    object_id: UUID,
) -> None:
    """主键 upsert：行存在 → 逐列赋值（仅覆盖非 None 值，防缺键降级）；否则
    新增（updated_at/updated_by 由 server_default / 调用方补）。"""
    row = await sess.get(model, object_id)
    if row is None:
        sess.add(model(**values))
        return
    for column, value in values.items():
        if column != pk and value is not None:
            setattr(row, column, value)


# ---- 10 类投影器（spec §2.2 映射表逐字段） ----


async def _project_customer(
    sess: AsyncSession, tenant_id: UUID, record: SourceRecord, object_id: UUID
) -> None:
    payload = record.payload
    values = dict(
        customer_id=object_id,
        tenant_id=tenant_id,
        code=record.source_id,
        name=payload.get("name") or record.source_id,
        level=payload.get("level"),
        attributes=_rest(payload, _KNOWN_CUSTOMER_KEYS),
    )
    await _upsert(sess, Customer, values, pk="customer_id", object_id=object_id)
    await sess.flush()


async def _project_material(
    sess: AsyncSession, tenant_id: UUID, record: SourceRecord, object_id: UUID
) -> None:
    payload = record.payload
    values = dict(
        material_id=object_id,
        tenant_id=tenant_id,
        code=record.source_id,
        name=payload.get("name") or record.source_id,
        unit=payload.get("unit"),
        attributes=_rest(payload, _KNOWN_MATERIAL_KEYS),
    )
    await _upsert(sess, Material, values, pk="material_id", object_id=object_id)
    await sess.flush()


async def _project_product(
    sess: AsyncSession, tenant_id: UUID, record: SourceRecord, object_id: UUID
) -> None:
    payload = record.payload
    values = dict(
        product_id=object_id,
        tenant_id=tenant_id,
        code=record.source_id,
        name=payload.get("name") or record.source_id,
        category=payload.get("category"),
        status=payload.get("status", "ACTIVE"),
    )
    await _upsert(sess, Product, values, pk="product_id", object_id=object_id)
    await sess.flush()


async def _project_supplier(
    sess: AsyncSession, tenant_id: UUID, record: SourceRecord, object_id: UUID
) -> None:
    payload = record.payload
    values = dict(
        supplier_id=object_id,
        tenant_id=tenant_id,
        code=record.source_id,
        name=payload.get("name") or record.source_id,
        attributes=_rest(payload, _KNOWN_SUPPLIER_KEYS),
    )
    await _upsert(sess, Supplier, values, pk="supplier_id", object_id=object_id)
    await sess.flush()


async def _project_order(
    sess: AsyncSession, tenant_id: UUID, record: SourceRecord, object_id: UUID
) -> None:
    payload = record.payload
    customer_id = await resolve_object_id(
        sess, tenant_id, "CUSTOMER", payload.get("customer_code", "")
    )
    if customer_id is None:
        logger.warning("订单客户未解析：%s/%s", record.source_system, record.source_id)
    values = dict(
        order_id=object_id,
        tenant_id=tenant_id,
        order_no=record.source_id,
        customer_id=customer_id,
        amount=_decimal(payload.get("amount")),
        currency=payload.get("currency", "CNY"),
        status=payload.get("status", "未知"),
        order_date=_parse_dt(payload.get("order_date")),
        delivery_date=_parse_dt(payload.get("delivery_date")),
        snapshot_at=record.occurred_at,
        attributes=_rest(payload, _KNOWN_ORDER_KEYS),
    )
    await _upsert(sess, SalesOrder, values, pk="order_id", object_id=object_id)
    # 行明细整组替换（先删后插，revision 更新防残留）
    await sess.execute(
        delete(SalesOrderLine).where(
            SalesOrderLine.tenant_id == tenant_id,
            SalesOrderLine.order_id == object_id,
        )
    )
    for idx, line in enumerate(payload.get("lines") or []):
        sess.add(
            SalesOrderLine(
                line_id=uuid5(object_id, f"line:{idx}"),
                tenant_id=tenant_id,
                order_id=object_id,
                product_id=await resolve_object_id(
                    sess, tenant_id, "PRODUCT", line.get("product_code", "")
                ),
                material_id=await resolve_object_id(
                    sess, tenant_id, "MATERIAL", line.get("material_code", "")
                ),
                quantity=_decimal(line.get("quantity")),
                unit_price=_decimal(line.get("unit_price")),
                amount=_line_amount(line),
            )
        )
    await sess.flush()


async def _project_purchase_order(
    sess: AsyncSession, tenant_id: UUID, record: SourceRecord, object_id: UUID
) -> None:
    payload = record.payload
    values = dict(
        po_id=object_id,
        tenant_id=tenant_id,
        po_no=record.source_id,
        supplier_id=await resolve_object_id(
            sess, tenant_id, "SUPPLIER", payload.get("supplier_code", "")
        ),
        material_id=await resolve_object_id(
            sess, tenant_id, "MATERIAL", payload.get("material_code", "")
        ),
        quantity=_decimal(payload.get("quantity")),
        expected_date=_parse_dt(payload.get("expected_date")),
        status=payload.get("status", "未知"),
        snapshot_at=record.occurred_at,
        attributes=_rest(payload, _KNOWN_PURCHASE_ORDER_KEYS),
    )
    await _upsert(sess, PurchaseOrder, values, pk="po_id", object_id=object_id)
    await sess.flush()


async def _project_inventory(
    sess: AsyncSession, tenant_id: UUID, record: SourceRecord, object_id: UUID
) -> None:
    payload = record.payload
    values = dict(
        inv_id=object_id,
        tenant_id=tenant_id,
        material_id=await resolve_object_id(
            sess, tenant_id, "MATERIAL", payload.get("material_code", "")
        ),
        warehouse=payload.get("warehouse"),
        quantity_available=_decimal(payload.get("available")) or Decimal(0),
        quantity_reserved=_decimal(payload.get("reserved")) or Decimal(0),
        snapshot_at=record.occurred_at,
        attributes=_rest(payload, _KNOWN_INVENTORY_KEYS),
    )
    await _upsert(sess, Inventory, values, pk="inv_id", object_id=object_id)
    await sess.flush()


async def _project_bom(
    sess: AsyncSession, tenant_id: UUID, record: SourceRecord, object_id: UUID
) -> None:
    payload = record.payload
    values = dict(
        bom_id=object_id,
        tenant_id=tenant_id,
        product_id=await resolve_object_id(
            sess, tenant_id, "PRODUCT", payload.get("product_code", "")
        ),
        version=payload.get("bom_version"),
        status=payload.get("status", "ACTIVE"),
    )
    await _upsert(sess, Bom, values, pk="bom_id", object_id=object_id)
    await sess.execute(
        delete(BomItem).where(BomItem.tenant_id == tenant_id, BomItem.bom_id == object_id)
    )
    for idx, item in enumerate(payload.get("items") or []):
        sess.add(
            BomItem(
                item_id=uuid5(object_id, f"item:{idx}"),
                tenant_id=tenant_id,
                bom_id=object_id,
                material_id=await resolve_object_id(
                    sess, tenant_id, "MATERIAL", item.get("material_code", "")
                ),
                quantity=_decimal(item.get("quantity")),
                position=idx,
            )
        )
    await sess.flush()


async def _project_supplier_lead_time(
    sess: AsyncSession, tenant_id: UUID, record: SourceRecord, object_id: UUID
) -> None:
    payload = record.payload
    supplier_id = await resolve_object_id(
        sess, tenant_id, "SUPPLIER", payload.get("supplier_code", "")
    )
    material_id = await resolve_object_id(
        sess, tenant_id, "MATERIAL", payload.get("material_code", "")
    )
    lead_time_days = payload.get("lead_time_days")
    existing = (
        await sess.execute(
            select(SupplierLeadTime).where(
                SupplierLeadTime.tenant_id == tenant_id,
                SupplierLeadTime.supplier_id == supplier_id,
                SupplierLeadTime.material_id == material_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        sess.add(
            SupplierLeadTime(
                id=uuid5(object_id, "lead"),
                tenant_id=tenant_id,
                supplier_id=supplier_id,
                material_id=material_id,
                lead_time_days=lead_time_days,
                updated_at=record.occurred_at,
            )
        )
    else:
        if lead_time_days is not None:
            existing.lead_time_days = lead_time_days
        existing.updated_at = record.occurred_at
    await sess.flush()


async def _project_project(
    sess: AsyncSession, tenant_id: UUID, record: SourceRecord, object_id: UUID
) -> None:
    payload = record.payload
    values = dict(
        project_id=object_id,
        tenant_id=tenant_id,
        project_no=record.source_id,
        product_id=await resolve_object_id(
            sess, tenant_id, "PRODUCT", payload.get("product_code", "")
        ),
        status=payload.get("status", "未知"),
        stage=payload.get("stage"),
        readiness_level=payload.get("readiness_level"),
        snapshot_at=record.occurred_at,
        attributes=_rest(payload, _KNOWN_PROJECT_KEYS),
    )
    await _upsert(sess, RdProject, values, pk="project_id", object_id=object_id)
    await sess.execute(
        delete(RdMilestone).where(
            RdMilestone.tenant_id == tenant_id, RdMilestone.project_id == object_id
        )
    )
    for idx, milestone in enumerate(payload.get("milestones") or []):
        sess.add(
            RdMilestone(
                milestone_id=uuid5(object_id, f"milestone:{idx}"),
                tenant_id=tenant_id,
                project_id=object_id,
                name=milestone.get("name", ""),
                due_date=_parse_dt(milestone.get("due_date")),
                actual_date=_parse_dt(milestone.get("actual_date")),
                status=milestone.get("status", "PENDING"),
            )
        )
    await sess.flush()


async def _project_capacity(
    sess: AsyncSession, tenant_id: UUID, record: SourceRecord, object_id: UUID
) -> None:
    """产能快照投影（delivery.capacity；EDP-017 剩余，MES 源）。

    行粒度 =（产线, 周期, 快照时刻），id=uuid5(object_id,"cap") 随对象稳定；
    `_upsert` 原地更新（同对象重投影不新增行）。
    """
    payload = record.payload
    values = dict(
        id=uuid5(object_id, "cap"),
        tenant_id=tenant_id,
        product_line=payload.get("product_line", ""),
        period=payload.get("period", ""),
        capacity_qty=_decimal(payload.get("capacity_qty")) or Decimal(0),
        snapshot_at=record.occurred_at,
    )
    await _upsert(sess, Capacity, values, pk="id", object_id=values["id"])
    await sess.flush()


Projector = Callable[[AsyncSession, UUID, SourceRecord, UUID], Awaitable[None]]

_PROJECTORS: dict[str, Projector] = {
    "CUSTOMER": _project_customer,
    "MATERIAL": _project_material,
    "PRODUCT": _project_product,
    "SUPPLIER": _project_supplier,
    "ORDER": _project_order,
    "PURCHASE_ORDER": _project_purchase_order,
    "INVENTORY": _project_inventory,
    "BOM": _project_bom,
    "SUPPLIER_LEAD_TIME": _project_supplier_lead_time,
    "PROJECT": _project_project,
    "CAPACITY": _project_capacity,
}


async def project_record(
    sess: AsyncSession, tenant_id: UUID, record: SourceRecord, object_id: UUID
) -> None:
    """按 object_type 分派投影器；未知类型静默跳过（通用对象无投影）。"""
    projector = _PROJECTORS.get(record.object_type)
    if projector is not None:
        await projector(sess, tenant_id, record, object_id)


# ---- tools 查询口（join master 主数据表；未命中 None/[]） ----
#
# 返回值视图 dataclass 内含领域 ORM 行 + 解析后的 code（tools 模块无需触碰
# 领域 ORM 结构即可按 B.8 组装响应）；查询显式带 tenant_id（RLS 双保险）。


@dataclass(slots=True, frozen=True)
class OrderLineView:
    """订单行视图：行记录 + 解析后的产品/物料 code（二选一或并存）。"""

    line: SalesOrderLine
    product_code: str | None
    material_code: str | None


@dataclass(slots=True, frozen=True)
class OrderView:
    """订单视图：订单 + 客户主数据（未解析为 None）+ 行明细（列表摘要为空）。"""

    order: SalesOrder
    customer: Customer | None
    lines: tuple[OrderLineView, ...] = ()


@dataclass(slots=True, frozen=True)
class InventoryView:
    """库存视图：物料主数据 + （物料, 仓库）粒度快照行列表。"""

    material: Material
    warehouses: tuple[Inventory, ...]


@dataclass(slots=True, frozen=True)
class PurchaseOrderView:
    """采购单视图：采购单 + 供应商主数据（未解析为 None）。"""

    po: PurchaseOrder
    supplier: Supplier | None


@dataclass(slots=True, frozen=True)
class BomItemView:
    """BOM 行视图：行记录 + 物料主数据（未解析为 None）。"""

    item: BomItem
    material: Material | None


@dataclass(slots=True, frozen=True)
class BomView:
    """BOM 视图：BOM 头 + 产品主数据 + 行明细。"""

    bom: Bom
    product: Product
    items: tuple[BomItemView, ...]


@dataclass(slots=True, frozen=True)
class LeadTimeView:
    """交期视图：交期行 + 物料主数据（未解析为 None）。"""

    lead_time: SupplierLeadTime
    material: Material | None


@dataclass(slots=True, frozen=True)
class LeadTimesView:
    """供应商交期视图：供应商主数据 + 交期行列表。"""

    supplier: Supplier
    items: tuple[LeadTimeView, ...]


async def get_order_by_no(
    sess: AsyncSession, tenant_id: UUID, order_no: str
) -> OrderView | None:
    """订单详情（含行明细与客户主数据）；未命中 → None。"""
    row = (
        await sess.execute(
            select(SalesOrder, Customer)
            .join_from(
                SalesOrder,
                Customer,
                and_(
                    Customer.tenant_id == SalesOrder.tenant_id,
                    Customer.customer_id == SalesOrder.customer_id,
                ),
                isouter=True,
            )
            .where(SalesOrder.tenant_id == tenant_id, SalesOrder.order_no == order_no)
        )
    ).first()
    if row is None:
        return None
    order, customer = row
    return OrderView(
        order=order,
        customer=customer,
        lines=tuple(await _order_lines(sess, tenant_id, order.order_id)),
    )


async def _order_lines(
    sess: AsyncSession, tenant_id: UUID, order_id: UUID
) -> list[OrderLineView]:
    rows = (
        await sess.execute(
            select(SalesOrderLine, Product.code, Material.code)
            .join_from(
                SalesOrderLine,
                Product,
                and_(
                    Product.tenant_id == SalesOrderLine.tenant_id,
                    Product.product_id == SalesOrderLine.product_id,
                ),
                isouter=True,
            )
            .join_from(
                SalesOrderLine,
                Material,
                and_(
                    Material.tenant_id == SalesOrderLine.tenant_id,
                    Material.material_id == SalesOrderLine.material_id,
                ),
                isouter=True,
            )
            .where(
                SalesOrderLine.tenant_id == tenant_id,
                SalesOrderLine.order_id == order_id,
            )
            .order_by(SalesOrderLine.line_id)
        )
    ).all()
    return [
        OrderLineView(line=line, product_code=product_code, material_code=material_code)
        for line, product_code, material_code in rows
    ]


async def list_orders(
    sess: AsyncSession,
    tenant_id: UUID,
    *,
    customer_code: str | None = None,
    status: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[OrderView]:
    """订单摘要列表（不含行明细）：客户 code / 状态过滤；未命中 → []。"""
    limit = max(1, min(limit, MAX_LIMIT))
    stmt = select(SalesOrder, Customer).join_from(
        SalesOrder,
        Customer,
        and_(
            Customer.tenant_id == SalesOrder.tenant_id,
            Customer.customer_id == SalesOrder.customer_id,
        ),
        isouter=True,
    )
    if customer_code:
        stmt = stmt.where(Customer.code == customer_code)
    if status:
        stmt = stmt.where(SalesOrder.status == status)
    rows = (
        await sess.execute(
            stmt.where(SalesOrder.tenant_id == tenant_id)
            .order_by(SalesOrder.order_no)
            .limit(limit)
        )
    ).all()
    return [OrderView(order=order, customer=customer) for order, customer in rows]


async def list_inventory_by_material_code(
    sess: AsyncSession, tenant_id: UUID, material_code: str
) -> InventoryView | None:
    """物料库存（warehouses 按仓库粒度）；物料不存在 → None（无库存行 → 空列表）。"""
    material = (
        await sess.execute(
            select(Material).where(
                Material.tenant_id == tenant_id, Material.code == material_code
            )
        )
    ).scalar_one_or_none()
    if material is None:
        return None
    rows = (
        (
            await sess.execute(
                select(Inventory)
                .where(
                    Inventory.tenant_id == tenant_id,
                    Inventory.material_id == material.material_id,
                )
                .order_by(Inventory.warehouse.asc().nulls_last(), Inventory.inv_id)
            )
        )
        .scalars()
        .all()
    )
    return InventoryView(material=material, warehouses=tuple(rows))


async def list_purchase_orders(
    sess: AsyncSession,
    tenant_id: UUID,
    *,
    material_code: str | None = None,
    status: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[PurchaseOrderView]:
    """采购单列表：物料 code / 状态过滤；未命中 → []。"""
    limit = max(1, min(limit, MAX_LIMIT))
    stmt = (
        select(PurchaseOrder, Supplier)
        .join_from(
            PurchaseOrder,
            Supplier,
            and_(
                Supplier.tenant_id == PurchaseOrder.tenant_id,
                Supplier.supplier_id == PurchaseOrder.supplier_id,
            ),
            isouter=True,
        )
        .join_from(
            PurchaseOrder,
            Material,
            and_(
                Material.tenant_id == PurchaseOrder.tenant_id,
                Material.material_id == PurchaseOrder.material_id,
            ),
            isouter=True,
        )
    )
    if material_code:
        stmt = stmt.where(Material.code == material_code)
    if status:
        stmt = stmt.where(PurchaseOrder.status == status)
    rows = (
        await sess.execute(
            stmt.where(PurchaseOrder.tenant_id == tenant_id)
            .order_by(
                PurchaseOrder.expected_date.asc().nulls_last(), PurchaseOrder.po_no
            )
            .limit(limit)
        )
    ).all()
    return [PurchaseOrderView(po=po, supplier=supplier) for po, supplier in rows]


async def get_active_bom(
    sess: AsyncSession, tenant_id: UUID, product_code: str
) -> BomView | None:
    """产品 ACTIVE BOM（多版本取 version 降序首条）；未命中 → None。"""
    row = (
        await sess.execute(
            select(Bom, Product)
            .join_from(
                Bom,
                Product,
                and_(
                    Product.tenant_id == Bom.tenant_id,
                    Product.product_id == Bom.product_id,
                ),
            )
            .where(
                Bom.tenant_id == tenant_id,
                Product.code == product_code,
                Bom.status == "ACTIVE",
            )
            .order_by(Bom.version.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    bom, product = row
    item_rows = (
        await sess.execute(
            select(BomItem, Material)
            .join_from(
                BomItem,
                Material,
                and_(
                    Material.tenant_id == BomItem.tenant_id,
                    Material.material_id == BomItem.material_id,
                ),
                isouter=True,
            )
            .where(BomItem.tenant_id == tenant_id, BomItem.bom_id == bom.bom_id)
            .order_by(BomItem.position.asc().nulls_last(), BomItem.item_id)
        )
    ).all()
    return BomView(
        bom=bom,
        product=product,
        items=tuple(BomItemView(item=item, material=material) for item, material in item_rows),
    )


async def list_lead_times(
    sess: AsyncSession, tenant_id: UUID, supplier_code: str
) -> LeadTimesView | None:
    """供应商交期列表（按物料 code 升序）；供应商不存在 → None。"""
    supplier = (
        await sess.execute(
            select(Supplier).where(
                Supplier.tenant_id == tenant_id, Supplier.code == supplier_code
            )
        )
    ).scalar_one_or_none()
    if supplier is None:
        return None
    rows = (
        await sess.execute(
            select(SupplierLeadTime, Material)
            .join_from(
                SupplierLeadTime,
                Material,
                and_(
                    Material.tenant_id == SupplierLeadTime.tenant_id,
                    Material.material_id == SupplierLeadTime.material_id,
                ),
                isouter=True,
            )
            .where(
                SupplierLeadTime.tenant_id == tenant_id,
                SupplierLeadTime.supplier_id == supplier.supplier_id,
            )
            .order_by(Material.code.asc().nulls_last(), SupplierLeadTime.id)
        )
    ).all()
    return LeadTimesView(
        supplier=supplier,
        items=tuple(
            LeadTimeView(lead_time=lead_time, material=material)
            for lead_time, material in rows
        ),
    )


async def get_customer_by_code(
    sess: AsyncSession, tenant_id: UUID, code: str
) -> Customer | None:
    """客户主数据（自然键 = tenant + code）；未命中 → None。"""
    return (
        await sess.execute(
            select(Customer).where(Customer.tenant_id == tenant_id, Customer.code == code)
        )
    ).scalar_one_or_none()
