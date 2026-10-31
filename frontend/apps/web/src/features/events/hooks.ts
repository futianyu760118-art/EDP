import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { message } from "antd";
import { EVENTS_PAGE_LIMIT, eventsApi } from "./api";

export interface EventFilters {
  /** 类型下拉 → 后端 event_type 参数。 */
  eventType?: string;
  /** 时间范围 → since/until（ISO，闭区间）。 */
  since?: string;
  until?: string;
}

/**
 * 事件流分页列表（13.6.2）：keepPreviousData 让翻页/切筛选时保留旧页数据，
 * 避免列表闪烁；queryKey 含全部过滤条件与游标。
 */
export function useEvents(filters: EventFilters, cursor: string | null) {
  return useQuery({
    queryKey: [
      "events",
      "list",
      filters.eventType ?? "",
      filters.since ?? "",
      filters.until ?? "",
      cursor,
    ],
    queryFn: () =>
      eventsApi.list({
        event_type: filters.eventType || undefined,
        since: filters.since,
        until: filters.until,
        limit: EVENTS_PAGE_LIMIT,
        cursor,
      }),
    placeholderData: keepPreviousData,
  });
}

/** KPI 带数据源：30s 轮询 health，select 只取 ops_metrics（其余字段总览页消费）。 */
export function useEventHealth() {
  return useQuery({
    queryKey: ["events", "health"],
    queryFn: eventsApi.health,
    refetchInterval: 30_000,
    retry: 1,
    select: (health) => health.ops_metrics,
  });
}

/** 回放向导目标适配器下拉（T17 消费）：适配器名 → Select option。
 * W3-37：enabled 门控——向导未打开不发清单请求（open 时才拉取）。 */
export function useAdapterOptions(enabled = true) {
  return useQuery({
    queryKey: ["events", "adapters"],
    queryFn: eventsApi.adapters,
    enabled,
    retry: 1,
    select: (page) => page.items.map((a) => ({ value: a.adapter, label: a.adapter })),
  });
}

/** 回放提交（T17 向导消费）：202 后成功 toast + 刷新事件列表。 */
export function useReplayEvent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { adapter: string; since?: string }) =>
      eventsApi.replay(input.adapter, { mode: "replay", since: input.since }),
    onSuccess: () => {
      message.success("回放任务已提交");
      void queryClient.invalidateQueries({ queryKey: ["events", "list"] });
    },
  });
}
