import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adaptersApi, type SystemCreateRequest, type SystemUpdateRequest } from "./api";

/** 适配器清单（7 列表格 + 测试连接下拉共用）。 */
export function useAdapters() {
  return useQuery({ queryKey: ["adapters", "list"], queryFn: adaptersApi.list });
}

/** 最近一次同步状态（1s 轮询；RUNNING 推进，终态停止——测试连接/日志抽屉共用）。 */
export function useAdapterStatus(name: string | undefined) {
  return useQuery({
    queryKey: ["adapters", "status", name],
    queryFn: () => adaptersApi.status(name!),
    enabled: name != null && name !== "",
    refetchInterval: (query) =>
      query.state.data?.last_sync?.status === "RUNNING" ? 1_000 : false,
  });
}

/** 任务历史（T5 jobs 端点；最新一条 RUNNING 时 1s 轮询推进）。 */
export function useAdapterJobs(name: string | undefined) {
  return useQuery({
    queryKey: ["adapters", "jobs", name],
    queryFn: () => adaptersApi.jobs(name!),
    enabled: name != null && name !== "",
    refetchInterval: (query) =>
      query.state.data?.items[0]?.status === "RUNNING" ? 1_000 : false,
  });
}

/** 触发增量同步（测试连接）：202 → 由调用方开启 status 轮询。 */
export function useSyncAdapter() {
  return useMutation({
    mutationFn: (name: string) => adaptersApi.sync(name, "incremental"),
  });
}

/** 注册适配器（POST /systems）：201 后清单失效重拉。 */
export function useCreateSystem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SystemCreateRequest) => adaptersApi.createSystem(body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["adapters", "list"] });
    },
  });
}

/** T50 系统详情（编辑弹窗预填；systemId 为空禁用）。 */
export function useSystem(systemId: string | undefined) {
  return useQuery({
    queryKey: ["systems", "detail", systemId],
    queryFn: () => adaptersApi.getSystem(systemId!),
    enabled: systemId != null && systemId !== "",
  });
}

/** T50 更新系统（PUT /systems/{id}）：成功刷新详情与清单。 */
export function useUpdateSystem(systemId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SystemUpdateRequest) => adaptersApi.updateSystem(systemId!, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["adapters", "list"] });
      void queryClient.invalidateQueries({ queryKey: ["systems", "detail", systemId] });
    },
  });
}

/** T50 删除系统（DELETE /systems/{id}）：成功刷新清单。 */
export function useDeleteSystem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (systemId: string) => adaptersApi.deleteSystem(systemId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["adapters", "list"] });
    },
  });
}
