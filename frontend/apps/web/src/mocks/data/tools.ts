import type { Schemas } from "../types";
import { hoursBefore, iso } from "../lib/demo-time";
import {
  OBJ_CUSTOMER_C008,
  OBJ_MATERIAL_X100,
  OBJ_MATERIAL_Y200,
  OBJ_ORDER_B,
  OBJ_ORDER_H,
  OBJ_PO_00771,
  OBJ_PO_00785,
  OBJ_PRODUCT_PF,
  OBJ_SUPPLIER_S021,
  OBJ_SUPPLIER_S118,
} from "./ids";

/**
 * B.8 六只读工具 fixtures：业务键与 objects.ts 对齐（订单 B/物料 X·Y/产品 F/供应商
 * S-021·S-118/PO 00771·00785/客户 C-008），evidence_hint.object_id 指向既有对象
 * UUID——工具结果可回溯到对象域证据链（spec §4 跨页一致）。
 */

export const ORDER_B_NO = "SO-2026-00123";
export const MATERIAL_X = "X-100";
export const MATERIAL_Y = "Y-200";
export const PRODUCT_F = "P-F";
export const SUPPLIER_S021 = "S-021";
export const SUPPLIER_S118 = "S-118";
export const CUSTOMER_C008 = "C-008";

/** 订单 B 详情（B.8：含 lines 明细与客户；evidence_hint → 对象订单 B）。 */
export const orderBDetail: Schemas["OrderDetail"] = {
  order_no: ORDER_B_NO,
  object_id: OBJ_ORDER_B,
  status: "已确认",
  currency: "CNY",
  amount: 120000,
  order_date: "2026-09-12",
  delivery_date: "2026-10-15",
  customer: { code: CUSTOMER_C008, name: "某客户", level: "VIP" },
  lines: [
    { product_code: PRODUCT_F, material_code: MATERIAL_X, quantity: 500, unit_price: 240 },
    { material_code: MATERIAL_Y, quantity: 200, unit_price: 180 },
  ],
  evidence_hint: { object_id: OBJ_ORDER_B, event_id: null },
};

/** 订单摘要列表（customer/status 过滤源；同详情结构不含 lines）。 */
export const orderSummaries: Schemas["OrderSummary"][] = [
  {
    order_no: ORDER_B_NO,
    object_id: OBJ_ORDER_B,
    status: "已确认",
    currency: "CNY",
    amount: 120000,
    delivery_date: "2026-10-15",
    customer: { code: CUSTOMER_C008, name: "某客户", level: "VIP" },
    evidence_hint: { object_id: OBJ_ORDER_B, event_id: null },
  },
  {
    order_no: "SO-2026-00129",
    object_id: OBJ_ORDER_H,
    status: "已确认",
    currency: "CNY",
    amount: 450000,
    delivery_date: "2026-10-12",
    customer: { code: "C-015", name: "客户 C-015", level: "普通" },
    evidence_hint: { object_id: OBJ_ORDER_H, event_id: null },
  },
];

/** 物料库存（仓库粒度 + 合计可用；objects attrs.total_available 对齐）。 */
export const inventoryByMaterial: Record<string, Schemas["InventoryResponse"]> = {
  [MATERIAL_X]: {
    material_code: MATERIAL_X,
    material_id: OBJ_MATERIAL_X100,
    total_available: 3200,
    snapshot_at: hoursBefore(2),
    warehouses: [
      { warehouse: "WH-SH01", available: 2400, reserved: 600 },
      { warehouse: "WH-SH02", available: 1400, reserved: 200 },
    ],
    evidence_hint: { object_id: OBJ_MATERIAL_X100, event_id: null },
  },
  [MATERIAL_Y]: {
    material_code: MATERIAL_Y,
    material_id: OBJ_MATERIAL_Y200,
    total_available: 5400,
    snapshot_at: hoursBefore(3),
    warehouses: [
      { warehouse: "WH-SH01", available: 4600, reserved: 400 },
      { warehouse: "WH-SH03", available: 1200, reserved: 0 },
    ],
    evidence_hint: { object_id: OBJ_MATERIAL_Y200, event_id: null },
  },
};

/** 产品 F ACTIVE BOM（BOM 版本 + 用量行）。 */
export const bomByProduct: Record<string, Schemas["BomResponse"]> = {
  [PRODUCT_F]: {
    product_code: PRODUCT_F,
    bom_version: "V2",
    items: [
      { material_code: MATERIAL_X, quantity_per: 2 },
      { material_code: MATERIAL_Y, quantity_per: 1 },
    ],
    evidence_hint: { object_id: OBJ_PRODUCT_PF, event_id: null },
  },
};

/** 采购单列表（material_code/status 过滤源；在途 00771 / 推迟 00785）。 */
export const purchaseOrders: Schemas["PurchaseOrderItem"][] = [
  {
    po_no: "PO-2026-00771",
    object_id: OBJ_PO_00771,
    supplier_code: SUPPLIER_S021,
    status: "在途",
    quantity: 2000,
    expected_date: "2026-10-20",
    evidence_hint: { object_id: OBJ_PO_00771, event_id: null },
  },
  {
    po_no: "PO-2026-00785",
    object_id: OBJ_PO_00785,
    supplier_code: SUPPLIER_S118,
    status: "在途（推迟 2 周）",
    quantity: 1500,
    expected_date: "2026-10-12",
    evidence_hint: { object_id: OBJ_PO_00785, event_id: null },
  },
];

/** 供应商交期（S-118 延迟 14 天 = 场景 3 输入；S-021 常态 10 天）。 */
export const leadTimesBySupplier: Record<string, Schemas["SupplierLeadTimesResponse"]> = {
  [SUPPLIER_S118]: {
    supplier_code: SUPPLIER_S118,
    updated_at: iso("2026-09-27T10:00:00Z"),
    lead_times: [
      { material_code: MATERIAL_X, lead_time_days: 14 },
      { material_code: MATERIAL_Y, lead_time_days: 21 },
    ],
    evidence_hint: { object_id: OBJ_SUPPLIER_S118, event_id: null },
  },
  [SUPPLIER_S021]: {
    supplier_code: SUPPLIER_S021,
    updated_at: iso("2026-09-25T10:00:00Z"),
    lead_times: [{ material_code: MATERIAL_X, lead_time_days: 10 }],
    evidence_hint: { object_id: OBJ_SUPPLIER_S021, event_id: null },
  },
};

/** 客户主数据（C-008 VIP = 订单 B/G 客户）。 */
export const customerByCode: Record<string, Schemas["CustomerResponse"]> = {
  [CUSTOMER_C008]: {
    customer_code: CUSTOMER_C008,
    name: "某客户",
    level: "VIP",
    attributes: { region: "华东", credit_limit: 2000000, note: "交付窗口严格" },
    evidence_hint: { object_id: OBJ_CUSTOMER_C008, event_id: null },
  },
};
