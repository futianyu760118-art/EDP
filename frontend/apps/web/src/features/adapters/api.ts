import { apiClient } from "../auth/api";
import type { Schemas } from "../../mocks/types";

const BASE = "/api/v1";

// SDK 生成类型单点（T8 契约冻结：B.12 适配器运维 + B.7 POST /systems）
export type AdapterListItem = Schemas["AdapterListItem"];
export type AdapterStatusResponse = Schemas["AdapterStatusResponse"];
export type AdapterSyncResponse = Schemas["AdapterSyncResponse"];
export type AdapterJobItem = Schemas["AdapterJobItem"];
export type AdapterJobsResponse = Schemas["AdapterJobsResponse"];
export type SystemCreateRequest = Schemas["SystemCreateRequest"];
export type SystemCreatedResponse = Schemas["SystemCreatedResponse"];
export type SystemResponse = Schemas["SystemResponse"];
export type SystemUpdateRequest = Schemas["SystemUpdateRequest"];
export type SystemTestResponse = Schemas["SystemTestResponse"];
export type SyncStats = Schemas["SyncStats"];

/**
 * 清单行：契约五字段（adapter/mode/status/health/last_sync_at）+ MSW 演示
 * 扩展（access/team/isolation/health_pct/last_sync——真实契约不含，真模式按
 * W3-01 口径「—」降级）。
 */
export interface AdapterRow extends AdapterListItem {
  last_sync?: string;
  access?: string;
  team?: string;
  isolation?: string;
  health_pct?: number;
}

export interface AdapterListData {
  items: AdapterRow[];
  next_cursor?: string | null;
}

/** 认证配置（B.7 auth_config：kind + secret_ref；type 别名以兼容契约索引签名）。 */
export type SystemAuthConfig = {
  kind: "apikey" | "basic";
  secret_ref: string;
};

export const SYSTEM_TYPE_OPTIONS = [
  { value: "SOURCE", label: "SOURCE · 源系统" },
  { value: "CONSUMER", label: "CONSUMER · 消费系统" },
] as const;

export const adaptersApi = {
  /** B.12 GET /admin/adapters：适配器清单与运行状态。 */
  list: (): Promise<AdapterListData> =>
    apiClient.get<AdapterListData>(`${BASE}/admin/adapters`),

  /** B.12 GET /admin/adapters/{name}/status：最近一次同步（轮询用）。 */
  status: (name: string): Promise<AdapterStatusResponse> =>
    apiClient.get<AdapterStatusResponse>(
      `${BASE}/admin/adapters/${encodeURIComponent(name)}/status`,
    ),

  /** T5 GET /admin/adapters/{name}/jobs：任务历史（ops.tasks 简投影，日志抽屉历史下拉）。 */
  jobs: (name: string): Promise<AdapterJobsResponse> =>
    apiClient.get<AdapterJobsResponse>(
      `${BASE}/admin/adapters/${encodeURIComponent(name)}/jobs`,
    ),

  /** B.12 POST /admin/adapters/{name}/sync（测试连接走 incremental）→ 202。 */
  sync: (
    name: string,
    mode: "incremental" | "full" | "replay" = "incremental",
  ): Promise<AdapterSyncResponse> =>
    apiClient.post<AdapterSyncResponse>(
      `${BASE}/admin/adapters/${encodeURIComponent(name)}/sync`,
      { mode },
    ),

  /** B.7 POST /systems（新增适配器注册）→ 201；同名 409。 */
  createSystem: (body: SystemCreateRequest): Promise<SystemCreatedResponse> =>
    apiClient.post<SystemCreatedResponse>(`${BASE}/systems`, body),

  /** T50 GET /systems/{id}：系统详情（编辑弹窗预填）。 */
  getSystem: (systemId: string): Promise<SystemResponse> =>
    apiClient.get<SystemResponse>(`${BASE}/systems/${encodeURIComponent(systemId)}`),

  /** T50 PUT /systems/{id}：局部更新（adapter_config 变更同步装配）。 */
  updateSystem: (systemId: string, body: SystemUpdateRequest): Promise<SystemResponse> =>
    apiClient.put<SystemResponse>(`${BASE}/systems/${encodeURIComponent(systemId)}`, body),

  /** T50 DELETE /systems/{id} → 204。 */
  deleteSystem: (systemId: string): Promise<void> =>
    apiClient.delete<void>(`${BASE}/systems/${encodeURIComponent(systemId)}`),

  /** T50 POST /systems/{id}/test：驱动配置探活。 */
  testSystem: (systemId: string): Promise<SystemTestResponse> =>
    apiClient.post<SystemTestResponse>(`${BASE}/systems/${encodeURIComponent(systemId)}/test`, {}),
};
