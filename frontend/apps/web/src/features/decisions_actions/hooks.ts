import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import {
  ACTIONS_PAGE_LIMIT,
  type ActionStatus,
  type ActionTransitionRequest,
  type DecisionCreateRequest,
  decisionsActionsApi,
} from "./api";

export interface ActionsFilters {
  status?: string;
  owner?: string;
  caseId?: string;
}

/** B.9 待决案例列表（total_pending 驱动头部角标）。 */
export function usePendingDecisions() {
  return useQuery({
    queryKey: ["decisions", "pending"],
    queryFn: () => decisionsActionsApi.pendingDecisions(),
  });
}

/** B.5 决策记录提交（Human-Only）；toast/invalidate 由页面分支处理。 */
export function useSubmitDecision() {
  return useMutation({
    mutationFn: ({ caseId, body }: { caseId: string; body: DecisionCreateRequest }) =>
      decisionsActionsApi.submitDecision(caseId, body),
  });
}

/** B.5 行动列表（keepPreviousData 防翻页/筛选闪烁）。 */
export function useActionsList(filters: ActionsFilters, cursor: string | null) {
  return useQuery({
    queryKey: ["actions", "list", filters.status ?? "", filters.owner ?? "", filters.caseId ?? "", cursor],
    queryFn: () =>
      decisionsActionsApi.listActions({
        status: filters.status as ActionStatus | undefined,
        owner: filters.owner,
        case_id: filters.caseId,
        limit: ACTIONS_PAGE_LIMIT,
        cursor,
      }),
    placeholderData: keepPreviousData,
  });
}

/** B.5 行动详情（抽屉打开时启用；422/409 后 invalidate 自动重拉）。 */
export function useActionDetail(actionId: string | null) {
  return useQuery({
    queryKey: ["actions", "detail", actionId],
    queryFn: () => decisionsActionsApi.actionDetail(actionId!),
    enabled: actionId != null,
    retry: 1,
  });
}

/** B.5 状态机转移（乐观锁 from_status）。 */
export function useTransitionAction() {
  return useMutation({
    mutationFn: ({ actionId, body }: { actionId: string; body: ActionTransitionRequest }) =>
      decisionsActionsApi.transitionAction(actionId, body),
  });
}
