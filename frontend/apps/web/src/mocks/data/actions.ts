import type { Schemas } from "../types";
import { daysBefore, hoursBefore, minutesBefore } from "../lib/demo-time";
import { CASE_ORDER_B, mockUuid } from "./ids";
import { ACTION_B_EXPEDITE } from "./cases";

/**
 * W4 行动 fixtures（EDP-404）：与 cases 故事线一致——ACTION_B_EXPEDITE（802，
 * cases.ts 聚合快照同 id）为订单 B 主线（APPROVED），其余 7 条铺 9 态状态机、
 * status/owner 筛选与列表排序基数。形状对齐 SDK ActionDetailResponse（T8 冻结）。
 */
export type ActionRow = Schemas["ActionDetailResponse"];
type TransitionItem = Schemas["TransitionItem"];

/**
 * B.5 转移表（to -> {to: human_only}），与后端 modules/actions/service.TRANSITIONS
 * 同构（T2 单点口径）；allowed_to 投影 to_status 字典序稳定。
 */
export const ACTION_TRANSITIONS: Record<string, Record<string, boolean>> = {
  PROPOSED: { ASSIGNED: false, REJECTED: false, CANCELLED: false },
  ASSIGNED: { ACCEPTED: false, CANCELLED: false },
  ACCEPTED: { APPROVED: false, CANCELLED: false },
  APPROVED: { EXECUTING: true, CANCELLED: false },
  EXECUTING: { COMPLETED: false, CANCELLED: false },
  COMPLETED: { VERIFIED: true, CANCELLED: false },
  VERIFIED: {},
  CANCELLED: {},
  REJECTED: {},
};

/** 当前状态允许的转移项（字典序稳定，对齐后端 service.allowed_to）。 */
export function allowedToOf(status: string): TransitionItem[] {
  return Object.entries(ACTION_TRANSITIONS[status] ?? {})
    .map(([to_status, human_only]) => ({ to_status, human_only }))
    .sort((a, b) => a.to_status.localeCompare(b.to_status));
}

export const ACTION_DISPATCH_CHECK = mockUuid(812);
export const ACTION_SUBSTITUTE_EVAL = mockUuid(813);
export const ACTION_C_PLAN_ADJUST = mockUuid(814);
export const ACTION_NOTIFY_CUSTOMER = mockUuid(815);
export const ACTION_S030_AUDIT = mockUuid(816);
export const ACTION_G_REVIEW = mockUuid(817);
export const ACTION_E_HOLD = mockUuid(818);

/** B.5 列表（created_at DESC，action_id DESC tiebreak）。 */
export const actionRows: ActionRow[] = [
  {
    action_id: ACTION_B_EXPEDITE,
    case_id: CASE_ORDER_B,
    title: "加急采购物料X",
    description: "缺口 1000 件影响交付，按决策加急补货（EXPEDITE）",
    action_type: "expedite_purchase",
    status: "APPROVED",
    owner: "user:purchasing_li",
    owner_role: "PROCUREMENT",
    due_date: daysBefore(-3),
    completion_time: null,
    verified_at: null,
    verified_by: null,
    created_at: minutesBefore(180),
    updated_at: minutesBefore(60),
    allowed_to: allowedToOf("APPROVED"),
  },
  {
    action_id: ACTION_DISPATCH_CHECK,
    case_id: null,
    title: "核查在途 PO-2026-00771 到货窗口",
    description: null,
    action_type: "dispatch_check",
    status: "EXECUTING",
    owner: "user:purchasing_li",
    owner_role: "PROCUREMENT",
    due_date: daysBefore(-1),
    completion_time: null,
    verified_at: null,
    verified_by: null,
    created_at: hoursBefore(6),
    updated_at: minutesBefore(40),
    allowed_to: allowedToOf("EXECUTING"),
  },
  {
    action_id: ACTION_SUBSTITUTE_EVAL,
    case_id: null,
    title: "评估物料X替代料方案",
    description: null,
    action_type: "substitute_eval",
    status: "PROPOSED",
    owner: null,
    owner_role: "PLANNING",
    due_date: null,
    completion_time: null,
    verified_at: null,
    verified_by: null,
    created_at: hoursBefore(9),
    updated_at: hoursBefore(9),
    allowed_to: allowedToOf("PROPOSED"),
  },
  {
    action_id: ACTION_C_PLAN_ADJUST,
    case_id: null,
    title: "调整 SO-2026-00124 生产计划",
    description: null,
    action_type: "plan_adjust",
    status: "ASSIGNED",
    owner: "user:planner_zhao",
    owner_role: "PLANNING",
    due_date: daysBefore(-2),
    completion_time: null,
    verified_at: null,
    verified_by: null,
    created_at: hoursBefore(14),
    updated_at: hoursBefore(10),
    allowed_to: allowedToOf("ASSIGNED"),
  },
  {
    action_id: ACTION_E_HOLD,
    case_id: null,
    title: "暂停接收 SO-2026-00126 新订单",
    description: null,
    action_type: "order_hold",
    status: "REJECTED",
    owner: "user:sales_sun",
    owner_role: "SALES",
    due_date: null,
    completion_time: null,
    verified_at: null,
    verified_by: null,
    created_at: hoursBefore(22),
    updated_at: hoursBefore(15),
    allowed_to: allowedToOf("REJECTED"),
  },
  {
    action_id: ACTION_S030_AUDIT,
    case_id: null,
    title: "S-030 供应商替代认证审计",
    description: null,
    action_type: "supplier_audit",
    status: "VERIFIED",
    owner: "user:qm_chen",
    owner_role: "QUALITY",
    due_date: daysBefore(-5),
    completion_time: hoursBefore(21),
    verified_at: hoursBefore(20),
    verified_by: "user:manager_wang",
    created_at: hoursBefore(26),
    updated_at: hoursBefore(20),
    allowed_to: allowedToOf("VERIFIED"),
  },
  {
    action_id: ACTION_NOTIFY_CUSTOMER,
    case_id: null,
    title: "通知客户 SO-2026-00126 库存不足影响",
    description: null,
    action_type: "customer_notify",
    status: "COMPLETED",
    owner: "user:cs_wu",
    owner_role: null,
    due_date: daysBefore(-6),
    completion_time: hoursBefore(34),
    verified_at: null,
    verified_by: null,
    created_at: hoursBefore(40),
    updated_at: hoursBefore(33),
    allowed_to: allowedToOf("COMPLETED"),
  },
  {
    action_id: ACTION_G_REVIEW,
    case_id: null,
    title: "VIP 订单交付策略复核",
    description: null,
    action_type: "delivery_review",
    status: "CANCELLED",
    owner: "user:manager_wang",
    owner_role: null,
    due_date: null,
    completion_time: null,
    verified_at: null,
    verified_by: null,
    created_at: daysBefore(2),
    updated_at: daysBefore(1),
    allowed_to: allowedToOf("CANCELLED"),
  },
];
