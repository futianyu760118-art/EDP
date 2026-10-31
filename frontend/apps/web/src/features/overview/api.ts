import { apiClient } from "../auth/api";
import type {
  AdapterSummary,
  AuditLogItem,
  EventResponse,
  ExceptionItem,
  HealthResponse,
  ObjectResponse,
  Page,
  QualityReport,
} from "../../mocks/types";

const BASE = "/api/v1";

/** GET /objects 分页：total 为 mock 扩展（真实后端 Page envelope 无 total，T18 契约回填对齐）。 */
export interface ObjectsPage {
  items: ObjectResponse[];
  next_cursor: string | null;
  total?: number;
}

/** 总览取数：类型按 MSW handler 实际响应形状（未冻结契约暂从 mocks/types 引用，T18 迁 api-sdk）。 */
export const overviewApi = {
  coverage: () => apiClient.get<QualityReport["coverage"]>(`${BASE}/admin/quality/coverage`),
  qualityReport: () => apiClient.get<QualityReport>(`${BASE}/admin/quality/reports`),
  health: () => apiClient.get<HealthResponse>(`${BASE}/health?deep=true`),
  adapters: () => apiClient.get<Page<AdapterSummary>>(`${BASE}/admin/adapters`),
  topExceptions: () => apiClient.get<Page<ExceptionItem>>(`${BASE}/ebms/exceptions?severity=P1&limit=3`),
  recentEvents: () => apiClient.get<Page<EventResponse>>(`${BASE}/events?limit=5`),
  recentAudit: () => apiClient.get<Page<AuditLogItem>>(`${BASE}/audit-logs?limit=4`),
  objectsTotal: () => apiClient.get<ObjectsPage>(`${BASE}/objects?limit=1`),
};
