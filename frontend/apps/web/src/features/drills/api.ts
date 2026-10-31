import { apiClient } from "../auth/api";
import type { Schemas } from "../../mocks/types";

const BASE = "/api/v1";

// SDK 生成类型单点（W5 契约冻结：EDP-502 演练记录只读归档）
export type DrillRecord = Schemas["DrillRecord"];
export type DrillRecordsOut = Schemas["DrillRecordsOut"];

/** drill_type 受控值（下划线，T7 备忘）：switchover / pitr / tenant_restore。 */
export type DrillType = "switchover" | "pitr" | "tenant_restore";

/** 演练结果受控值：SUCCEEDED / FAILED / PLANNED（executed_at null = 未执行）。 */
export type DrillResult = "SUCCEEDED" | "FAILED" | "PLANNED";

export const drillsApi = {
  list: (): Promise<DrillRecordsOut> => apiClient.get<DrillRecordsOut>(`${BASE}/admin/drills`),
};
