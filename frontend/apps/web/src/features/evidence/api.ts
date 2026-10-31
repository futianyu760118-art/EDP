import { apiClient } from "../auth/api";
import type {
  EvidenceRecord,
  EvidenceVerifyResponse,
  HealthResponse,
  Page,
  QualityTask,
  Schemas,
} from "../../mocks/types";

const BASE = "/api/v1";

/** 列表页大小（与 EvidencePage 分页区间计算共用）。 */
export const EVIDENCE_PAGE_LIMIT = 20;

export interface EvidenceListParams {
  object_id?: string;
  ref_type?: string;
  ref_id?: string;
  /** 模糊搜索：source_record_id/source_system（W3R 契约扩展） */
  q?: string;
  limit?: number;
  cursor?: string | null;
}

/** T6 重索引：202 响应（ReindexAccepted）——任务经 GET /admin/quality/tasks/{id} 轮询。 */
export type ReindexAccepted = Schemas["ReindexAccepted"];

export const evidenceApi = {
  list: (params: EvidenceListParams = {}): Promise<Page<EvidenceRecord>> => {
    const q = new URLSearchParams();
    if (params.object_id) q.set("object_id", params.object_id);
    if (params.ref_type) q.set("ref_type", params.ref_type);
    if (params.ref_id) q.set("ref_id", params.ref_id);
    if (params.q) q.set("q", params.q);
    q.set("limit", String(params.limit ?? EVIDENCE_PAGE_LIMIT));
    if (params.cursor) q.set("cursor", params.cursor);
    return apiClient.get<Page<EvidenceRecord>>(`${BASE}/evidence?${q.toString()}`);
  },
  detail: (evidenceId: string): Promise<EvidenceRecord> =>
    apiClient.get<EvidenceRecord>(`${BASE}/evidence/${evidenceId}`),
  verify: (evidenceId: string): Promise<EvidenceVerifyResponse> =>
    apiClient.get<EvidenceVerifyResponse>(`${BASE}/evidence/${evidenceId}/verify`),
  /** KPI 带真数据源（证据数量 ← ops_metrics.evidence_count）。 */
  health: (): Promise<HealthResponse> => apiClient.get<HealthResponse>(`${BASE}/health`),
  /** T6 重索引下发：scope=ALL（契约当前仅全量）→ 202 {task_id, status}。 */
  reindex: (): Promise<ReindexAccepted> =>
    apiClient.post<ReindexAccepted>(`${BASE}/admin/evidence/reindex`, { scope: "ALL" }),
  /** T6 任务轮询（quality tasks 端点共用，不新开查询端点）。 */
  reindexTask: (taskId: string): Promise<QualityTask> =>
    apiClient.get<QualityTask>(`${BASE}/admin/quality/tasks/${taskId}`),
};
