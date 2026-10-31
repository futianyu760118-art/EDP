import { apiClient } from "../auth/api";
import type { EvidenceVerifyResponse, Schemas } from "../../mocks/types";

const BASE = "/api/v1";

// SDK 生成类型单点（T8 契约冻结：CaseDetailResponse 含 event/steps/actions/evidence_chain 扩展）
export type CaseListItem = Schemas["CaseListItem"];
export type CaseDetail = Schemas["CaseDetailResponse"];
export type CaseStepItem = Schemas["CaseStepItem"];
export type CaseEventSummary = Schemas["CaseEventSummary"];
export type CaseActionItem = Schemas["CaseActionItem"];
export type ActionTransitionRef = Schemas["ActionTransitionRef"];
export type EvidenceChainItem = Schemas["EvidenceChainItem"];

/** 列表页大小（与 CasesPage 分页区间计算共用）。 */
export const CASES_PAGE_LIMIT = 20;

export type CaseStatus = "OPEN" | "DECIDED" | "CANCELLED";
export type CaseRiskLevel = "P0" | "P1" | "P2" | "P3";

export interface CaseListParams {
  status?: CaseStatus;
  risk_level?: CaseRiskLevel;
  limit?: number;
  cursor?: string | null;
}

/** GET /decisions/cases 分页（Page_CaseListItem_：total 可选——真契约缺省走降级导航）。 */
export interface CasesPageData {
  items: CaseListItem[];
  next_cursor: string | null;
  total?: number | null;
}

export const casesApi = {
  list: (params: CaseListParams = {}): Promise<CasesPageData> => {
    const q = new URLSearchParams();
    if (params.status) q.set("status", params.status);
    if (params.risk_level) q.set("risk_level", params.risk_level);
    q.set("limit", String(params.limit ?? CASES_PAGE_LIMIT));
    if (params.cursor) q.set("cursor", params.cursor);
    return apiClient.get<CasesPageData>(`${BASE}/decisions/cases?${q.toString()}`);
  },
  detail: (caseId: string): Promise<CaseDetail> =>
    apiClient.get<CaseDetail>(`${BASE}/decisions/cases/${caseId}`),
  /** 证据链 EVIDENCE 层节点校验（复用既有端点 GET /evidence/{id}/verify，设计 13.6.5）。 */
  verifyEvidence: (evidenceId: string): Promise<EvidenceVerifyResponse> =>
    apiClient.get<EvidenceVerifyResponse>(`${BASE}/evidence/${evidenceId}/verify`),
};
