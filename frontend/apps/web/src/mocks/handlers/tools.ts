import { http, HttpResponse } from "msw";
import { errorOf } from "../lib/http";
import { scenarioResponse } from "../lib/scenario";
import {
  bomByProduct,
  customerByCode,
  inventoryByMaterial,
  leadTimesBySupplier,
  orderBDetail,
  purchaseOrders,
} from "../data/tools";

/**
 * B.8 六只读工具 GET 端点（W3R 已有契约）：对象级点查（订单详情/客户主数据）+
 * 查询参数取数（库存/BOM/交期必填 code，采购单可选 material/status 过滤）；
 * 未命中统一 404 NOT_FOUND 不泄露存在性（13.9.2）。
 */

export const toolHandlers = [
  // 订单详情：GET /tools/orders/{order_no}
  http.get("*/api/v1/tools/orders/:orderNo", ({ params, request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    if (String(params.orderNo) === orderBDetail.order_no) return HttpResponse.json(orderBDetail);
    return errorOf("NOT_FOUND", "资源不存在", 404);
  }),

  // 物料库存：GET /tools/inventory?material_code=（必填；物料不存在 → 404）
  http.get("*/api/v1/tools/inventory", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const code = new URL(request.url).searchParams.get("material_code");
    if (!code) return errorOf("VALIDATION_ERROR", "material_code 必填", 422);
    const found = inventoryByMaterial[code];
    if (found) return HttpResponse.json(found);
    return errorOf("NOT_FOUND", "资源不存在", 404);
  }),

  // 采购单列表：GET /tools/purchase-orders?material_code=&status=（可选过滤）
  http.get("*/api/v1/tools/purchase-orders", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const q = new URL(request.url).searchParams;
    const material = q.get("material_code");
    const status = q.get("status");
    const items = purchaseOrders.filter((po) => {
      if (material === "X-100" && po.po_no !== "PO-2026-00771") return false;
      if (material === "Y-200" && po.po_no !== "PO-2026-00785") return false;
      if (material && !["X-100", "Y-200"].includes(material)) return false;
      if (status && !po.status.includes(status)) return false;
      return true;
    });
    return HttpResponse.json({ items, next_cursor: null });
  }),

  // 产品 BOM：GET /tools/bom?product_code=（必填；产品/版本不存在 → 404）
  http.get("*/api/v1/tools/bom", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const code = new URL(request.url).searchParams.get("product_code");
    if (!code) return errorOf("VALIDATION_ERROR", "product_code 必填", 422);
    const found = bomByProduct[code];
    if (found) return HttpResponse.json(found);
    return errorOf("NOT_FOUND", "资源不存在", 404);
  }),

  // 供应商交期：GET /tools/supplier-lead-times?supplier_code=（必填；无行 → 200 空）
  http.get("*/api/v1/tools/supplier-lead-times", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const code = new URL(request.url).searchParams.get("supplier_code");
    if (!code) return errorOf("VALIDATION_ERROR", "supplier_code 必填", 422);
    const found = leadTimesBySupplier[code];
    if (found) return HttpResponse.json(found);
    return errorOf("NOT_FOUND", "资源不存在", 404);
  }),

  // 客户主数据：GET /tools/customers/{customer_code}
  http.get("*/api/v1/tools/customers/:customerCode", ({ params, request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const found = customerByCode[String(params.customerCode)];
    if (found) return HttpResponse.json(found);
    return errorOf("NOT_FOUND", "资源不存在", 404);
  }),
];
