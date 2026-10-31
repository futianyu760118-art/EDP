import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { evidenceApi, EVIDENCE_PAGE_LIMIT, type EvidenceListParams } from "./api";

export interface EvidenceFilters {
  /** 卡内搜索（后端 q 参数，300ms 防抖在页面层做） */
  q?: string;
  sourceSystem?: string;
}

/** 证据分页列表（keepPreviousData 防翻页闪烁）。 */
export function useEvidenceList(filters: EvidenceFilters, cursor: string | null) {
  const params: EvidenceListParams = {
    q: filters.q || undefined,
    limit: EVIDENCE_PAGE_LIMIT,
    cursor,
  };
  return useQuery({
    queryKey: ["evidence", "list", filters.q ?? "", cursor],
    queryFn: () => evidenceApi.list(params),
    placeholderData: keepPreviousData,
  });
}

/** 同对象证据集合（链图用）。 */
export function useObjectEvidence(objectId: string | undefined) {
  return useQuery({
    queryKey: ["evidence", "by-object", objectId],
    queryFn: () => evidenceApi.list({ object_id: objectId!, limit: 20 }),
    enabled: objectId != null,
    select: (page) => page.items,
  });
}

/** KPI 带数据源（/health.ops_metrics）。 */
export function useEvidenceHealth() {
  return useQuery({
    queryKey: ["evidence", "health"],
    queryFn: evidenceApi.health,
    select: (health) => health.ops_metrics,
    refetchInterval: 30_000,
  });
}

/** verify 联动：点击校验 → 结果由页面维护（本会话状态 pill）。 */
export function useVerifyEvidence() {
  return useMutation({
    mutationFn: (evidenceId: string) => evidenceApi.verify(evidenceId),
  });
}

/** 重索引提交（T6 POST reindex scope=ALL → 202）。 */
export function useReindexEvidence() {
  return useMutation({ mutationFn: evidenceApi.reindex });
}

/** 重索引任务轮询（quality tasks 端点；1s 推进，终态停止）。 */
export function useReindexTask(taskId: string | null) {
  return useQuery({
    queryKey: ["evidence", "reindex-task", taskId],
    queryFn: () => evidenceApi.reindexTask(taskId!),
    enabled: taskId != null,
    refetchInterval: (query) =>
      query.state.data?.status === "RUNNING" ? 1_000 : false,
  });
}
