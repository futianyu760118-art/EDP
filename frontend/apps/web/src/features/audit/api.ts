import { apiClient } from "../auth/api";
import type { Schemas } from "../../mocks/types";

const BASE = "/api/v1";

// SDK 生成类型单点（T8 契约冻结：EDP-401 审计日志 + 审计策略）
export type AuditLogItem = Schemas["AuditLogItem"];
export type PolicyItem = Schemas["PolicyItem"];
export type PolicyCreateRequest = Schemas["PolicyCreateRequest"];
export type PolicyUpdateRequest = Schemas["PolicyUpdateRequest"];

/** 日志列表页大小（与 AuditTable 分页区间计算共用）。 */
export const AUDIT_PAGE_LIMIT = 20;
/** 导出全量拉取封顶（超限截断 + 提示）。 */
export const AUDIT_EXPORT_MAX_ROWS = 1000;
/** 单页拉取上限（后端 limit ≤ 100）。 */
const AUDIT_FETCH_PAGE = 100;

/** 审计查询过滤（与 GET /audit-logs 查询参数一一对应；值为接口口径）。 */
export interface AuditLogFilters {
  actor_id?: string;
  resource_type?: string;
  action?: string;
  /** ISO 时刻（date 输入在页面层已归一为 `${date}T00:00:00Z`）。 */
  since?: string;
  /** ISO 时刻（归一为 `${date}T23:59:59Z`，闭区间当日含尾）。 */
  until?: string;
}

/** GET /audit-logs 分页（Page_AuditLogItem_：total 可选——缺省走降级导航）。 */
export interface AuditPageData {
  items: AuditLogItem[];
  next_cursor: string | null;
  total?: number | null;
}

export interface PolicyPageData {
  items: PolicyItem[];
  next_cursor: string | null;
  total?: number | null;
}

export interface AuditExportResult {
  rows: AuditLogItem[];
  /** 是否触及 1000 行保护上限（截断提示用）。 */
  capped: boolean;
}

export const auditApi = {
  /** B.6 GET /audit-logs（actor_id/resource_type/action/since/until + 游标）。 */
  list: (
    filters: AuditLogFilters = {},
    cursor: string | null = null,
    limit: number = AUDIT_PAGE_LIMIT,
  ): Promise<AuditPageData> => {
    const q = new URLSearchParams();
    if (filters.actor_id) q.set("actor_id", filters.actor_id);
    if (filters.resource_type) q.set("resource_type", filters.resource_type);
    if (filters.action) q.set("action", filters.action);
    if (filters.since) q.set("since", filters.since);
    if (filters.until) q.set("until", filters.until);
    q.set("limit", String(limit));
    if (cursor) q.set("cursor", cursor);
    return apiClient.get<AuditPageData>(`${BASE}/audit-logs?${q.toString()}`);
  },

  /** 导出全量拉取：按当前筛选翻页收集至游标耗尽或 1000 行封顶。 */
  listAllForExport: async (filters: AuditLogFilters = {}): Promise<AuditExportResult> => {
    const rows: AuditLogItem[] = [];
    let cursor: string | null = null;
    for (;;) {
      const page = await auditApi.list(filters, cursor, AUDIT_FETCH_PAGE);
      rows.push(...page.items);
      if (page.next_cursor == null || rows.length >= AUDIT_EXPORT_MAX_ROWS) break;
      cursor = page.next_cursor;
    }
    const capped = rows.length > AUDIT_EXPORT_MAX_ROWS;
    return { rows: rows.slice(0, AUDIT_EXPORT_MAX_ROWS), capped };
  },

  /** EDP-032 GET /admin/audit-policies（status 过滤 + 游标）。 */
  listPolicies: (
    status?: string,
    cursor: string | null = null,
  ): Promise<PolicyPageData> => {
    const q = new URLSearchParams();
    if (status) q.set("status", status);
    q.set("limit", "100");
    if (cursor) q.set("cursor", cursor);
    return apiClient.get<PolicyPageData>(`${BASE}/admin/audit-policies?${q.toString()}`);
  },

  /** EDP-032 POST /admin/audit-policies（201 完整对象；重名 409）。 */
  createPolicy: (body: PolicyCreateRequest): Promise<PolicyItem> =>
    apiClient.post<PolicyItem>(`${BASE}/admin/audit-policies`, body),

  /** EDP-032 PATCH /admin/audit-policies/{id}（局部更新；启停经 status）。 */
  updatePolicy: (policyId: string, body: PolicyUpdateRequest): Promise<PolicyItem> =>
    apiClient.request<PolicyItem>(`${BASE}/admin/audit-policies/${policyId}`, {
      method: "PATCH",
      body,
    }),

  /** EDP-032 DELETE /admin/audit-policies/{id}（204）。 */
  deletePolicy: (policyId: string): Promise<void> =>
    apiClient.request<void>(`${BASE}/admin/audit-policies/${policyId}`, {
      method: "DELETE",
    }),
};
