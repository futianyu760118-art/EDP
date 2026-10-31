import type { Schemas } from "../types";
import { CAP_DQ_CHECK, CAP_ORDER_RISK, CAP_PRODUCT_READINESS } from "./traces";
import { mockUuid } from "./ids";

/**
 * W3R 能力注册 fixtures（B.7 简投影，GET /capabilities）：前三能力与 traces/memory
 * 演示数据共用 UUID（跨页筛选一致，spec §4）；第四能力（供应商延期监控）不挂轨迹，
 * 供三页下拉证明「选项来自接口」而非前端兜底常量。
 */
export const CAP_SUPPLIER_WATCH = mockUuid(804);

export const capabilityRows: Schemas["CapabilityListItem"][] = [
  {
    capability_id: CAP_ORDER_RISK,
    name: "订单风险评估",
    domain: "delivery",
    risk_level: "L1",
    permission: "AUTO_ALLOWED",
    endpoint: null,
    owner: "supply-chain-team",
    status: "ACTIVE",
    created_at: "2026-09-01T08:00:00.000Z",
  },
  {
    capability_id: CAP_PRODUCT_READINESS,
    name: "产品就绪度",
    domain: "product",
    risk_level: "L1",
    permission: "AUTO_ALLOWED",
    endpoint: null,
    owner: "planning-team",
    status: "ACTIVE",
    created_at: "2026-09-02T08:00:00.000Z",
  },
  {
    capability_id: CAP_DQ_CHECK,
    name: "数据质量检查",
    domain: "quality",
    risk_level: "L0",
    permission: "READ_ONLY",
    endpoint: null,
    owner: "data-platform-team",
    status: "ACTIVE",
    created_at: "2026-09-03T08:00:00.000Z",
  },
  {
    capability_id: CAP_SUPPLIER_WATCH,
    name: "供应商延期监控",
    domain: "delivery",
    risk_level: "L2",
    permission: "HUMAN_ONLY",
    endpoint: null,
    owner: "procurement-team",
    status: "ACTIVE",
    created_at: "2026-09-04T08:00:00.000Z",
  },
];
