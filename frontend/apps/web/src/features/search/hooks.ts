import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { searchApi } from "./api";

/** 全局搜索（/search?q=）：q 进 queryKey，URL 参数变化即重新查询；q 为空不发包。 */
export function useGlobalSearch(q: string) {
  return useQuery({
    queryKey: ["search", "global", q],
    queryFn: () => searchApi.global(q),
    enabled: q.length > 0,
    placeholderData: keepPreviousData,
  });
}
