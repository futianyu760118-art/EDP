import type { StatusPillTone } from "@edp/shared";
import { DEMO_NOW } from "../../mocks/lib/demo-time";

/** 业务对象页派生规则（设计 13.6.2）：纯函数，无 IO。 */

export type DerivedStatus =
  | "Healthy"
  | "Watch"
  | "At Risk"
  | "Blocking"
  | "DQ Exception"
  | "Delayed";

export interface DeriveStatusInput {
  /** 最新能力结果事件 risk_level（由页面 risk 索引 Map 传入） */
  riskLevel?: string | null;
  /** events 含 DATA_QUALITY 异常 */
  hasDqException?: boolean;
  /** now - updated_at（小时） */
  syncLagHours?: number;
}

export function deriveStatus(input: DeriveStatusInput): DerivedStatus {
  if (input.riskLevel === "P0") return "Blocking";
  if (input.riskLevel === "P1") return "At Risk";
  if (input.hasDqException) return "DQ Exception";
  if ((input.syncLagHours ?? 0) > 48) return "Delayed";
  if (input.riskLevel === "P2" || input.riskLevel === "P3") return "Watch";
  return "Healthy";
}

export const DERIVED_TONE: Record<DerivedStatus, StatusPillTone> = {
  Healthy: "success",
  Watch: "info",
  "At Risk": "warning",
  Blocking: "error",
  "DQ Exception": "warning",
  Delayed: "warning",
};

/** 派生态全集（状态下拉选项顺序）。 */
export const DERIVED_STATUSES: DerivedStatus[] = [
  "Healthy",
  "Watch",
  "At Risk",
  "Blocking",
  "DQ Exception",
  "Delayed",
];

/** 风险评分（卡片进度条宽度/数值）：P0=95 / P1=80 / P2=55 / P3=30 / 无风险=8。 */
export function riskScore(riskLevel?: string | null): number {
  switch (riskLevel) {
    case "P0":
      return 95;
    case "P1":
      return 80;
    case "P2":
      return 55;
    case "P3":
      return 30;
    default:
      return 8;
  }
}

/**
 * updated_at 距当前小时数（演示锚点在未来时为负，不触发 Delayed）。
 * MSW 演示模式（VITE_USE_MSW=1）下 fixtures 时间以 mocks 的 DEMO_NOW 锚定，
 * 真实时钟越过锚点 48h 后会把全部对象误判 Delayed（演示时间炸弹，T7 评审
 * Minor a）——该模式以锚点为基准；真实模式用系统时钟。
 */
export function lagHours(updatedAtIso: string, nowMs: number = currentNowMs()): number {
  return (nowMs - new Date(updatedAtIso).getTime()) / 3_600_000;
}

function currentNowMs(): number {
  return import.meta.env.VITE_USE_MSW === "1" ? DEMO_NOW.getTime() : Date.now();
}

/** 域下拉选项（原型`业务对象.html`行 357~363 逐字）：value 为 owner_domain 实际值。 */
export const DOMAIN_OPTIONS: { value: string; label: string }[] = [
  { value: "delivery", label: "Delivery" },
  { value: "sales", label: "Sales" },
  { value: "rd", label: "R&D" },
  { value: "procurement", label: "Procurement" },
  { value: "master", label: "Master" },
];

export function domainLabel(domain: string): string {
  return DOMAIN_OPTIONS.find((d) => d.value === domain)?.label ?? domain;
}
