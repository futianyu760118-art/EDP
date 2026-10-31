import { useQuery } from "@tanstack/react-query";
import { healthApi } from "./api";

/** 深层健康轮询（10s；系统健康页 EDP-304）。 */
export function useDeepHealth() {
  return useQuery({
    queryKey: ["health", "deep"],
    queryFn: healthApi.deep,
    refetchInterval: 10_000,
  });
}

/** 演练记录归档（T7 /admin/drills；备份卡读数——文件缺失/坏 JSON 后端回空列表）。 */
export function useDrillRecords() {
  return useQuery({
    queryKey: ["health", "drills"],
    queryFn: healthApi.drills,
    retry: 1,
  });
}
