import { apiClient } from "../auth/api";
import type { HealthResponse, Schemas } from "../../mocks/types";

const BASE = "/api/v1";

export type DrillRecord = Schemas["DrillRecord"];
export type DrillRecordsOut = Schemas["DrillRecordsOut"];

export const healthApi = {
  /** B.13 深层健康（db_ha/outbox_pending/last_sync/version + ops_metrics）。 */
  deep: (): Promise<HealthResponse> =>
    apiClient.get<HealthResponse>(`${BASE}/health?deep=true`),
  /** T7 演练记录只读归档（备份卡读数：switchover readings 备份相关键值）。 */
  drills: (): Promise<DrillRecordsOut> => apiClient.get<DrillRecordsOut>(`${BASE}/admin/drills`),
};
