import { apiClient } from "../auth/api";
import type { Schemas } from "../../mocks/types";

const BASE = "/api/v1";

// SDK 生成类型单点（B.8 六接口契约冻结）
export type OrderDetail = Schemas["OrderDetail"];
export type OrderSummary = Schemas["OrderSummary"];
export type InventoryResponse = Schemas["InventoryResponse"];
export type BomResponse = Schemas["BomResponse"];
export type PurchaseOrderListResponse = Schemas["PurchaseOrderListResponse"];
export type SupplierLeadTimesResponse = Schemas["SupplierLeadTimesResponse"];
export type CustomerResponse = Schemas["CustomerResponse"];
export type EvidenceHint = Schemas["EvidenceHint"];

/** 工具查询键：接口 → 动态输入字段（label/placeholder 按契约参数名提示）。 */
export interface ToolField {
  key: string;
  label: string;
  placeholder: string;
  required: boolean;
}

export interface ToolDef {
  /** 稳定 value（select 用）。 */
  value: string;
  label: string;
  description: string;
  fields: ToolField[];
  /** 按字段值组装请求 URL（相对 BASE）。 */
  url: (values: Record<string, string>) => string;
}

/** B.8 六只读工具清单（页头 chips 与试查下拉共用；参数名逐字对齐契约）。 */
export const TOOL_DEFS: ToolDef[] = [
  {
    value: "order_detail",
    label: "订单详情",
    description: "订单（含行明细与客户）",
    fields: [{ key: "order_no", label: "订单号 order_no", placeholder: "如 SO-2026-00123", required: true }],
    url: (v) => `/tools/orders/${encodeURIComponent(v.order_no ?? "")}`,
  },
  {
    value: "inventory",
    label: "物料库存",
    description: "物料库存（仓库粒度 + 合计可用）",
    fields: [{ key: "material_code", label: "物料 code material_code", placeholder: "如 X-100", required: true }],
    url: (v) => `/tools/inventory?material_code=${encodeURIComponent(v.material_code ?? "")}`,
  },
  {
    value: "purchase_orders",
    label: "采购单列表",
    description: "采购单（material/status 过滤）",
    fields: [
      { key: "material_code", label: "物料 code material_code", placeholder: "如 X-100", required: false },
      { key: "status", label: "状态 status", placeholder: "如 在途", required: false },
    ],
    url: (v) => {
      const q = new URLSearchParams();
      if (v.material_code) q.set("material_code", v.material_code);
      if (v.status) q.set("status", v.status);
      const s = q.toString();
      return `/tools/purchase-orders${s ? `?${s}` : ""}`;
    },
  },
  {
    value: "bom",
    label: "产品 BOM",
    description: "产品 BOM（ACTIVE 版本 + 用量行）",
    fields: [{ key: "product_code", label: "产品 code product_code", placeholder: "如 P-F", required: true }],
    url: (v) => `/tools/bom?product_code=${encodeURIComponent(v.product_code ?? "")}`,
  },
  {
    value: "supplier_lead_times",
    label: "供应商交期",
    description: "供应商交期（物料粒度）",
    fields: [{ key: "supplier_code", label: "供应商 code supplier_code", placeholder: "如 S-118", required: true }],
    url: (v) => `/tools/supplier-lead-times?supplier_code=${encodeURIComponent(v.supplier_code ?? "")}`,
  },
  {
    value: "customer",
    label: "客户主数据",
    description: "客户主数据（name/level/attributes）",
    fields: [{ key: "customer_code", label: "客户 code customer_code", placeholder: "如 C-008", required: true }],
    url: (v) => `/tools/customers/${encodeURIComponent(v.customer_code ?? "")}`,
  },
];

/** 试查执行：GET（mutation 触发，错误经 EdpApiError 交页面按 13.9.2 呈现）。 */
export function tryToolQuery(def: ToolDef, values: Record<string, string>): Promise<unknown> {
  return apiClient.get<unknown>(`${BASE}${def.url(values)}`);
}
