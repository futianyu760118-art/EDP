"""tools 响应模型（设计文档附录 B.8 逐字段；全 Read-Only，仅响应体）。

字段事实来源 = B.8 六接口示例：
- 订单详情/摘要：order_no/object_id/customer/amount/currency/status/order_date/
  delivery_date（详情 + lines）；行明细 B.8 示例仅 product_code，本模块补
  material_code 可空字段（演示数据集含物料直采行 X-100，缺此字段该行无法
  辨识——对 B.8 的字段超集，T14 契约导出时随路径一并冻结）；
- 库存：material_code/material_id/warehouses[]/total_available/snapshot_at；
- 采购：items[po_no/supplier_code/quantity/expected_date/status] + next_cursor；
- BOM：product_code/bom_version/items[material_code/quantity_per]；
- 交期：supplier_code/lead_times[material_code/lead_time_days]/updated_at；
- 客户：customer_code/name/level/attributes；
- 统一 evidence_hint {object_id, event_id}（无快照事件 → event_id=null，
  字段保留不裁剪）。

数值列用 float：B.8 为 JSON 数字，Decimal 在 Pydantic JSON 模式序列化为
字符串，故 service 组装时转 float。next_cursor 本轮固定 null——采购列表
游标分页与 429 同批留待 EDP-025 轮次（契约字段先占位）。
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class EvidenceHint(BaseModel):
    """关联对象/事件（该对象最新 {TYPE}_SNAPSHOT 事件；无则 event_id=null）。"""

    object_id: UUID
    event_id: UUID | None = None


class CustomerRef(BaseModel):
    """订单内嵌客户引用（B.8：code/name/level；主数据未解析 → 响应字段为 null）。"""

    code: str
    name: str
    level: str | None = None


class OrderLineItem(BaseModel):
    """订单行（product_code/material_code 二选一或并存）。"""

    product_code: str | None = None
    material_code: str | None = None
    quantity: float | None = None
    unit_price: float | None = None


class OrderSummary(BaseModel):
    """订单摘要（B.8 订单结构，不含 lines 明细）。"""

    order_no: str
    object_id: UUID
    customer: CustomerRef | None = None
    amount: float | None = None
    currency: str
    status: str
    order_date: datetime | None = None
    delivery_date: datetime | None = None
    evidence_hint: EvidenceHint


class OrderDetail(OrderSummary):
    """订单详情（B.8：摘要结构 + lines 行明细）。"""

    lines: list[OrderLineItem]


class OrderListResponse(BaseModel):
    """GET /tools/orders 响应（摘要列表；游标分页字段占位）。"""

    items: list[OrderSummary]
    next_cursor: str | None = None


class WarehouseItem(BaseModel):
    """库存仓库粒度快照（B.8：warehouse/available/reserved）。"""

    warehouse: str | None = None
    available: float
    reserved: float


class InventoryResponse(BaseModel):
    """GET /tools/inventory 响应（warehouses[] + total_available + snapshot_at）。"""

    material_code: str
    material_id: UUID
    warehouses: list[WarehouseItem]
    total_available: float
    snapshot_at: datetime | None = None
    evidence_hint: EvidenceHint


class PurchaseOrderItem(BaseModel):
    """采购单行（B.8：po_no/supplier_code/quantity/expected_date/status）。"""

    po_no: str
    object_id: UUID
    supplier_code: str | None = None
    quantity: float | None = None
    expected_date: datetime | None = None
    status: str
    evidence_hint: EvidenceHint


class PurchaseOrderListResponse(BaseModel):
    """GET /tools/purchase-orders 响应（items + next_cursor）。"""

    items: list[PurchaseOrderItem]
    next_cursor: str | None = None


class BomItemResponse(BaseModel):
    """BOM 行（B.8：material_code/quantity_per——quantity_per 即用量）。"""

    material_code: str | None = None
    quantity_per: float | None = None


class BomResponse(BaseModel):
    """GET /tools/bom 响应（product_code/bom_version/items[]）。"""

    product_code: str
    bom_version: str | None = None
    items: list[BomItemResponse]
    evidence_hint: EvidenceHint


class LeadTimeItem(BaseModel):
    """供应商交期行（B.8：material_code/lead_time_days）。"""

    material_code: str | None = None
    lead_time_days: int | None = None


class SupplierLeadTimesResponse(BaseModel):
    """GET /tools/supplier-lead-times 响应（lead_times[] + updated_at）。"""

    supplier_code: str
    lead_times: list[LeadTimeItem]
    updated_at: datetime | None = None
    evidence_hint: EvidenceHint


class SearchObjectItem(BaseModel):
    """search-objects 结果项（T33）：对象标识 + 属性。"""

    object_id: UUID
    object_type: str
    source_system: str
    source_id: str
    attributes: dict[str, Any]


class SearchObjectsResponse(BaseModel):
    items: list[SearchObjectItem]


class CustomerResponse(BaseModel):
    """GET /tools/customers/{code} 响应（name/level/attributes）。"""

    customer_code: str
    name: str
    level: str | None = None
    attributes: dict[str, Any]
    evidence_hint: EvidenceHint
