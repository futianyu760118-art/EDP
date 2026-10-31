import { apiClient } from "../auth/api";
import type { Schemas } from "../../mocks/types";

const BASE = "/api/v1";

// SDK 生成类型单点（T8 契约冻结：EDP-404 五端点）
export type PendingDecisionItem = Schemas["PendingDecisionItem"];
export type PendingDecisionsData = Schemas["PendingDecisionsResponse"];
export type DecisionCreateRequest = Schemas["DecisionCreateRequest"];
export type DecisionCreatedResponse = Schemas["DecisionCreatedResponse"];
export type ActionListItem = Schemas["ActionListItem"];
export type ActionDetail = Schemas["ActionDetailResponse"];
export type ActionTransitionRequest = Schemas["ActionTransitionRequest"];
export type ActionTransitionResponse = Schemas["ActionTransitionResponse"];
export type TransitionItem = Schemas["TransitionItem"];

export type ActionStatus =
  | "PROPOSED"
  | "ASSIGNED"
  | "ACCEPTED"
  | "APPROVED"
  | "EXECUTING"
  | "COMPLETED"
  | "VERIFIED"
  | "CANCELLED"
  | "REJECTED";

/** 待决列表页大小（B.9 pending 默认 limit=5，页面取一页 20）。 */
export const DECISIONS_PENDING_LIMIT = 20;
/** 行动列表页大小（与 ActionsPage 分页区间计算共用）。 */
export const ACTIONS_PAGE_LIMIT = 20;

export interface ActionsListParams {
  status?: ActionStatus;
  owner?: string;
  case_id?: string;
  limit?: number;
  cursor?: string | null;
}

/** GET /actions 分页（Page_ActionListItem_：total 可选——缺省走降级导航）。 */
export interface ActionsPageData {
  items: ActionListItem[];
  next_cursor: string | null;
  total?: number | null;
}

export const decisionsActionsApi = {
  /** B.9 GET /ebms/decisions/pending（risk 优先 + created_at ASC；total_pending 全量计数）。 */
  pendingDecisions: (limit = DECISIONS_PENDING_LIMIT): Promise<PendingDecisionsData> =>
    apiClient.get<PendingDecisionsData>(`${BASE}/ebms/decisions/pending?limit=${limit}`),

  /** B.5 POST /decisions/cases/{id}/records（Human-Only：GUARD_POLICY_DENIED 由页面分支呈现）。 */
  submitDecision: (
    caseId: string,
    body: DecisionCreateRequest,
  ): Promise<DecisionCreatedResponse> =>
    apiClient.post<DecisionCreatedResponse>(`${BASE}/decisions/cases/${caseId}/records`, body),

  /** B.5 GET /actions（status/owner/case_id 过滤 + 游标，简投影含 allowed_to）。 */
  listActions: (params: ActionsListParams = {}): Promise<ActionsPageData> => {
    const q = new URLSearchParams();
    if (params.status) q.set("status", params.status);
    if (params.owner) q.set("owner", params.owner);
    if (params.case_id) q.set("case_id", params.case_id);
    q.set("limit", String(params.limit ?? ACTIONS_PAGE_LIMIT));
    if (params.cursor) q.set("cursor", params.cursor);
    return apiClient.get<ActionsPageData>(`${BASE}/actions?${q.toString()}`);
  },

  /** B.5 GET /actions/{id}（完整对象 + allowed_to）。 */
  actionDetail: (actionId: string): Promise<ActionDetail> =>
    apiClient.get<ActionDetail>(`${BASE}/actions/${actionId}`),

  /** B.5 PATCH /actions/{id}/status（乐观锁 from_status；422 附 allowed_to / 409 CONFLICT）。 */
  transitionAction: (
    actionId: string,
    body: ActionTransitionRequest,
  ): Promise<ActionTransitionResponse> =>
    apiClient.request<ActionTransitionResponse>(`${BASE}/actions/${actionId}/status`, {
      method: "PATCH",
      body,
    }),
};
