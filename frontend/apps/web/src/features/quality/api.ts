import { apiClient } from "../auth/api";
import type { Page, QualityReport, QualityTask } from "../../mocks/types";
import type { ExceptionItem } from "../../mocks/types";

const BASE = "/api/v1";

export type RecheckScope = "RECONCILE" | "ORPHAN" | "CHECKSUM" | "ALL";
export type RecheckAccepted = { task_id: string; status: string };

export const qualityApi = {
  /** B.13/T3 报告（四段实时聚合 + kpi/dimensions 派生）。 */
  reports: (date?: string): Promise<QualityReport> => {
    const q = date ? `?date=${encodeURIComponent(date)}` : "";
    return apiClient.get<QualityReport>(`${BASE}/admin/quality/reports${q}`);
  },
  /** 异常卡数据源（真实 API 已交付）。 */
  exceptions: (limit = 3): Promise<Page<ExceptionItem>> =>
    apiClient.get<Page<ExceptionItem>>(
      `${BASE}/ebms/exceptions?status=OPEN&limit=${limit}`,
    ),
  /** T4 重校验提交：scope → 202 {task_id, status}（后台异步执行）。 */
  recheck: (scope: RecheckScope): Promise<RecheckAccepted> =>
    apiClient.post<RecheckAccepted>(`${BASE}/admin/quality/rechecks`, { scope }),
  /** T4 任务详情（重校验/重索引轮询共用）。 */
  task: (taskId: string): Promise<QualityTask> =>
    apiClient.get<QualityTask>(`${BASE}/admin/quality/tasks/${taskId}`),
};
