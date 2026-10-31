/**
 * 13.4.4 枚举统一（共享单点：存储/API 枚举值 ↔ 前端展示名/语义色）。
 * 值与设计文档 13.4.4 映射表、后端种子（backend migrations/platform/0005_seed）
 * 保持一致——改枚举值必须两侧同步过测试。
 */

/** 展示语义色（与 components/StatusPill 的 StatusPillTone 对齐）。 */
export type LabelTone = "success" | "warning" | "error" | "info" | "muted";

export interface LabelWithTone {
  label: string;
  tone: LabelTone;
}

/** 五角色中文名（PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST/SERVICE）。 */
export const ROLE_LABELS: Record<string, string> = {
  PLATFORM_ADMIN: "平台运营",
  ADMIN: "工作空间管理员",
  MANAGER: "数据管理员·业务负责人",
  ANALYST: "审计员·操作员",
  SERVICE: "服务主体",
};

/** 角色展示名；未知角色码回显原值，undefined/空 → 空串。 */
export function roleLabel(role: string | undefined): string {
  if (!role) return "";
  return ROLE_LABELS[role] ?? role;
}

/** 租户状态（platform.tenants.status，迁移 0001 CHECK 四值）。 */
export const TENANT_STATUS_LABELS: Record<string, LabelWithTone> = {
  PROVISIONING: { label: "开通中", tone: "info" },
  ACTIVE: { label: "正常", tone: "success" },
  SUSPENDED: { label: "已暂停", tone: "warning" },
  CANCELLED: { label: "已注销", tone: "muted" },
};

/** 风险等级（event/decision 共用 P 系；原型 L3→P1/L2→P2/L1→P3 分档映射）。 */
export const RISK_LEVEL_LABELS: Record<string, LabelWithTone> = {
  P0: { label: "P0 · 紧急", tone: "error" },
  P1: { label: "P1 · 高", tone: "error" },
  P2: { label: "P2 · 中", tone: "warning" },
  P3: { label: "P3 · 低", tone: "info" },
};

/** 套餐版本（TRIAL/STANDARD/PREMIUM/DEDICATED）。 */
export const PLAN_LABELS: Record<string, string> = {
  TRIAL: "体验版",
  STANDARD: "基础版",
  PREMIUM: "专业版",
  DEDICATED: "企业版",
};

/** 套餐展示名；未知值回显原码，undefined/空 → 基础版（与侧边栏缺省一致）。 */
export function planLabel(plan: string | undefined): string {
  if (!plan) return PLAN_LABELS.STANDARD;
  return PLAN_LABELS[plan] ?? plan;
}
