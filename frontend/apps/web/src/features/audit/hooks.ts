import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  auditApi,
  type AuditLogFilters,
  type PolicyCreateRequest,
  type PolicyUpdateRequest,
} from "./api";

/** 审计日志分页列表（keepPreviousData 防翻页/筛选闪烁）。 */
export function useAuditLogs(filters: AuditLogFilters, cursor: string | null) {
  return useQuery({
    queryKey: [
      "audit",
      "logs",
      filters.actor_id ?? "",
      filters.resource_type ?? "",
      filters.action ?? "",
      filters.since ?? "",
      filters.until ?? "",
      cursor,
    ],
    queryFn: () => auditApi.list(filters, cursor),
    placeholderData: keepPreviousData,
  });
}

/** 策略列表（status 过滤；策略量小取单页 100，不做翻页 UI）。 */
export function useAuditPolicies(status?: string) {
  return useQuery({
    queryKey: ["audit", "policies", status ?? ""],
    queryFn: () => auditApi.listPolicies(status),
  });
}

/** 策略写操作后统一失效（列表 + 无关日志缓存不动）。 */
function useInvalidatePolicies() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: ["audit", "policies"] });
}

/** 新建策略（201）：toast 由页面层处理。 */
export function useCreatePolicy() {
  const invalidate = useInvalidatePolicies();
  return useMutation({
    mutationFn: (body: PolicyCreateRequest) => auditApi.createPolicy(body),
    onSuccess: invalidate,
  });
}

/** 局部更新 / 启停（PATCH status）。 */
export function useUpdatePolicy() {
  const invalidate = useInvalidatePolicies();
  return useMutation({
    mutationFn: ({ policyId, body }: { policyId: string; body: PolicyUpdateRequest }) =>
      auditApi.updatePolicy(policyId, body),
    onSuccess: invalidate,
  });
}

/** 删除策略（204）。 */
export function useDeletePolicy() {
  const invalidate = useInvalidatePolicies();
  return useMutation({
    mutationFn: (policyId: string) => auditApi.deletePolicy(policyId),
    onSuccess: invalidate,
  });
}
