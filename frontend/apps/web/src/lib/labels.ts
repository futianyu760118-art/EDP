/** Web 本地展示工具：13.4.4 枚举展示名（角色/套餐）与头像缩写归 @edp/shared 单点。 */

import type { StatusPillTone } from "@edp/shared";

export { planLabel, roleLabel } from "@edp/shared";

/** 头像两字母缩写：拉丁名取前两个字母（Y. Liu → YL），中文名取前两字（默认租户 → 默认租）。 */
export function initials(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "ED";
  const latin = trimmed.replace(/[^A-Za-z]/g, "").slice(0, 2).toUpperCase();
  if (latin.length >= 1) return latin.padEnd(2, "");
  return trimmed.slice(0, 2);
}

/** 千分位（T4 总览 KPI 网格数值格式；集中放 labels.ts 供总览/后续页复用）。 */
export function fmt(n: number): string {
  return new Intl.NumberFormat("en-US").format(n);
}

/** 紧凑格式：>1000 显示 `52.6K`（原型证据存储/审计日志卡样式），否则千分位。 */
export function fmtCompact(n: number): string {
  return n > 1000 ? `${(n / 1000).toFixed(1)}K` : fmt(n);
}

/** 短日期时间 `MM-DD HH:mm`（原型时间线/证据行样式），本地时区。 */
export function fmtDateTime(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 事件来源展示名（事件流页「来源」列，spec §7.1）；未命中回退原值。 */
export const SOURCE_DISPLAY: Record<string, string> = {
  erp: "ERP-S4",
  mes: "MES",
  plm: "PLM",
  mdm: "MDM",
  crm: "CRM",
  "agent-hub": "Agent 中枢",
  "edp-adapter": "Adapter",
};

export function sourceLabel(source: string): string {
  return SOURCE_DISPLAY[source] ?? source;
}

export interface EventTypeDisplay {
  label: string;
  tone: StatusPillTone;
}

/**
 * 事件类型字典（事件流页「类型」列与类型下拉派生源，spec §7.1）：
 * 管道快照 `{TYPE}_SNAPSHOT` + 能力结果 `capability.result.*` + 适配器失败。
 * 未命中回退原值 + muted（展示型事件不迁入 seed，见契约偏差清单）。
 */
export const EVENT_TYPE_LABELS: Record<string, EventTypeDisplay> = {
  "capability.result.order_risk": { label: "订单风险", tone: "error" },
  "capability.result.order_quality": { label: "订单质量", tone: "warning" },
  "capability.result.product_readiness": { label: "产品就绪度", tone: "info" },
  "capability.result.dq_check": { label: "数据质量检查", tone: "error" },
  "adapter.sync.failed": { label: "适配器同步失败", tone: "warning" },
  ORDER_SNAPSHOT: { label: "订单快照", tone: "info" },
  CUSTOMER_SNAPSHOT: { label: "客户快照", tone: "info" },
  MATERIAL_SNAPSHOT: { label: "物料快照", tone: "info" },
  PRODUCT_SNAPSHOT: { label: "产品快照", tone: "info" },
  SUPPLIER_SNAPSHOT: { label: "供应商快照", tone: "info" },
  INVENTORY_SNAPSHOT: { label: "库存快照", tone: "info" },
  BOM_SNAPSHOT: { label: "BOM 快照", tone: "info" },
  PURCHASE_ORDER_SNAPSHOT: { label: "采购单快照", tone: "info" },
  SUPPLIER_LEAD_TIME_SNAPSHOT: { label: "交期快照", tone: "info" },
  PROJECT_SNAPSHOT: { label: "项目快照", tone: "info" },
};

export function eventTypeDisplay(eventType: string): EventTypeDisplay {
  return EVENT_TYPE_LABELS[eventType] ?? { label: eventType, tone: "muted" };
}

/** 相对时间（T5 风险列表/抽屉）："N 分钟/小时/天前"；超过 30 天或未来时间（演示锚点偏移）回退 fmtDateTime。 */
export function relTime(iso: string): string {
  const ts = new Date(iso).getTime();
  if (Number.isNaN(ts)) return iso;
  const diff = Date.now() - ts;
  if (diff <= 0) return fmtDateTime(iso);
  if (diff < 60_000) return "刚刚";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`;
  const days = Math.floor(diff / 86_400_000);
  if (days <= 30) return `${days} 天前`;
  return fmtDateTime(iso);
}
