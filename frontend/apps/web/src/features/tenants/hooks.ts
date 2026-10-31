import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import {
  TENANTS_PAGE_LIMIT,
  tenantsApi,
  type TenantCancelRequest,
  type TenantCreateRequest,
  type TenantMemberCreateRequest,
  type TenantMemberUpdateRequest,
  type TenantQuotaUpdateRequest,
  type TenantsFilters,
} from "./api";

/** 租户分页列表（keepPreviousData 防翻页/筛选闪烁）。 */
export function useTenantsList(filters: TenantsFilters, cursor: string | null) {
  return useQuery({
    queryKey: ["tenants", "list", filters.status ?? "", filters.plan ?? "", cursor],
    queryFn: () => tenantsApi.list(filters, cursor),
    placeholderData: keepPreviousData,
  });
}

/** 租户详情。 */
export function useTenantDetail(tenantId: string | undefined) {
  return useQuery({
    queryKey: ["tenants", "detail", tenantId],
    queryFn: () => tenantsApi.detail(tenantId!),
    enabled: tenantId != null,
    retry: 1,
  });
}

/** 租户完整配额（七字段 + tenant_id）。 */
export function useTenantQuotas(tenantId: string | undefined) {
  return useQuery({
    queryKey: ["tenants", "quotas", tenantId],
    queryFn: () => tenantsApi.quotas(tenantId!),
    enabled: tenantId != null,
  });
}

/** 租户成员清单。 */
export function useTenantMembers(tenantId: string | undefined) {
  return useQuery({
    queryKey: ["tenants", "members", tenantId],
    queryFn: () => tenantsApi.members(tenantId!),
    enabled: tenantId != null,
  });
}

/** 平台用户目录（邀请成员下拉，GET /admin/users 真端点——W5-11 收口；
 *  已知断点 W6-07：目录范围为平台管理员主租户用户，跨租户通道待契约裁定）。
 *  降级：真模式 404/失败 → Modal 切手输 user_id。 */
export function usePlatformUsers() {
  return useQuery({
    queryKey: ["tenants", "platform-users"],
    queryFn: () => tenantsApi.platformUsers(),
    retry: 0,
    select: (page) => page.items,
  });
}

/** 切换弹窗目标清单：仅 ACTIVE（一次取全，量级 ≤100）。 */
export function useTenantSwitchOptions() {
  return useQuery({
    queryKey: ["tenants", "switch-options"],
    queryFn: () => tenantsApi.list({ status: "ACTIVE" }, null, 100),
    retry: 0,
  });
}

export function useCreateTenant() {
  return useMutation({ mutationFn: (body: TenantCreateRequest) => tenantsApi.create(body) });
}

export function useCancelTenant() {
  return useMutation({
    mutationFn: (vars: { tenantId: string; body: TenantCancelRequest }) =>
      tenantsApi.cancel(vars.tenantId, vars.body),
  });
}

export function useSuspendTenant() {
  return useMutation({ mutationFn: (tenantId: string) => tenantsApi.suspend(tenantId) });
}

export function useResumeTenant() {
  return useMutation({ mutationFn: (tenantId: string) => tenantsApi.resume(tenantId) });
}

export function useSwitchTenantContext() {
  return useMutation({ mutationFn: (tenantId: string) => tenantsApi.switchContext(tenantId) });
}

export function useInviteMember(tenantId: string) {
  return useMutation({
    mutationFn: (body: TenantMemberCreateRequest) => tenantsApi.inviteMember(tenantId, body),
  });
}

export function useUpdateMember(tenantId: string) {
  return useMutation({
    mutationFn: (vars: { memberId: string; body: TenantMemberUpdateRequest }) =>
      tenantsApi.updateMember(tenantId, vars.memberId, vars.body),
  });
}

export function useUpdateQuotas(tenantId: string) {
  return useMutation({
    mutationFn: (body: TenantQuotaUpdateRequest) => tenantsApi.updateQuotas(tenantId, body),
  });
}

export { TENANTS_PAGE_LIMIT };
