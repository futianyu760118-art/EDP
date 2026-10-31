import { useQuery } from "@tanstack/react-query";
import { drillsApi } from "./api";

/** 演练记录清单（只读归档，executed_at null = PLANNED 未执行；文件缺失后端回空列表 → 空态）。 */
export function useDrills() {
  return useQuery({
    queryKey: ["drills", "list"],
    queryFn: () => drillsApi.list(),
  });
}
