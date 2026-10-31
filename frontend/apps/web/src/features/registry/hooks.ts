import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { OBJECTS_PAGE_LIMIT, objectsApi } from "./api";
import type { EventResponse } from "../../mocks/types";

export interface RegistryFilters {
  /** 域下拉 → 后端 owner_domain 参数（唯一走服务端的筛选）。 */
  ownerDomain?: string;
}

/**
 * 业务对象分页列表（13.9.3）：keepPreviousData 让翻页/切筛选时保留旧页数据，
 * 避免列表闪烁。派生状态与搜索为前端过滤，不进 queryKey/queryFn。
 */
export function useObjects(filters: RegistryFilters, cursor: string | null) {
  return useQuery({
    queryKey: ["registry", "objects", filters.ownerDomain ?? "", cursor],
    queryFn: () =>
      objectsApi.list({
        owner_domain: filters.ownerDomain || undefined,
        limit: OBJECTS_PAGE_LIMIT,
        cursor,
      }),
    placeholderData: keepPreviousData,
  });
}

/** object_id → 最新能力结果 risk_level（同对象多事件取 occurred_at 最新）。 */
export function useRiskIndex() {
  return useQuery({
    queryKey: ["registry", "risk-index"],
    queryFn: objectsApi.riskIndexEvents,
    select: (items: EventResponse[]) => {
      const latest = new Map<string, { risk: string; at: string }>();
      for (const e of items) {
        if (!e.risk_level) continue;
        const prev = latest.get(e.object_id);
        if (!prev || e.occurred_at >= prev.at) {
          latest.set(e.object_id, { risk: e.risk_level, at: e.occurred_at });
        }
      }
      const risks = new Map<string, string>();
      for (const [objectId, v] of latest) risks.set(objectId, v.risk);
      return risks;
    },
  });
}

/** 存在 DATA_QUALITY 异常事件的 object_id 集合。 */
export function useDqIndex() {
  return useQuery({
    queryKey: ["registry", "dq-index"],
    queryFn: objectsApi.dqIndexEvents,
    select: (page: { items: EventResponse[] }) =>
      new Set(
        page.items.filter((e) => e.result_type === "DATA_QUALITY").map((e) => e.object_id),
      ),
  });
}

/** 详情抽屉修订历史：抽屉打开且 objectId 就绪时才发请求（无轮询）。 */
export function useObjectHistory(objectId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ["registry", "object-history", objectId],
    queryFn: () => objectsApi.history(objectId!),
    enabled: enabled && objectId != null,
    retry: 1,
  });
}
