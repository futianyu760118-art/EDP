import { apiClient } from "../auth/api";
import type { Schemas } from "../../mocks/types";

const BASE = "/api/v1";

// SDK 生成类型单点（B.10 契约冻结）
export type TraceListItem = Schemas["TraceListItem"];
export type TraceDetail = Schemas["TraceDetail"];
export type ToolCallItem = Schemas["ToolCallItem"];
export type PageTraceList = Schemas["Page_TraceListItem_"];

/** 列表页大小（与 TracesPage 分页区间计算共用）。 */
export const TRACES_PAGE_LIMIT = 20;

/** Trace 状态五值（B.10 status 枚举）。 */
export type TraceStatus = "RUNNING" | "SUCCEEDED" | "FAILED" | "TIMEOUT" | "ABORTED";

export const TRACE_STATUS_OPTIONS: { value: TraceStatus; label: string }[] = [
  { value: "SUCCEEDED", label: "SUCCEEDED（成功）" },
  { value: "RUNNING", label: "RUNNING（执行中）" },
  { value: "FAILED", label: "FAILED（失败）" },
  { value: "TIMEOUT", label: "TIMEOUT（超时）" },
  { value: "ABORTED", label: "ABORTED（中止）" },
];

/** GET /traces 查询参数（agent_id/task_id/capability_id/since + 游标）。 */
export interface TraceListParams {
  agent_id?: string;
  task_id?: string;
  capability_id?: string;
  since?: string;
  limit?: number;
  cursor?: string | null;
}

export const tracesApi = {
  /** B.10 GET /traces（简投影列表，started_at DESC）。 */
  list: (params: TraceListParams = {}): Promise<PageTraceList> => {
    const q = new URLSearchParams();
    if (params.agent_id) q.set("agent_id", params.agent_id);
    if (params.task_id) q.set("task_id", params.task_id);
    if (params.capability_id) q.set("capability_id", params.capability_id);
    if (params.since) q.set("since", params.since);
    q.set("limit", String(params.limit ?? TRACES_PAGE_LIMIT));
    if (params.cursor) q.set("cursor", params.cursor);
    return apiClient.get<PageTraceList>(`${BASE}/traces?${q.toString()}`);
  },

  /** B.10 GET /traces/{trace_id}（完整轨迹 + tool_calls[] seq 升序）。 */
  detail: (traceId: string): Promise<TraceDetail> =>
    apiClient.get<TraceDetail>(`${BASE}/traces/${encodeURIComponent(traceId)}`),
};
