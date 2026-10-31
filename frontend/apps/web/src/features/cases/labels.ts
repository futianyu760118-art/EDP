import { RISK_LEVEL_LABELS, type LabelWithTone } from "@edp/shared";

/** 案例状态（B.5：OPEN/DECIDED/CANCELLED）。 */
export const CASE_STATUS_LABELS: Record<string, LabelWithTone> = {
  OPEN: { label: "待决", tone: "info" },
  DECIDED: { label: "已决策", tone: "success" },
  CANCELLED: { label: "已取消", tone: "muted" },
};

/** 行动 9 态 pill 色（T2 状态机；T10 行动页沿用）。 */
export const ACTION_STATUS_LABELS: Record<string, LabelWithTone> = {
  PROPOSED: { label: "PROPOSED", tone: "muted" },
  ASSIGNED: { label: "ASSIGNED", tone: "info" },
  ACCEPTED: { label: "ACCEPTED", tone: "info" },
  APPROVED: { label: "APPROVED", tone: "warning" },
  EXECUTING: { label: "EXECUTING", tone: "info" },
  COMPLETED: { label: "COMPLETED", tone: "success" },
  VERIFIED: { label: "VERIFIED", tone: "success" },
  CANCELLED: { label: "CANCELLED", tone: "muted" },
  REJECTED: { label: "REJECTED", tone: "muted" },
};

export function riskLabelOf(level: string | null | undefined): LabelWithTone {
  if (level == null) return { label: "—", tone: "muted" };
  return RISK_LEVEL_LABELS[level] ?? { label: level, tone: "muted" };
}

export function caseStatusOf(status: string): LabelWithTone {
  return CASE_STATUS_LABELS[status] ?? { label: status, tone: "muted" };
}

export function actionStatusOf(status: string): LabelWithTone {
  return ACTION_STATUS_LABELS[status] ?? { label: status, tone: "muted" };
}
