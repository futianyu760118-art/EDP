import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { qualityApi, type RecheckScope } from "./api";

/** 质量报告（真端点 T3 交付；错误由页面错误态承接）。 */
export function useQualityReport() {
  return useQuery({
    queryKey: ["quality", "report"],
    queryFn: () => qualityApi.reports(),
    placeholderData: keepPreviousData,
    retry: 1,
  });
}

/** 异常卡（真实 EBMS API；OPEN 前 N 条）。 */
export function useQualityExceptions(limit = 3) {
  return useQuery({
    queryKey: ["quality", "exceptions", limit],
    queryFn: () => qualityApi.exceptions(limit),
  });
}

/** 重校验提交（POST rechecks scope → 202）。 */
export function useRecheck() {
  return useMutation({ mutationFn: (scope: RecheckScope) => qualityApi.recheck(scope) });
}

/** 任务日志抽屉轮询（1s；任务进入终态后停止）。 */
export function useQualityTask(taskId: string | undefined) {
  return useQuery({
    queryKey: ["quality", "task", taskId],
    queryFn: () => qualityApi.task(taskId!),
    enabled: taskId != null,
    refetchInterval: (query) =>
      query.state.data?.status === "RUNNING" ? 1_000 : false,
  });
}
