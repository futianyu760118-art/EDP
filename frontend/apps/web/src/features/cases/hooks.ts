import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { CASES_PAGE_LIMIT, casesApi, type CaseListParams, type CaseRiskLevel, type CaseStatus } from "./api";

export interface CasesFilters {
  status?: CaseStatus;
  riskLevel?: CaseRiskLevel;
}

/** 案例分页列表（keepPreviousData 防翻页/筛选闪烁）。 */
export function useCasesList(filters: CasesFilters, cursor: string | null) {
  const params: CaseListParams = {
    status: filters.status,
    risk_level: filters.riskLevel,
    limit: CASES_PAGE_LIMIT,
    cursor,
  };
  return useQuery({
    queryKey: ["cases", "list", filters.status ?? "", filters.riskLevel ?? "", cursor],
    queryFn: () => casesApi.list(params),
    placeholderData: keepPreviousData,
  });
}

/** 案例详情（闭环聚合：event/steps/actions/evidence_chain 扩展字段）。 */
export function useCaseDetail(caseId: string | undefined) {
  return useQuery({
    queryKey: ["cases", "detail", caseId],
    queryFn: () => casesApi.detail(caseId!),
    enabled: caseId != null,
    retry: 1,
  });
}

/** 证据链节点 verify 联动：结果由页面维护（本会话状态 pill，模式同证据库页）。 */
export function useVerifyCaseEvidence() {
  return useMutation({
    mutationFn: (evidenceId: string) => casesApi.verifyEvidence(evidenceId),
  });
}
