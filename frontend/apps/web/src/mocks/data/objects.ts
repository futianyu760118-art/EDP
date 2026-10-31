import type { ObjectResponse } from "../types";
import { daysBefore, hoursBefore } from "../lib/demo-time";
import {
  OBJ_CUSTOMER_C008, OBJ_CUSTOMER_C030A, OBJ_CUSTOMER_C030B, OBJ_MATERIAL_X100, OBJ_MATERIAL_Y200,
  OBJ_ORDER_A, OBJ_ORDER_B, OBJ_ORDER_C, OBJ_ORDER_E, OBJ_ORDER_G, OBJ_ORDER_H, OBJ_ORDER_I,
  OBJ_ORDER_J, OBJ_ORDER_R1, OBJ_ORDER_R2, OBJ_PO_00771, OBJ_PO_00785, OBJ_PRODUCT_PD,
  OBJ_PRODUCT_PF, OBJ_PROJECT_PRJD, OBJ_SUPPLIER_S021, OBJ_SUPPLIER_S118, OBJ_SUPPLIER_S030,
  TENANT_ID,
} from "./ids";

interface ObjectSeed {
  id: string;
  type: string;
  domain: string;
  source?: string;
  sourceId: string;
  name: string;
  revision?: number;
  attrs?: Record<string, unknown>;
  updatedHoursAgo?: number;
}

function obj(seed: ObjectSeed): ObjectResponse {
  return {
    object_id: seed.id,
    tenant_id: TENANT_ID,
    object_type: seed.type,
    owner_domain: seed.domain,
    source_system: seed.source ?? "erp",
    source_id: seed.sourceId,
    revision: seed.revision ?? 1,
    status: "ACTIVE",
    merged_into: null,
    attributes: { name: seed.name, ...(seed.attrs ?? {}) },
    created_at: daysBefore(21),
    updated_at: hoursBefore(seed.updatedHoursAgo ?? 6),
  };
}

/** 23 个业务对象：订单 10（场景 1~9 输入侧 + 2 常规）+ 客户/物料/产品/供应商/PO/研发项目（spec §4）。 */
export const objects: ObjectResponse[] = [
  obj({ id: OBJ_ORDER_A, type: "ORDER", domain: "sales", sourceId: "SO-2026-00122", name: "订单 A · 常规", revision: 2, attrs: { customer_code: "C-012", amount: 86000, currency: "CNY", status: "已确认", delivery_date: "2026-10-15" } }),
  obj({ id: OBJ_ORDER_B, type: "ORDER", domain: "sales", sourceId: "SO-2026-00123", name: "订单 B · 关键料缺失", revision: 7, updatedHoursAgo: 2, attrs: { customer_code: "C-008", amount: 120000, currency: "CNY", status: "已确认", delivery_date: "2026-10-15", risk_note: "物料X缺口1000" } }),
  obj({ id: OBJ_ORDER_C, type: "ORDER", domain: "sales", sourceId: "SO-2026-00124", name: "订单 C · 供应商延迟", revision: 3, attrs: { customer_code: "C-015", amount: 64000, currency: "CNY", status: "已确认", delivery_date: "2026-10-18" } }),
  obj({ id: OBJ_ORDER_R1, type: "ORDER", domain: "sales", sourceId: "SO-2026-00125", name: "订单 · 常规", attrs: { customer_code: "C-021", amount: 38000, currency: "CNY", status: "已确认", delivery_date: "2026-10-22" } }),
  obj({ id: OBJ_ORDER_E, type: "ORDER", domain: "sales", sourceId: "SO-2026-00126", name: "订单 E · 高值低库存", revision: 4, updatedHoursAgo: 3, attrs: { customer_code: "C-012", amount: 980000, currency: "CNY", status: "已确认", delivery_date: "2026-10-10", product: "P-F" } }),
  obj({ id: OBJ_ORDER_R2, type: "ORDER", domain: "sales", sourceId: "SO-2026-00127", name: "订单 · 常规", attrs: { customer_code: "C-033", amount: 51000, currency: "CNY", status: "已确认", delivery_date: "2026-10-25" } }),
  obj({ id: OBJ_ORDER_G, type: "ORDER", domain: "sales", sourceId: "SO-2026-00128", name: "订单 G · VIP 客户", revision: 2, attrs: { customer_code: "C-008", amount: 260000, currency: "CNY", status: "已确认", delivery_date: "2026-10-08", condition: "交付窗口严格" } }),
  obj({ id: OBJ_ORDER_H, type: "ORDER", domain: "sales", sourceId: "SO-2026-00129", name: "订单 H · 组合风险", revision: 5, updatedHoursAgo: 4, attrs: { customer_code: "C-015", amount: 450000, currency: "CNY", status: "已确认", delivery_date: "2026-10-12", risk_note: "部分物料短缺+产能紧张" } }),
  obj({ id: OBJ_ORDER_I, type: "ORDER", domain: "sales", sourceId: "SO-2026-00130", name: "订单 I · 数据不一致", revision: 2, attrs: { customer_code: "C-030", amount: 72000, currency: "CNY", status: "已确认", delivery_date: "2026-10-20" } }),
  obj({ id: OBJ_ORDER_J, type: "ORDER", domain: "sales", sourceId: "SO-2026-00131", name: "订单 J · 供应商交叉", revision: 3, attrs: { customer_code: "C-021", amount: 155000, currency: "CNY", status: "已确认", delivery_date: "2026-11-05", suppliers: ["S-021", "S-030"] } }),
  obj({ id: OBJ_CUSTOMER_C008, type: "CUSTOMER", domain: "master", source: "mdm", sourceId: "C-008", name: "某客户", attrs: { level: "VIP" } }),
  obj({ id: OBJ_CUSTOMER_C030A, type: "CUSTOMER", domain: "master", sourceId: "C-030", name: "宏达精密", attrs: { level: "普通" } }),
  obj({ id: OBJ_CUSTOMER_C030B, type: "CUSTOMER", domain: "master", sourceId: "C-030-B", name: "宏达精密", attrs: { level: "普通", note: "ERP 双记录（场景 8）" } }),
  obj({ id: OBJ_MATERIAL_X100, type: "MATERIAL", domain: "master", sourceId: "X-100", name: "物料 X-100", revision: 3, attrs: { total_available: 3200, reserved: 800, unit: "件" } }),
  obj({ id: OBJ_MATERIAL_Y200, type: "MATERIAL", domain: "master", sourceId: "Y-200", name: "物料 Y-200", revision: 2, attrs: { total_available: 5400, reserved: 400, unit: "件" } }),
  obj({ id: OBJ_PRODUCT_PF, type: "PRODUCT", domain: "master", source: "plm", sourceId: "P-F", name: "产品 F", attrs: { stage: "量产", available: 38 } }),
  obj({ id: OBJ_PRODUCT_PD, type: "PRODUCT", domain: "master", source: "plm", sourceId: "P-D", name: "产品 D（新品）", attrs: { stage: "验证中" } }),
  obj({ id: OBJ_SUPPLIER_S021, type: "SUPPLIER", domain: "procurement", sourceId: "S-021", name: "供应商 S-021", attrs: { lead_time_days: 10 } }),
  obj({ id: OBJ_SUPPLIER_S118, type: "SUPPLIER", domain: "procurement", sourceId: "S-118", name: "供应商 S-118", revision: 2, attrs: { lead_time_days: 14, note: "预计交期延迟 14 天" } }),
  obj({ id: OBJ_SUPPLIER_S030, type: "SUPPLIER", domain: "procurement", sourceId: "S-030", name: "供应商 S-030", revision: 2, attrs: { status: "即将停产", effective_date: "2026-11-01" } }),
  obj({ id: OBJ_PO_00771, type: "PURCHASE_ORDER", domain: "procurement", sourceId: "PO-2026-00771", name: "在途采购 · X-100×2000", revision: 2, attrs: { supplier_code: "S-021", material_code: "X-100", quantity: 2000, expected_date: "2026-10-20", status: "在途" } }),
  obj({ id: OBJ_PO_00785, type: "PURCHASE_ORDER", domain: "procurement", sourceId: "PO-2026-00785", name: "在途采购 · Y-200×1500", revision: 3, attrs: { supplier_code: "S-118", material_code: "Y-200", quantity: 1500, expected_date: "2026-10-12", status: "在途（推迟 2 周）" } }),
  obj({ id: OBJ_PROJECT_PRJD, type: "PROJECT", domain: "rd", source: "plm", sourceId: "PRJ-D", name: "产品 D 研发项目", revision: 4, attrs: { status: "验证中", product: "P-D" } }),
];

export function findObject(id: string): ObjectResponse | undefined {
  return objects.find((o) => o.object_id === id);
}
