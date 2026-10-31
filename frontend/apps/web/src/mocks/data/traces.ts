import type { Schemas } from "../types";
import { mockUuid } from "./ids";
import { hoursBefore, minutesBefore } from "../lib/demo-time";
import { EVID_ORDER_B_INVENTORY, EVID_ORDER_B_PO, EVID_ORDER_B_SNAPSHOT } from "./ids";
import { CUSTOMER_C008, MATERIAL_X, ORDER_B_NO, SUPPLIER_S118 } from "./tools";

/**
 * B.10 Trace fixtures：主链锚定订单 B 风险评估（设计 §B.10 示例逐字段——agent:
 * delivery-order-risk / token 3120·480·3600 / 四步工具调用），工具名与 B.8 六接口
 * 对齐；capability_id 三能力供 traces/memory 两页筛选共用（跨页一致，spec §4）。
 */

// ---- 能力（traces/memory 筛选共用；能力清单 name 见 data/catalog.ts 与 capabilities 兜底常量） ----
export const CAP_ORDER_RISK = mockUuid(801); // 订单风险评估
export const CAP_PRODUCT_READINESS = mockUuid(802); // 产品就绪度
export const CAP_DQ_CHECK = mockUuid(803); // 数据质量检查

// ---- Trace UUID（7xx 段） ----
export const TRACE_ORDER_B_RISK = mockUuid(711);
export const TRACE_ORDER_C_DELAY = mockUuid(712);
export const TRACE_PRJD_READINESS = mockUuid(713);
export const TRACE_ORDER_I_DQ = mockUuid(714);
export const TRACE_ORDER_G_VIP = mockUuid(715);
export const TRACE_ORDER_E_STRESS = mockUuid(716);
export const TRACE_ORDER_J_CROSS = mockUuid(717);
export const TRACE_DQ_NIGHTLY = mockUuid(718);

/** 订单 B 风险评估主链（§B.10 示例）：四步工具调用 + token 三数 + 证据三链。 */
const orderBRiskDetail: Schemas["TraceDetail"] = {
  trace_id: TRACE_ORDER_B_RISK,
  agent_id: "agent:delivery-order-risk",
  task_id: "task-0928-001",
  capability_id: CAP_ORDER_RISK,
  status: "SUCCEEDED",
  started_at: "2026-09-28T08:00:00.000Z",
  finished_at: "2026-09-28T08:00:41.000Z",
  created_at: "2026-09-28T08:00:41.000Z",
  input_context: { order_no: ORDER_B_NO, customer_code: CUSTOMER_C008 },
  output_structured: { risk_level: "P1", score: 0.86, summary: "关键料缺失 + 交期推迟叠加" },
  token_usage: { prompt: 3120, completion: 480, total: 3600 },
  evidence_refs: [EVID_ORDER_B_SNAPSHOT, EVID_ORDER_B_INVENTORY, EVID_ORDER_B_PO],
  tool_calls: [
    {
      call_id: mockUuid(721),
      seq: 1,
      tool_name: "get_order",
      called_at: "2026-09-28T08:00:02.000Z",
      input: { order_no: ORDER_B_NO },
      output: { status: "已确认", amount: 120000, currency: "CNY" },
      status_code: 200,
      latency_ms: 85,
      error: null,
    },
    {
      call_id: mockUuid(722),
      seq: 2,
      tool_name: "get_inventory",
      called_at: "2026-09-28T08:00:05.000Z",
      input: { material_code: MATERIAL_X },
      output: { material_code: MATERIAL_X, total_available: 3200 },
      status_code: 200,
      latency_ms: 112,
      error: null,
    },
    {
      call_id: mockUuid(723),
      seq: 3,
      tool_name: "list_purchase_orders",
      called_at: "2026-09-28T08:00:09.000Z",
      input: { material_code: MATERIAL_X },
      output: { count: 1, pos: ["PO-2026-00771"] },
      status_code: 200,
      latency_ms: 156,
      error: null,
    },
    {
      call_id: mockUuid(724),
      seq: 4,
      tool_name: "get_supplier_lead_times",
      called_at: "2026-09-28T08:00:14.000Z",
      input: { supplier_code: SUPPLIER_S118 },
      output: { lead_times: [{ material_code: MATERIAL_X, lead_time_days: 14 }] },
      status_code: 200,
      latency_ms: 94,
      error: null,
    },
  ],
};

function trace(
  id: string,
  seed: {
    agent: string;
    capability: string | null;
    status: string;
    startedAt: string;
    seconds: number | null;
    taskId?: string | null;
  },
): Schemas["TraceDetail"] {
  const started = new Date(seed.startedAt);
  return {
    trace_id: id,
    agent_id: seed.agent,
    task_id: seed.taskId ?? null,
    capability_id: seed.capability,
    status: seed.status,
    started_at: seed.startedAt,
    finished_at:
      seed.seconds != null ? new Date(started.getTime() + seed.seconds * 1000).toISOString() : null,
    created_at:
      seed.seconds != null ? new Date(started.getTime() + seed.seconds * 1000).toISOString() : started.toISOString(),
    input_context: {},
    output_structured: null,
    token_usage: null,
    evidence_refs: [],
    tool_calls: [],
  };
}

/** 全量轨迹（列表 handler 投影简表；详情 handler 原样返回）。started_at DESC 挂载顺序。 */
export const traceDetails: Schemas["TraceDetail"][] = [
  orderBRiskDetail,
  {
    ...trace(TRACE_ORDER_G_VIP, {
      agent: "agent:delivery-order-risk",
      capability: CAP_ORDER_RISK,
      status: "SUCCEEDED",
      startedAt: minutesBefore(35),
      seconds: 28,
      taskId: "task-0928-006",
    }),
    input_context: { order_no: "SO-2026-00128", customer_code: CUSTOMER_C008 },
    output_structured: { risk_level: "P2", score: 0.54, summary: "VIP 客户交付窗口严格" },
    token_usage: { prompt: 2410, completion: 366, total: 2776 },
    tool_calls: [
      {
        call_id: mockUuid(731),
        seq: 1,
        tool_name: "get_customer",
        called_at: minutesBefore(35),
        input: { customer_code: CUSTOMER_C008 },
        output: { name: "某客户", level: "VIP" },
        status_code: 200,
        latency_ms: 61,
        error: null,
      },
    ],
  },
  {
    ...trace(TRACE_ORDER_J_CROSS, {
      agent: "agent:delivery-order-risk",
      capability: CAP_ORDER_RISK,
      status: "TIMEOUT",
      startedAt: minutesBefore(72),
      seconds: 120,
      taskId: "task-0928-009",
    }),
    input_context: { order_no: "SO-2026-00131" },
    output_structured: null,
    token_usage: { prompt: 5230, completion: 122, total: 5352 },
    tool_calls: [
      {
        call_id: mockUuid(732),
        seq: 1,
        tool_name: "get_bom",
        called_at: minutesBefore(72),
        input: { product_code: "P-D" },
        output: null,
        status_code: 404,
        latency_ms: 89,
        error: { code: "NOT_FOUND", message: "产品 ACTIVE BOM 不存在" },
      },
    ],
  },
  {
    ...trace(TRACE_DQ_NIGHTLY, {
      agent: "agent:dq-nightly",
      capability: CAP_DQ_CHECK,
      status: "RUNNING",
      startedAt: minutesBefore(9),
      seconds: null,
      taskId: "task-0928-011",
    }),
    input_context: { scope: "CUSTOMER", window: "24h" },
  },
  {
    ...trace(TRACE_ORDER_I_DQ, {
      agent: "agent:dq-check",
      capability: CAP_DQ_CHECK,
      status: "FAILED",
      startedAt: hoursBefore(5),
      seconds: 34,
      taskId: "task-0928-008",
    }),
    input_context: { order_no: "SO-2026-00130" },
    output_structured: { duplicate_pairs: 1, note: "ERP 客户双记录（C-030 / C-030-B）" },
    token_usage: { prompt: 1890, completion: 240, total: 2130 },
    tool_calls: [
      {
        call_id: mockUuid(733),
        seq: 1,
        tool_name: "get_customer",
        called_at: hoursBefore(5),
        input: { customer_code: "C-030" },
        output: null,
        status_code: 500,
        latency_ms: 402,
        error: { code: "INTERNAL", message: "上游 MDM 查询失败" },
      },
    ],
  },
  {
    ...trace(TRACE_PRJD_READINESS, {
      agent: "agent:product-readiness",
      capability: CAP_PRODUCT_READINESS,
      status: "SUCCEEDED",
      startedAt: hoursBefore(8),
      seconds: 66,
      taskId: "task-0928-004",
    }),
    input_context: { project_code: "PRJ-D" },
    output_structured: { readiness: 0.62, blockers: ["物料 Y-200 交期推迟"] },
    token_usage: { prompt: 4460, completion: 610, total: 5070 },
    tool_calls: [
      {
        call_id: mockUuid(734),
        seq: 1,
        tool_name: "get_bom",
        called_at: hoursBefore(8),
        input: { product_code: "P-D" },
        output: { items: 6 },
        status_code: 200,
        latency_ms: 143,
        error: null,
      },
      {
        call_id: mockUuid(735),
        seq: 2,
        tool_name: "get_supplier_lead_times",
        called_at: hoursBefore(8),
        input: { supplier_code: SUPPLIER_S118 },
        output: { max_lead_time_days: 21 },
        status_code: 200,
        latency_ms: 97,
        error: null,
      },
    ],
  },
  {
    ...trace(TRACE_ORDER_E_STRESS, {
      agent: "agent:delivery-order-risk",
      capability: CAP_ORDER_RISK,
      status: "SUCCEEDED",
      startedAt: hoursBefore(22),
      seconds: 37,
      taskId: "task-0928-005",
    }),
    input_context: { order_no: "SO-2026-00126" },
    output_structured: { risk_level: "P1", score: 0.81, summary: "高值低库存" },
    token_usage: { prompt: 2980, completion: 421, total: 3401 },
    tool_calls: [],
  },
  {
    ...trace(TRACE_ORDER_C_DELAY, {
      agent: "agent:supplier-delay-watch",
      capability: CAP_ORDER_RISK,
      status: "SUCCEEDED",
      startedAt: hoursBefore(30),
      seconds: 19,
      taskId: "task-0928-003",
    }),
    input_context: { po_no: "PO-2026-00785" },
    output_structured: { delay_days: 14, supplier: SUPPLIER_S118 },
    token_usage: { prompt: 1520, completion: 208, total: 1728 },
    tool_calls: [],
  },
];
