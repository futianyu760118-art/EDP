import type { Schemas } from "../types";
import { daysBefore, hoursBefore } from "../lib/demo-time";
import { TENANT_ID, mockUuid } from "./ids";

/**
 * W5 租户平台面 fixtures（EDP-501 / B.14）：10 租户覆盖三状态
 * （ACTIVE×7 / SUSPENDED×2 / CANCELLED×1）× 四计划；default 租户与
 * auth handlers / GET tenants/current 保持一致（TENANT_ID + slug default）。
 * 形状对齐 SDK TenantSummary/TenantDetail/TenantMemberItem/TenantQuotaInfo（T9 契约冻结）。
 */
export type TenantRow = Schemas["TenantSummary"];
export type TenantDetailData = Schemas["TenantDetail"];
export type TenantMemberRow = Schemas["TenantMemberItem"];
export type TenantQuotaInfoData = Schemas["TenantQuotaInfo"];
export type UsageItemData = Schemas["UsageItem"];

/** 列表用量摘要（mock 扩展：B.14 TenantSummary 无用量字段，页面「用量摘要」列需要；真实后端补齐后对齐）。 */
export interface TenantUsageSummary {
  storage_used_gb: number | null;
  events_this_month: number | null;
}

// ---- 租户 id（5xx 段；default 复用全局 TENANT_ID 保证与 auth/current 一致） ----
export const TENANT_ACME_ID = mockUuid(502);
export const TENANT_DEMO_ID = mockUuid(503);
export const TENANT_TRIAL_ID = mockUuid(504);
export const TENANT_PREMIUM_ID = mockUuid(505);
export const TENANT_HR_ID = mockUuid(506);
export const TENANT_MFG_ID = mockUuid(507);
export const TENANT_RETAIL_ID = mockUuid(508);
export const TENANT_LEGACY_ID = mockUuid(509);
export const TENANT_NW_ID = mockUuid(510);

// ---- 平台用户目录（邀请成员下拉源；GET /admin/users 真契约 AdminUserItem——display_name 可空透传） ----
export interface PlatformUser {
  user_id: string;
  username: string;
  display_name: string | null;
}

export const USER_ADMIN = mockUuid(531);
export const USER_MANAGER1 = mockUuid(532);
export const USER_ANALYST1 = mockUuid(533);
export const USER_OPS1 = mockUuid(534);
const USER_STEWARD1 = mockUuid(535);
const USER_OWNER1 = mockUuid(536);
export const USER_NEWHIRE = mockUuid(537);

export const platformUsers: PlatformUser[] = [
  { user_id: USER_ADMIN, username: "admin", display_name: "平台运营" },
  { user_id: USER_MANAGER1, username: "manager1", display_name: "陈经理" },
  { user_id: USER_ANALYST1, username: "analyst1", display_name: "李审计" },
  { user_id: USER_OPS1, username: "ops1", display_name: "王操作" },
  { user_id: USER_STEWARD1, username: "steward1", display_name: "赵数据" },
  { user_id: USER_OWNER1, username: "owner1", display_name: "周业务" },
  // display_name 空透传用例（下拉 label 回退 username）
  { user_id: USER_NEWHIRE, username: "newhire", display_name: null },
];

/** B.14 租户清单（handler 按 created_at DESC 排序返回）。 */
export const tenantRows: TenantRow[] = [
  { tenant_id: TENANT_ID, slug: "default", name: "默认租户", plan: "STANDARD", status: "ACTIVE", created_at: hoursBefore(6) },
  { tenant_id: TENANT_ACME_ID, slug: "acme", name: "ACME · 华东事业群", plan: "DEDICATED", status: "ACTIVE", created_at: hoursBefore(30) },
  { tenant_id: TENANT_DEMO_ID, slug: "demo", name: "DEMO · 华南事业群", plan: "STANDARD", status: "ACTIVE", created_at: daysBefore(3) },
  { tenant_id: TENANT_TRIAL_ID, slug: "trial-sandbox", name: "试点沙箱", plan: "TRIAL", status: "ACTIVE", created_at: daysBefore(5) },
  { tenant_id: TENANT_PREMIUM_ID, slug: "premium-lab", name: "高级实验室", plan: "PREMIUM", status: "ACTIVE", created_at: daysBefore(9) },
  { tenant_id: TENANT_HR_ID, slug: "hr-workspace", name: "人事工作空间", plan: "STANDARD", status: "ACTIVE", created_at: daysBefore(14) },
  { tenant_id: TENANT_MFG_ID, slug: "mfg-pilot", name: "制造试点", plan: "TRIAL", status: "SUSPENDED", created_at: daysBefore(21) },
  { tenant_id: TENANT_RETAIL_ID, slug: "south-retail", name: "华南零售", plan: "STANDARD", status: "SUSPENDED", created_at: daysBefore(33) },
  { tenant_id: TENANT_LEGACY_ID, slug: "legacy-erp", name: "旧 ERP 迁移", plan: "PREMIUM", status: "CANCELLED", created_at: daysBefore(48) },
  { tenant_id: TENANT_NW_ID, slug: "northwest", name: "西北事业部", plan: "PREMIUM", status: "ACTIVE", created_at: daysBefore(60) },
];

/** 列表用量摘要（暂停/注销租户计量停采 → null）。 */
const usageBySlug: Record<string, TenantUsageSummary> = {
  default: { storage_used_gb: 486.2, events_this_month: 184_213 },
  acme: { storage_used_gb: 684.0, events_this_month: 18_421 },
  demo: { storage_used_gb: 96.5, events_this_month: 3_204 },
  "trial-sandbox": { storage_used_gb: 8.2, events_this_month: 512 },
  "premium-lab": { storage_used_gb: 1_204.7, events_this_month: 1_286_400 },
  "hr-workspace": { storage_used_gb: 42.1, events_this_month: 8_930 },
  northwest: { storage_used_gb: 88.4, events_this_month: 96_320 },
};

export function tenantUsageSummaryOf(slug: string): TenantUsageSummary | null {
  return usageBySlug[slug] ?? null;
}

/** 详情用量（B.14 TenantUsage；api_calls_today 仅展示扩展）。 */
export function tenantUsageOf(slug: string): Schemas["TenantUsage"] | null {
  const summary = tenantUsageSummaryOf(slug);
  if (!summary) return null;
  return { ...summary, api_calls_today: Math.round((summary.events_this_month ?? 0) / 20) };
}

// ---- 套餐默认配额（B.14 PLAN_QUOTAS 口径） ----
export const PLAN_QUOTAS: Record<string, TenantQuotaInfoData> = {
  TRIAL: { api_rate_limit: 60, batch_max_events: 100, events_per_month: 100_000, pool_share: "0.05", query_timeout_ms: 15_000, storage_gb: 100 },
  STANDARD: { api_rate_limit: 120, batch_max_events: 500, events_per_month: 1_000_000, pool_share: "0.1", query_timeout_ms: 30_000, storage_gb: 500 },
  PREMIUM: { api_rate_limit: 600, batch_max_events: 2_000, events_per_month: 5_000_000, pool_share: "0.2", query_timeout_ms: 60_000, storage_gb: 2_000 },
  DEDICATED: { api_rate_limit: 1_200, batch_max_events: 5_000, events_per_month: 20_000_000, pool_share: "1.0", query_timeout_ms: 120_000, storage_gb: 8_192 },
};

/** 运维调整覆盖（acme 曾临时提额，演示「配额可调整」）。 */
const quotaOverrides: Record<string, Partial<TenantQuotaInfoData>> = {
  acme: { storage_gb: 3_000, api_rate_limit: 1_500 },
};

export function tenantQuotaOf(tenant: TenantRow): TenantQuotaInfoData {
  const base = PLAN_QUOTAS[tenant.plan] ?? PLAN_QUOTAS.STANDARD;
  return { ...base, ...(quotaOverrides[tenant.slug] ?? {}) };
}

export function tenantQuotaDetailOf(tenant: TenantRow): Schemas["TenantQuotaDetail"] {
  return {
    ...tenantQuotaOf(tenant),
    tenant_id: tenant.tenant_id,
    updated_at: quotaOverrides[tenant.slug] != null ? daysBefore(2) : tenant.created_at,
  };
}

// ---- 成员（B.14 tenant_members；display_name join platformUsers） ----
const MEMBER_ID_BASE = 511;
const member = (n: number, userId: string, roles: string[], status: string, joinedAt: string): TenantMemberRow => ({
  member_id: mockUuid(MEMBER_ID_BASE + n),
  user_id: userId,
  display_name: platformUsers.find((u) => u.user_id === userId)?.display_name ?? null,
  member_roles: roles,
  status,
  joined_at: joinedAt,
});

/** acme 四成员对齐原型租户管理页成员卡（Y. Liu/M. Chen/J. Wang/S. Kim）。 */
export const tenantMembers: Record<string, TenantMemberRow[]> = {
  [TENANT_ID]: [
    member(0, USER_ADMIN, ["ADMIN"], "ACTIVE", hoursBefore(6)),
    member(1, USER_MANAGER1, ["MANAGER"], "ACTIVE", hoursBefore(5)),
    member(2, USER_ANALYST1, ["ANALYST"], "ACTIVE", daysBefore(2)),
  ],
  [TENANT_ACME_ID]: [
    member(3, USER_ADMIN, ["ADMIN"], "ACTIVE", hoursBefore(30)),
    member(4, USER_MANAGER1, ["MANAGER", "ANALYST"], "ACTIVE", daysBefore(3)),
    member(5, USER_OPS1, ["MANAGER"], "ACTIVE", daysBefore(8)),
    member(6, USER_NEWHIRE, ["ANALYST"], "INVITED", daysBefore(1)),
  ],
  [TENANT_DEMO_ID]: [
    member(7, USER_ADMIN, ["ADMIN"], "ACTIVE", daysBefore(3)),
    member(8, USER_MANAGER1, ["MANAGER"], "DISABLED", daysBefore(2)),
  ],
  [TENANT_TRIAL_ID]: [member(9, USER_OPS1, ["ADMIN"], "ACTIVE", daysBefore(5))],
  [TENANT_PREMIUM_ID]: [
    member(10, USER_ADMIN, ["ADMIN"], "ACTIVE", daysBefore(9)),
    member(11, USER_MANAGER1, ["MANAGER"], "ACTIVE", daysBefore(6)),
  ],
  [TENANT_HR_ID]: [member(12, USER_OPS1, ["ADMIN"], "ACTIVE", daysBefore(14))],
  [TENANT_MFG_ID]: [member(13, USER_MANAGER1, ["ADMIN"], "ACTIVE", daysBefore(21))],
  [TENANT_RETAIL_ID]: [member(14, USER_OPS1, ["ADMIN"], "ACTIVE", daysBefore(33))],
  [TENANT_LEGACY_ID]: [
    member(15, USER_ADMIN, ["ADMIN"], "DISABLED", daysBefore(48)),
    member(17, USER_OPS1, ["ADMIN"], "ACTIVE", daysBefore(47)),
  ],
  [TENANT_NW_ID]: [member(16, USER_MANAGER1, ["ADMIN"], "ACTIVE", daysBefore(60))],
};

export function findTenant(tenantId: string): TenantRow | undefined {
  return tenantRows.find((t) => t.tenant_id === tenantId);
}

export function findTenantDetail(tenantId: string): TenantDetailData | undefined {
  const tenant = findTenant(tenantId);
  if (!tenant) return undefined;
  return {
    tenant_id: tenant.tenant_id,
    slug: tenant.slug,
    name: tenant.name,
    plan: tenant.plan,
    status: tenant.status,
    created_at: tenant.created_at,
    updated_at: quotaOverrides[tenant.slug] != null ? daysBefore(2) : tenant.created_at,
    cancel_scheduled_at: tenant.status === "CANCELLED" ? daysBefore(1) : null,
    quotas: tenantQuotaOf(tenant),
    usage: tenantUsageOf(tenant.slug),
  };
}

// ---- 计量日表（GET /tenants/current/usage 与 /tenants/{id}/usage 共用；default 3 天） ----
export const usageDaily: UsageItemData[] = [
  { usage_date: "2026-09-28", events_in: 18_421, events_duplicated: 12, api_calls: 2_842, throttled_429: 3, storage_gb: "486.2" },
  { usage_date: "2026-09-27", events_in: 17_902, events_duplicated: 9, api_calls: 2_510, throttled_429: 1, storage_gb: "481.0" },
  { usage_date: "2026-09-26", events_in: 16_358, events_duplicated: 15, api_calls: 2_337, throttled_429: 0, storage_gb: "473.4" },
];
