import type { Schemas } from "../types";
import { daysBefore, hoursBefore } from "../lib/demo-time";
import {
  CAP_DQ_CHECK,
  CAP_ORDER_RISK,
  CAP_PRODUCT_READINESS,
  TRACE_ORDER_B_RISK,
  TRACE_ORDER_I_DQ,
  TRACE_PRJD_READINESS,
} from "./traces";
import { MATERIAL_X, ORDER_B_NO, SUPPLIER_S118 } from "./tools";

/**
 * B.11 候选记忆 fixtures：Agent 中枢执行轨迹提炼的候选（status=CANDIDATE 为主，
 * 少量已评审 APPROVED/REJECTED 展示三态 pill）；source_type=TRACE 时 source_id
 * 指向 traces.ts 既有轨迹（跨页一致），内容摘要锚定订单 B 主线场景。
 */

export const memoryItems: Schemas["MemoryListItem"][] = [
  {
    memory_id: "00000000-0000-4000-8000-000000000741",
    capability_id: CAP_ORDER_RISK,
    status: "CANDIDATE",
    source_type: "TRACE",
    source_id: TRACE_ORDER_B_RISK,
    content: {
      summary: `订单 ${ORDER_B_NO} 关键料 ${MATERIAL_X} 缺口 1000：可用 3200 − 已占 4200，需在 2026-10-10 前补货`,
      order_no: ORDER_B_NO,
      material_code: MATERIAL_X,
      gap_quantity: 1000,
      suggested_action: "催货 PO-2026-00771 或启用备选料",
    },
    created_at: hoursBefore(6),
    reviewed_at: null,
    reviewed_by: null,
  },
  {
    memory_id: "00000000-0000-4000-8000-000000000742",
    capability_id: CAP_ORDER_RISK,
    status: "CANDIDATE",
    source_type: "TRACE",
    source_id: TRACE_ORDER_B_RISK,
    content: {
      summary: `供应商 ${SUPPLIER_S118} 交期由 7 天推迟至 14 天（2026-09-25 起），影响其在途全部物料`,
      supplier_code: SUPPLIER_S118,
      lead_time_days: 14,
      effective_from: "2026-09-25",
    },
    created_at: hoursBefore(26),
    reviewed_at: null,
    reviewed_by: null,
  },
  {
    memory_id: "00000000-0000-4000-8000-000000000743",
    capability_id: CAP_PRODUCT_READINESS,
    status: "CANDIDATE",
    source_type: "TRACE",
    source_id: TRACE_PRJD_READINESS,
    content: {
      summary: "产品 D（PRJ-D）就绪度 0.62，阻塞项为物料 Y-200 交期推迟两周，验证阶段无法闭环",
      project_code: "PRJ-D",
      readiness: 0.62,
      blockers: ["Y-200 交期推迟"],
    },
    created_at: daysBefore(2),
    reviewed_at: null,
    reviewed_by: null,
  },
  {
    memory_id: "00000000-0000-4000-8000-000000000744",
    capability_id: CAP_DQ_CHECK,
    status: "APPROVED",
    source_type: "TRACE",
    source_id: TRACE_ORDER_I_DQ,
    content: {
      summary: "ERP 客户主数据存在 C-030 / C-030-B 双记录，按最近修订版本合并归属",
      duplicate_pair: ["C-030", "C-030-B"],
      resolution: "以 revision 较高者为主记录",
    },
    created_at: daysBefore(4),
    reviewed_at: daysBefore(3),
    reviewed_by: "dq_owner",
  },
  {
    memory_id: "00000000-0000-4000-8000-000000000745",
    capability_id: CAP_ORDER_RISK,
    status: "REJECTED",
    source_type: "TRACE",
    source_id: TRACE_ORDER_B_RISK,
    content: {
      summary: "单次风险评分高于 0.8 即建议直接升级 P0（评审驳回：需叠加人工确认信号）",
      rule: "score>0.8 → P0",
    },
    created_at: daysBefore(5),
    reviewed_at: daysBefore(5),
    reviewed_by: "risk_owner",
  },
];
