import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { MEMORY_PAGE_LIMIT, memoriesApi, type MemoryStatus } from "./api";

export interface MemoryFilters {
  status?: MemoryStatus;
  capabilityId?: string;
}

/** B.11 候选记忆列表（keepPreviousData 防翻页/筛选闪烁）。 */
export function useMemoriesList(filters: MemoryFilters, cursor: string | null) {
  return useQuery({
    queryKey: ["memories", "list", filters.status ?? "", filters.capabilityId ?? "", cursor],
    queryFn: () =>
      memoriesApi.list({
        status: filters.status,
        capability_id: filters.capabilityId || undefined,
        limit: MEMORY_PAGE_LIMIT,
        cursor,
      }),
    placeholderData: keepPreviousData,
  });
}
