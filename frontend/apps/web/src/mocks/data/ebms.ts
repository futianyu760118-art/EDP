import type { ExceptionItem } from "../types";
import { hoursBefore, minutesBefore } from "../lib/demo-time";
import {
  CASE_ORDER_B, EVT_ADAPTER_PLM_FAILED, EVT_ORDER_B_RISK, EVT_ORDER_C_RISK, EVT_ORDER_E_RISK,
  EVT_ORDER_H_RISK, EVT_ORDER_I_DQ, EVT_ORDER_J_RISK, EVT_PRJD_READINESS, OBJ_ORDER_B, OBJ_ORDER_C,
  OBJ_ORDER_E, OBJ_ORDER_H, OBJ_ORDER_I, OBJ_ORDER_J, OBJ_PROJECT_PRJD,
} from "./ids";

/**
 * B.9 异常列表（8 条 = P0×1 + P1×3 + P2×4）。
 * status 语义由 handler 实现：B.9 无 status 字段——mock 约定最后一行（场景 8 数据不一致）
 * 为 RESOLVED（人工已确认），`?status=RESOLVED` 只返回它，默认/OPEN 返回其余 7 条。
 */
export const exceptions: ExceptionItem[] = [
  { event_id: EVT_ORDER_H_RISK, result_type: "ORDER_RISK", risk_level: "P0", object_id: OBJ_ORDER_H, order_no: "SO-2026-00129", summary: "部分物料短缺+产能紧张，综合高风险", occurred_at: hoursBefore(3), case_id: null },
  { event_id: EVT_ORDER_B_RISK, result_type: "ORDER_RISK", risk_level: "P1", object_id: OBJ_ORDER_B, order_no: "SO-2026-00123", summary: "物料X缺口1000，预计延误5天", occurred_at: hoursBefore(5), case_id: CASE_ORDER_B },
  { event_id: EVT_ORDER_E_RISK, result_type: "ORDER_QUALITY", risk_level: "P1", object_id: OBJ_ORDER_E, order_no: "SO-2026-00126", summary: "产品F库存不足（仅剩38），大额订单交付风险", occurred_at: hoursBefore(8), case_id: null },
  { event_id: EVT_ORDER_J_RISK, result_type: "ORDER_RISK", risk_level: "P1", object_id: OBJ_ORDER_J, order_no: "SO-2026-00131", summary: "供应商S-030即将停产，多源依赖需替代方案", occurred_at: hoursBefore(12), case_id: null },
  { event_id: EVT_ORDER_C_RISK, result_type: "ORDER_RISK", risk_level: "P2", object_id: OBJ_ORDER_C, order_no: "SO-2026-00124", summary: "PO-2026-00785 预计到货推迟 2 周", occurred_at: hoursBefore(20), case_id: null },
  { event_id: EVT_PRJD_READINESS, result_type: "PRODUCT_READINESS", risk_level: "P2", object_id: OBJ_PROJECT_PRJD, order_no: "PRJ-D", summary: "新品D项目验证中，未达量产就绪", occurred_at: hoursBefore(32), case_id: null },
  { event_id: EVT_ADAPTER_PLM_FAILED, result_type: "ADAPTER", risk_level: "P2", object_id: OBJ_PROJECT_PRJD, order_no: "PLM", summary: "PLM 同步失败（工具调用故障），里程碑数据待更新", occurred_at: minutesBefore(18), case_id: null },
  { event_id: EVT_ORDER_I_DQ, result_type: "DATA_QUALITY", risk_level: "P2", object_id: OBJ_ORDER_I, order_no: "SO-2026-00130", summary: "客户ID在ERP存在双记录，需人工确认", occurred_at: hoursBefore(44), case_id: null },
];
