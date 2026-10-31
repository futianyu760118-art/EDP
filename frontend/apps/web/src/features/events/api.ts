import { apiClient } from "../auth/api";
import type {
  AdapterSummary,
  AdapterSyncResponse,
  EventResponse,
  EvidenceRecord,
  HealthResponse,
  Page,
} from "../../mocks/types";

const BASE = "/api/v1";

/** 列表页大小：与 EventsPage 分页区间计算共用。 */
export const EVENTS_PAGE_LIMIT = 20;

/** GET /events 查询参数（B.3；event_type/risk_level/since/until 闭区间过滤；
 *  event_type_prefix 前缀 LIKE 过滤（与 event_type 互斥——W6 契约 regen）。 */
export interface EventListParams {
  event_type?: string;
  event_type_prefix?: string;
  risk_level?: string;
  since?: string;
  until?: string;
  limit?: number;
  cursor?: string | null;
}

export type EventsPage = Page<EventResponse>;

/** 事件流取数（spec §7.1）：列表/health KPI/适配器下拉/回放/结果证据。 */
export const eventsApi = {
  list: (params: EventListParams = {}): Promise<EventsPage> => {
    const q = new URLSearchParams();
    if (params.event_type) q.set("event_type", params.event_type);
    if (params.event_type_prefix) q.set("event_type_prefix", params.event_type_prefix);
    if (params.risk_level) q.set("risk_level", params.risk_level);
    if (params.since) q.set("since", params.since);
    if (params.until) q.set("until", params.until);
    q.set("limit", String(params.limit ?? EVENTS_PAGE_LIMIT));
    if (params.cursor) q.set("cursor", params.cursor);
    return apiClient.get<EventsPage>(`${BASE}/events?${q.toString()}`);
  },
  /** KPI 带数据源（T12）：ops_metrics 真实子集 + mock 扩展字段。 */
  health: (): Promise<HealthResponse> => apiClient.get<HealthResponse>(`${BASE}/health`),
  /** 回放向导目标适配器下拉（T17 消费）。 */
  adapters: (): Promise<Page<AdapterSummary>> =>
    apiClient.get<Page<AdapterSummary>>(`${BASE}/admin/adapters`),
  /** 回放（T17 向导提交）：202 Accepted → sync_id/status。 */
  replay: (name: string, body: { mode: "replay"; since?: string }): Promise<AdapterSyncResponse> =>
    apiClient.post<AdapterSyncResponse>(`${BASE}/admin/adapters/${name}/sync`, body),
  /** 结果事件关联证据（详情抽屉，T17 消费）：ref_type=RESULT 逆向追溯。 */
  resultEvidence: (eventId: string): Promise<Page<EvidenceRecord>> =>
    apiClient.get<Page<EvidenceRecord>>(
      `${BASE}/evidence?ref_type=RESULT&ref_id=${encodeURIComponent(eventId)}`,
    ),
};
