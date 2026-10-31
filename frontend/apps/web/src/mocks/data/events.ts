import type { EventResponse } from "../types";
import { daysBefore, hoursBefore, minutesBefore } from "../lib/demo-time";
import { objects } from "./objects";
import { EVID_ORDER_I_DUAL } from "./ids";
import {
  EVT_ADAPTER_PLM_FAILED, EVT_CASE_B_CREATED, EVT_ORDER_A_RISK, EVT_ORDER_B_RISK, EVT_ORDER_C_RISK,
  EVT_ORDER_E_RISK, EVT_ORDER_G_RISK, EVT_ORDER_H_RISK, EVT_ORDER_I_DQ, EVT_ORDER_J_RISK,
  EVT_PRJD_READINESS, EVT_QUALITY_CHECKSUM_FAIL, EVT_QUALITY_RECHECK_OK, EVT_QUALITY_REINDEX_MISMATCH,
  EVT_QUALITY_REINDEX_OK, OBJ_ORDER_A, OBJ_ORDER_B, OBJ_ORDER_C, OBJ_ORDER_E, OBJ_ORDER_G, OBJ_ORDER_H,
  OBJ_ORDER_I, OBJ_ORDER_J, OBJ_ORDER_R1, OBJ_ORDER_R2, OBJ_PROJECT_PRJD, TENANT_ID, mockUuid,
} from "./ids";

type RiskLevel = "P0" | "P1" | "P2" | "P3" | null;
type DeliveryStatus = "DELIVERED" | "PENDING" | "DEAD_LETTER";

/** object_id → source_id 反查（object_source_id 展示列，B.3/§6.2）。 */
const objectSourceIds = new Map(objects.map((o) => [o.object_id, o.source_id]));

interface EventSeed {
  id: string;
  type: string;
  objectId: string;
  source: string;
  occurredAt: string;
  actorType?: "HUMAN" | "SERVICE" | "AI";
  actorId?: string;
  resultType?: string | null;
  risk?: RiskLevel;
  score?: number | null;
  data?: Record<string, unknown>;
  latencyMs?: number;
  deliveryStatus?: DeliveryStatus;
}

/** 接入耗时确定性回填：mockUuid 序号派生 60~299ms（对齐后端 seed `60 + hash % 240` 口径）。 */
function latencyOf(id: string): number {
  const seq = Number(id.slice(-12));
  return 60 + (Number.isFinite(seq) ? seq % 240 : 0);
}

function evt(seed: EventSeed): EventResponse {
  return {
    event_id: seed.id,
    tenant_id: TENANT_ID,
    event_type: seed.type,
    object_id: seed.objectId,
    source_system: seed.source,
    occurred_at: seed.occurredAt,
    actor_type: seed.actorType ?? "SERVICE",
    actor_id: seed.actorId ?? "adapter:erp",
    result_type: seed.resultType ?? null,
    risk_level: seed.risk ?? null,
    score: seed.score ?? null,
    data: seed.data ?? {},
    idempotency_key: null,
    ingest_latency_ms: seed.latencyMs ?? latencyOf(seed.id),
    delivery_status: seed.deliveryStatus ?? "DELIVERED",
    object_source_id: objectSourceIds.get(seed.objectId) ?? null,
    created_at: seed.occurredAt,
  };
}

/** 订单例行事件（10 创建 + 5 确认 + 10 更新 + 3 交期变更），确定性生成。 */
const orderIds = [OBJ_ORDER_A, OBJ_ORDER_B, OBJ_ORDER_C, OBJ_ORDER_R1, OBJ_ORDER_E, OBJ_ORDER_R2, OBJ_ORDER_G, OBJ_ORDER_H, OBJ_ORDER_I, OBJ_ORDER_J];

const orderRoutineEvents: EventResponse[] = orderIds.flatMap((id, i) => {
  const rows: EventResponse[] = [
    evt({ id: mockUuid(500 + i * 4), type: "order.created", objectId: id, source: "erp", occurredAt: daysBefore(14 - i), actorId: "adapter:erp", data: { note: "订单创建" } }),
    evt({ id: mockUuid(501 + i * 4), type: "order.updated", objectId: id, source: "erp", occurredAt: daysBefore(9 - i * 0.8), actorId: "adapter:erp", data: { note: "主数据刷新" } }),
  ];
  if (i % 2 === 0) {
    rows.push(evt({ id: mockUuid(502 + i * 4), type: "order.confirmed", objectId: id, source: "erp", occurredAt: daysBefore(12 - i), actorType: "HUMAN", actorId: "user:sales_li", data: { note: "订单确认" } }));
  }
  if (i === 2 || i === 4 || i === 7) {
    rows.push(evt({ id: mockUuid(503 + i * 4), type: "order.delivery_date_changed", objectId: id, source: "erp", occurredAt: hoursBefore(30 - i), actorId: "adapter:erp", data: { note: "交期变更" } }));
  }
  return rows;
});

/** 库存例行事件 16 条（可用 8 + 占用 8）。 */
const inventoryRoutineEvents: EventResponse[] = Array.from({ length: 16 }, (_, i) =>
  evt({
    id: mockUuid(560 + i),
    type: "inventory.changed",
    objectId: i % 2 === 0 ? OBJ_ORDER_B : OBJ_ORDER_E,
    source: "erp",
    occurredAt: hoursBefore(1 + i * 0.5),
    actorId: "adapter:erp",
    data: { kind: i < 8 ? "available" : "reserved", delta: -(i % 3) * 50 - 20 },
  }),
);

/** 能力结果回流 + 场景关键事件（B.3 形状；L 系映射 P 系，shared enums）。 */
const capabilityEvents: EventResponse[] = [
  evt({ id: EVT_ORDER_A_RISK, type: "capability.result.order_risk", objectId: OBJ_ORDER_A, source: "agent-hub", occurredAt: hoursBefore(26), actorType: "AI", actorId: "agent:delivery-order-risk", resultType: "ORDER_RISK", risk: "P3", score: 0.08, data: { reason: "物料充足", recommendation: "无（正常）" } }),
  evt({ id: EVT_ORDER_B_RISK, type: "capability.result.order_risk", objectId: OBJ_ORDER_B, source: "agent-hub", occurredAt: hoursBefore(5), actorType: "AI", actorId: "agent:delivery-order-risk", resultType: "ORDER_RISK", risk: "P1", score: 0.86, data: { reason: "物料X缺口1000", recommendation: "加急采购/替代料", expected_delay_days: 5 } }),
  evt({ id: EVT_ORDER_C_RISK, type: "capability.result.order_risk", objectId: OBJ_ORDER_C, source: "agent-hub", occurredAt: hoursBefore(20), actorType: "AI", actorId: "agent:delivery-order-risk", resultType: "ORDER_RISK", risk: "P2", score: 0.64, data: { reason: "PO 预计到货推迟 2 周", recommendation: "确认交期，调整生产计划" } }),
  evt({ id: EVT_PRJD_READINESS, type: "capability.result.product_readiness", objectId: OBJ_PROJECT_PRJD, source: "agent-hub", occurredAt: hoursBefore(32), actorType: "AI", actorId: "agent:rd-product-readiness", resultType: "PRODUCT_READINESS", risk: "P2", score: 0.55, data: { readiness: "未达产", blocking: "完成验证与测试" } }),
  evt({ id: EVT_ORDER_E_RISK, type: "capability.result.order_quality", objectId: OBJ_ORDER_E, source: "agent-hub", occurredAt: hoursBefore(8), actorType: "AI", actorId: "agent:sales-order-quality", resultType: "ORDER_QUALITY", risk: "P1", score: 0.81, data: { reason: "产品F库存不足（仅剩 38）", recommendation: "补料/通知客户" } }),
  evt({ id: EVT_ORDER_G_RISK, type: "capability.result.order_quality", objectId: OBJ_ORDER_G, source: "agent-hub", occurredAt: hoursBefore(28), actorType: "AI", actorId: "agent:sales-order-quality", resultType: "ORDER_QUALITY", risk: "P3", score: 0.12, data: { reason: "重要客户，策略加权后无风险", recommendation: "正常交付" } }),
  evt({ id: EVT_ORDER_H_RISK, type: "capability.result.order_risk", objectId: OBJ_ORDER_H, source: "agent-hub", occurredAt: hoursBefore(3), actorType: "AI", actorId: "agent:delivery-order-risk", resultType: "ORDER_RISK", risk: "P0", score: 0.93, data: { reason: "部分物料短缺+产能紧张", recommendation: "组合方案：分批交付+产能协调+替代料" } }),
  evt({ id: EVT_ORDER_I_DQ, type: "capability.result.dq_check", objectId: OBJ_ORDER_I, source: "agent-hub", occurredAt: hoursBefore(44), actorType: "AI", actorId: "agent:dq-checker", resultType: "DATA_QUALITY", risk: "P2", score: 0.58, data: { reason: "客户ID在ERP中有两处不同记录", recommendation: "人工确认主记录" } }),
  evt({ id: EVT_ORDER_J_RISK, type: "capability.result.order_risk", objectId: OBJ_ORDER_J, source: "agent-hub", occurredAt: hoursBefore(12), actorType: "AI", actorId: "agent:delivery-order-risk", resultType: "ORDER_RISK", risk: "P1", score: 0.88, data: { reason: "供应商 S-030 即将停产，多源依赖", recommendation: "寻找替代供应商或修改BOM" } }),
  evt({ id: EVT_CASE_B_CREATED, type: "decision.case_created", objectId: OBJ_ORDER_B, source: "agent-hub", occurredAt: hoursBefore(4), actorType: "AI", actorId: "agent:delivery-order-risk", data: { case_no: "DC-20260928-007", question: "订单 SO-2026-00123 存在缺料风险，是否加急采购物料X？" } }),
  evt({ id: EVT_ADAPTER_PLM_FAILED, type: "adapter.sync.failed", objectId: OBJ_PROJECT_PRJD, source: "edp-adapter", occurredAt: minutesBefore(18), actorType: "SERVICE", actorId: "adapter:plm", risk: "P2", score: 0.5, resultType: "ADAPTER", deliveryStatus: "DEAD_LETTER", data: { adapter: "plm", reason: "UPSTREAM_UNAVAILABLE", note: "场景 10：工具调用失败，已转人工跟进" } }),
];

/** 质量事件流（T3/T4/T6 后端写通道 event_type 实测：quality.* / edp-quality）：
 *  occurred_at 置于事件流页默认 24H 窗口之外（26h+），不扰动既有窗口计数断言。 */
const qualityEvents: EventResponse[] = [
  evt({
    id: EVT_QUALITY_REINDEX_OK,
    type: "quality.reindex_succeeded",
    objectId: OBJ_ORDER_A,
    source: "edp-quality",
    occurredAt: hoursBefore(26),
    actorType: "SERVICE",
    actorId: "service:quality",
    data: {
      task_id: "a3e1c000-0000-4000-8000-000000000950",
      scope: "ALL",
      stats: { total: 20, rechecked: 20, mismatched: 0 },
    },
  }),
  evt({
    id: EVT_QUALITY_REINDEX_MISMATCH,
    type: "quality.reindex_mismatch",
    objectId: OBJ_ORDER_A,
    source: "edp-quality",
    occurredAt: hoursBefore(26.1),
    actorType: "SERVICE",
    actorId: "service:quality",
    data: {
      task_id: "a3e1c000-0000-4000-8000-000000000950",
      mismatched: 1,
      mismatches: [
        { evidence_id: EVID_ORDER_I_DUAL, expected: "sha256:9f2c…", actual: "sha256:71ab…" },
      ],
    },
  }),
  evt({
    id: EVT_QUALITY_RECHECK_OK,
    type: "quality.recheck_succeeded",
    objectId: OBJ_ORDER_A,
    source: "edp-quality",
    occurredAt: hoursBefore(30),
    actorType: "SERVICE",
    actorId: "service:quality",
    data: {
      task_id: "TASK-20260926-0003",
      scope: "ALL",
      stats: { reconciliation: { groups: 5, bad_groups: 0 }, checksum: { sampled: 120, failed: 1 } },
    },
  }),
  evt({
    id: EVT_QUALITY_CHECKSUM_FAIL,
    type: "quality.checksum_failed",
    objectId: OBJ_ORDER_I,
    source: "edp-quality",
    occurredAt: hoursBefore(49),
    actorType: "SERVICE",
    actorId: "service:quality",
    data: { evidence_id: EVID_ORDER_I_DUAL, expected: "sha256:9f2c…", actual: "sha256:71ab…" },
  }),
];

export const events: EventResponse[] = [
  ...orderRoutineEvents,
  ...inventoryRoutineEvents,
  ...capabilityEvents,
  ...qualityEvents,
];

export function findEvent(id: string): EventResponse | undefined {
  return events.find((e) => e.event_id === id);
}
