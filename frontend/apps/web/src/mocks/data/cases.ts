import type { Schemas } from "../types";
import { daysBefore, hoursBefore, minutesBefore } from "../lib/demo-time";
import { exceptions } from "./ebms";
import { fakeChecksum } from "./evidence";
import {
  CASE_ORDER_B,
  EVID_ORDER_B_INVENTORY,
  EVID_ORDER_B_LEADTIME,
  EVID_ORDER_B_PO,
  EVID_ORDER_B_SNAPSHOT,
  EVT_ORDER_B_RISK,
  EVT_ORDER_C_RISK,
  EVT_ORDER_E_RISK,
  EVT_ORDER_H_RISK,
  EVT_ORDER_J_RISK,
  mockUuid,
} from "./ids";

/**
 * W4 闭环案例 fixtures（EDP-403）：故事线复用 ebms/objects/evidence 数据——
 * CASE_ORDER_B（场景 2 订单 B，M4 主线）为 DECIDED 全量聚合样本（event/steps/
 * actions/evidence_chain 四层），其余案例与 16 条例行案例构成筛选/分页基数。
 * 形状对齐 SDK CaseListItem/CaseDetailResponse（T8 契约冻结）。
 */
export type CaseRow = Schemas["CaseListItem"];
export type CaseDetailData = Schemas["CaseDetailResponse"];
type CaseStep = Schemas["CaseStepItem"];
type CaseEventSummary = Schemas["CaseEventSummary"];

// ---- 故事案例 id（W4 页面数据不在 spec §4 固定表范围，本地具名） ----
export const CASE_H_COMBINED = mockUuid(902);
export const CASE_E_LOWSTOCK = mockUuid(903);
export const CASE_J_SUPPLIER = mockUuid(904);
export const CASE_C_DELAY = mockUuid(905);
export const CASE_G_VIP = mockUuid(906);
export const CASE_I_DQ = mockUuid(907);
const DECISION_B = mockUuid(801);
export const ACTION_B_EXPEDITE = mockUuid(802);
const EVID_RESULT_B = mockUuid(620);
const EVID_DECISION_B = mockUuid(621);

const caseQuestionB = "订单 SO-2026-00123 存在缺料风险，是否加急采购物料X？";
const caseOptionsB = [
  { key: "EXPEDITE", label: "加急采购" },
  { key: "SUBSTITUTE", label: "启用替代料" },
  { key: "REJECT", label: "拒绝建议" },
];

/** B.5 列表（created_at DESC 序；例行 16 条铺筛选/分页基数）。 */
export const caseRows: CaseRow[] = [
  { case_id: CASE_H_COMBINED, case_no: "DC-20260928-008", question: "订单 SO-2026-00129 物料短缺叠加产能紧张，采用哪种交付组合方案？", risk_level: "P0", status: "OPEN", created_at: minutesBefore(150) },
  { case_id: CASE_ORDER_B, case_no: "DC-20260928-007", question: caseQuestionB, risk_level: "P1", status: "DECIDED", created_at: hoursBefore(4) },
  { case_id: CASE_E_LOWSTOCK, case_no: "DC-20260928-006", question: "订单 SO-2026-00126 产品F库存不足，是否暂停接单并通知客户？", risk_level: "P1", status: "OPEN", created_at: hoursBefore(7) },
  { case_id: CASE_J_SUPPLIER, case_no: "DC-20260928-005", question: "供应商 S-030 即将停产，是否启动替代供应商认证？", risk_level: "P1", status: "OPEN", created_at: hoursBefore(11) },
  { case_id: CASE_C_DELAY, case_no: "DC-20260928-004", question: "订单 SO-2026-00124 采购到货推迟 2 周，是否调整生产计划？", risk_level: "P2", status: "OPEN", created_at: hoursBefore(19) },
  { case_id: CASE_G_VIP, case_no: "DC-20260928-003", question: "订单 SO-2026-00128 VIP 客户交付策略复核", risk_level: "P3", status: "CANCELLED", created_at: hoursBefore(27) },
  { case_id: CASE_I_DQ, case_no: "DC-20260927-002", question: "订单 SO-2026-00130 客户主数据双记录，请确认主记录", risk_level: "P2", status: "CANCELLED", created_at: hoursBefore(43) },
  ...Array.from({ length: 16 }, (_, i) =>
    ({
      case_id: mockUuid(920 + i),
      case_no: `DC-20260927-${String(21 + i).padStart(3, "0")}`,
      question: `例行风险复核 #${i + 1}：物料 X-${100 + i} 齐套率低于阈值`,
      risk_level: (i + 1) % 3 === 0 ? "P3" : "P2",
      status: "OPEN",
      created_at: daysBefore(3 + i),
    }) satisfies CaseRow,
  ),
];

/** 源事件摘要（ebms exceptions 故事线复用：summary/result_type/risk_level 口径一致）。 */
function eventSummaryOf(eventId: string): CaseEventSummary | null {
  const found = exceptions.find((e) => e.event_id === eventId);
  if (!found) return null;
  return {
    event_id: found.event_id,
    event_type: `capability.result.${found.result_type.toLowerCase()}`,
    result_type: found.result_type,
    risk_level: found.risk_level,
    summary: found.summary,
    occurred_at: found.occurred_at,
  };
}

const eventByCase: Record<string, CaseEventSummary | null> = {
  [CASE_H_COMBINED]: eventSummaryOf(EVT_ORDER_H_RISK),
  [CASE_E_LOWSTOCK]: eventSummaryOf(EVT_ORDER_E_RISK),
  [CASE_J_SUPPLIER]: eventSummaryOf(EVT_ORDER_J_RISK),
  [CASE_C_DELAY]: eventSummaryOf(EVT_ORDER_C_RISK),
  // G/I 已取消（复核确认无风险/主记录确认后取消）：无源事件 → 关联风险按钮禁用
  [CASE_G_VIP]: null,
  [CASE_I_DQ]: null,
};

const genericOptions = [
  { key: "CONFIRM", label: "确认执行" },
  { key: "ADJUST", label: "调整方案" },
  { key: "REJECT", label: "拒绝建议" },
];

/** 通用详情（非主线案例）：context 仅 source_event_id（可缺省），steps 最小两节点。 */
function buildDetail(row: CaseRow, event: CaseEventSummary | null): CaseDetailData {
  const steps: CaseStep[] = [];
  if (event != null) {
    steps.push({
      step_type: "EVENT",
      occurred_at: event.occurred_at,
      actor: "agent-hub",
      title: event.summary,
      detail: event.event_type,
    });
  }
  steps.push({
    step_type: "CASE_CREATED",
    occurred_at: row.created_at,
    actor: "agent:edp",
    title: `创建决策案例 ${row.case_no ?? ""}`.trim(),
    detail: row.question,
  });
  return {
    case_id: row.case_id,
    question: row.question,
    context: event != null ? { source_event_id: event.event_id } : {},
    options: genericOptions,
    risk_level: row.risk_level,
    status: row.status,
    evidence_refs: [],
    decisions: [],
    event,
    steps,
    actions: [],
    evidence_chain: [],
  };
}

// ---- CASE_ORDER_B 全量聚合（M4 主线：事件→案例→决策→行动 + 四层证据链） ----

const detailB: CaseDetailData = {
  case_id: CASE_ORDER_B,
  question: caseQuestionB,
  context: { order_amount: 120000, material_gap: 1000, source_event_id: EVT_ORDER_B_RISK },
  options: caseOptionsB,
  risk_level: "P1",
  status: "DECIDED",
  evidence_refs: [
    { evidence_id: EVID_ORDER_B_SNAPSHOT, checksum: fakeChecksum(0xa4c1), source_system: "erp" },
    { evidence_id: EVID_ORDER_B_INVENTORY, checksum: fakeChecksum(0x0259), source_system: "erp" },
    { evidence_id: EVID_ORDER_B_PO, checksum: fakeChecksum(0x77d2), source_system: "erp" },
    { evidence_id: EVID_ORDER_B_LEADTIME, checksum: fakeChecksum(0x9f3d), source_system: "erp" },
  ],
  decisions: [
    {
      decision_id: DECISION_B,
      chosen_option: "EXPEDITE",
      comment: "缺口影响交付，先加急补 1000 件",
      decided_by: "user:manager_wang",
      decision_time: minutesBefore(210),
      decision_type: "HUMAN_APPROVAL",
    },
  ],
  event: eventSummaryOf(EVT_ORDER_B_RISK),
  steps: [
    {
      step_type: "EVENT",
      occurred_at: hoursBefore(5),
      actor: "agent-hub",
      title: "物料X缺口1000，预计延误5天",
      detail: "capability.result.order_risk",
    },
    {
      step_type: "CASE_CREATED",
      occurred_at: hoursBefore(4),
      actor: "agent:delivery-order-risk",
      title: "创建决策案例 DC-20260928-007",
      detail: caseQuestionB,
    },
    {
      step_type: "DECISION",
      occurred_at: minutesBefore(210),
      actor: "user:manager_wang",
      title: "决策：加急采购（EXPEDITE）",
      detail: "缺口影响交付，先加急补 1000 件",
      human_only: true,
    },
    {
      step_type: "ACTION",
      occurred_at: minutesBefore(180),
      actor: "user:manager_wang",
      title: "加急采购物料X",
      detail: "创建行动（PROCUREMENT）",
    },
    {
      step_type: "ACTION",
      occurred_at: minutesBefore(60),
      actor: "user:purchasing_li",
      title: "当前状态：APPROVED",
      // APPROVED 存在 Human-Only 出边（→EXECUTING），快照节点标注（后端 _has_human_only_edge 口径）
      human_only: true,
    },
  ],
  actions: [
    {
      action_id: ACTION_B_EXPEDITE,
      title: "加急采购物料X",
      status: "APPROVED",
      owner: "user:purchasing_li",
      due_date: daysBefore(-3),
      allowed_to: [
        { to_status: "EXECUTING", human_only: true },
        { to_status: "CANCELLED", human_only: false },
      ],
    },
  ],
  evidence_chain: [
    // RESULT：源结果事件回流证据
    { layer: "RESULT", evidence_id: EVID_RESULT_B, checksum: fakeChecksum(0xb21f), source_system: "agent-hub", source_record_id: "RES-SO-2026-00123#v1", title: "agent-hub:RES-SO-2026-00123#v1" },
    // DECISION：决策记录意见证据
    { layer: "DECISION", evidence_id: EVID_DECISION_B, checksum: fakeChecksum(0x77aa), source_system: "edp", source_record_id: "DEC-20260928-007#EXPEDITE", title: "edp:DEC-20260928-007#EXPEDITE" },
    // EVIDENCE：ref_type=CASE 证据集合（evidence fixtures 4 份，verify 走既有端点）
    { layer: "EVIDENCE", evidence_id: EVID_ORDER_B_SNAPSHOT, checksum: fakeChecksum(0xa4c1), source_system: "erp", source_record_id: "SO-2026-00123#v7", title: "erp:SO-2026-00123#v7" },
    { layer: "EVIDENCE", evidence_id: EVID_ORDER_B_INVENTORY, checksum: fakeChecksum(0x0259), source_system: "erp", source_record_id: "INV-X-100#20260927", title: "erp:INV-X-100#20260927" },
    { layer: "EVIDENCE", evidence_id: EVID_ORDER_B_PO, checksum: fakeChecksum(0x77d2), source_system: "erp", source_record_id: "PO-2026-00771", title: "erp:PO-2026-00771" },
    { layer: "EVIDENCE", evidence_id: EVID_ORDER_B_LEADTIME, checksum: fakeChecksum(0x9f3d), source_system: "erp", source_record_id: "SLT-S-021", title: "erp:SLT-S-021" },
    // SOURCE：(source_system, source_record_id) 投影去重（首现序）
    { layer: "SOURCE", source_system: "agent-hub", source_record_id: "RES-SO-2026-00123#v1", title: "agent-hub:RES-SO-2026-00123#v1" },
    { layer: "SOURCE", source_system: "edp", source_record_id: "DEC-20260928-007#EXPEDITE", title: "edp:DEC-20260928-007#EXPEDITE" },
    { layer: "SOURCE", source_system: "erp", source_record_id: "SO-2026-00123#v7", title: "erp:SO-2026-00123#v7" },
    { layer: "SOURCE", source_system: "erp", source_record_id: "INV-X-100#20260927", title: "erp:INV-X-100#20260927" },
    { layer: "SOURCE", source_system: "erp", source_record_id: "PO-2026-00771", title: "erp:PO-2026-00771" },
    { layer: "SOURCE", source_system: "erp", source_record_id: "SLT-S-021", title: "erp:SLT-S-021" },
  ],
};

export const caseDetails: CaseDetailData[] = caseRows.map((row) =>
  row.case_id === CASE_ORDER_B ? detailB : buildDetail(row, eventByCase[row.case_id] ?? null),
);

export function findCaseDetail(id: string): CaseDetailData | undefined {
  return caseDetails.find((c) => c.case_id === id);
}
