import { http, HttpResponse } from "msw";
import { scenarioResponse } from "../lib/scenario";
import { errorOf } from "../lib/http";
import { clampLimit, paginate } from "../lib/cursor";
import { TENANT_ID } from "../data/ids";
import {
  findTenant,
  findTenantDetail,
  platformUsers,
  tenantMembers,
  tenantQuotaDetailOf,
  tenantRows,
  tenantUsageSummaryOf,
  usageDaily,
  type TenantRow,
} from "../data/tenants";

/** B.14/W5 EDP-501 租户平台面：清单/详情/成员/配额/生命周期/context 切换 + 用量。 */

/** POST /tenants 编码自动生成 mock 序号（模块内递增，模拟按年重置语义）。 */
let mockCodeSeq = 0;

function memberNotFound() {
  return errorOf("NOT_FOUND", "成员不存在", 404);
}

export const tenantHandlers = [
  // W1 冻结契约：GET /api/v1/tenants/current（tenantmgmt TenantInfo：id/slug/name/plan/status）
  http.get("*/api/v1/tenants/current", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    return HttpResponse.json({
      tenant_id: TENANT_ID,
      slug: "default",
      name: "默认租户",
      plan: "STANDARD",
      status: "ACTIVE",
    });
  }),

  // GET /tenants/current/usage（B.14 计量日表；须先于 :tenant_id 动态段注册）
  http.get("*/api/v1/tenants/current/usage", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const q = new URL(request.url).searchParams;
    return HttpResponse.json(paginate(usageDaily, clampLimit(q.get("limit"), 20, 100), q.get("cursor")));
  }),

  // GET /tenants：status/plan 过滤 + created_at DESC 游标分页；items 附 mock 扩展 usage 摘要
  http.get("*/api/v1/tenants", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const q = new URL(request.url).searchParams;
    const status = q.get("status");
    const plan = q.get("plan");
    const filtered = [...tenantRows]
      .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.tenant_id.localeCompare(a.tenant_id))
      .filter((row) => {
        if (status && row.status !== status) return false;
        if (plan && row.plan !== plan) return false;
        return true;
      })
      .map((row) => ({ ...row, usage: tenantUsageSummaryOf(row.slug) }));
    return HttpResponse.json(paginate(filtered, clampLimit(q.get("limit"), 20, 100), q.get("cursor")));
  }),

  // POST /tenants：开通（B.14）；编码服务端自动生成 ten-YYYY-NNNN（模块内
  // 递增序号）；未携带 admin.password 时回传一次性临时口令
  http.post("*/api/v1/tenants", async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as {
      name?: string;
      plan?: string;
      admin?: { username?: string; password?: string | null };
    };
    if (!body.name || !body.plan) {
      return errorOf("VALIDATION_ERROR", "name/plan 均为必填", 400);
    }
    mockCodeSeq += 1;
    const slug = `ten-${new Date().getFullYear()}-${String(mockCodeSeq).padStart(4, "0")}`;
    const generated = body.admin?.password == null || body.admin.password === "";
    return HttpResponse.json(
      {
        tenant_id: `00000000-0000-4000-8000-${String(599).padStart(12, "0")}`,
        slug,
        name: body.name,
        status: "ACTIVE",
        created_at: new Date().toISOString(),
        initial_admin_user_id: `00000000-0000-0000-0000-${(body.admin?.username ?? "admin").padStart(12, "0")}`,
        ...(generated ? { temporary_password: "Tmp-9k2f-Xq7b" } : { temporary_password: null }),
      },
      { status: 201 },
    );
  }),

  // GET /tenants/{tenant_id}：详情（配额/用量可空）
  http.get("*/api/v1/tenants/:tenantId", ({ params }) => {
    const detail = findTenantDetail(String(params.tenantId));
    if (!detail) return errorOf("NOT_FOUND", "租户不存在", 404);
    return HttpResponse.json(detail);
  }),

  // PATCH /tenants/{tenant_id}：name/plan 变更（仅记录，不联动配额）
  http.patch("*/api/v1/tenants/:tenantId", async ({ params, request }) => {
    const tenant = findTenant(String(params.tenantId));
    if (!tenant) return errorOf("NOT_FOUND", "租户不存在", 404);
    const body = (await request.json().catch(() => ({}))) as { name?: string; plan?: string };
    return HttpResponse.json({
      ...findTenantDetail(tenant.tenant_id)!,
      ...(body.name ? { name: body.name } : {}),
      ...(body.plan ? { plan: body.plan } : {}),
    });
  }),

  // POST /tenants/{tenant_id}/suspend|resume：生命周期（202 受理；非法转移 422）
  http.post("*/api/v1/tenants/:tenantId/suspend", ({ params }) => {
    const tenant = findTenant(String(params.tenantId));
    if (!tenant) return errorOf("NOT_FOUND", "租户不存在", 404);
    if (tenant.status !== "ACTIVE") {
      return errorOf("INVALID_TRANSITION", "仅 ACTIVE 租户可暂停", 422);
    }
    return HttpResponse.json(
      { tenant_id: tenant.tenant_id, operation: "suspend", status: "SUSPENDED", occurred_at: new Date().toISOString() },
      { status: 202 },
    );
  }),

  http.post("*/api/v1/tenants/:tenantId/resume", ({ params }) => {
    const tenant = findTenant(String(params.tenantId));
    if (!tenant) return errorOf("NOT_FOUND", "租户不存在", 404);
    if (tenant.status !== "SUSPENDED") {
      return errorOf("INVALID_TRANSITION", "仅 SUSPENDED 租户可恢复", 422);
    }
    return HttpResponse.json(
      { tenant_id: tenant.tenant_id, operation: "resume", status: "ACTIVE", occurred_at: new Date().toISOString() },
      { status: 202 },
    );
  }),

  // POST /tenants/{tenant_id}/cancel：注销强确认（confirm=true 且 reason 非空才受理）
  http.post("*/api/v1/tenants/:tenantId/cancel", async ({ params, request }) => {
    const tenant = findTenant(String(params.tenantId));
    if (!tenant) return errorOf("NOT_FOUND", "租户不存在", 404);
    const body = (await request.json().catch(() => ({}))) as { confirm?: boolean; reason?: string };
    if (body.confirm !== true || !body.reason?.trim()) {
      return errorOf("VALIDATION_ERROR", "需 confirm=true 且 reason 非空", 400);
    }
    return HttpResponse.json(
      { tenant_id: tenant.tenant_id, operation: "cancel", status: "CANCELLED", occurred_at: new Date().toISOString() },
      { status: 202 },
    );
  }),

  // POST /tenants/{tenant_id}/context：切换租户上下文（B.14 扩展：响应体回发 access_token）
  http.post("*/api/v1/tenants/:tenantId/context", ({ params }) => {
    const tenant = findTenant(String(params.tenantId));
    if (!tenant) return errorOf("NOT_FOUND", "租户不存在", 404);
    if (tenant.status !== "ACTIVE") {
      return errorOf("TENANT_SUSPENDED", "目标租户已暂停或状态异常", 403);
    }
    return HttpResponse.json({
      tenant_id: tenant.tenant_id,
      access_token: `mock-access-ctx-${tenant.slug}`,
      note: "token 已按目标租户上下文重签",
      switched_at: new Date().toISOString(),
    });
  }),

  // GET /tenants/{tenant_id}/members：成员清单（joined_at = 加入时间）
  http.get("*/api/v1/tenants/:tenantId/members", ({ params, request }) => {
    const tenant = findTenant(String(params.tenantId));
    if (!tenant) return errorOf("NOT_FOUND", "租户不存在", 404);
    const q = new URL(request.url).searchParams;
    const rows = tenantMembers[tenant.tenant_id] ?? [];
    return HttpResponse.json(paginate(rows, clampLimit(q.get("limit"), 20, 100), q.get("cursor")));
  }),

  // POST /tenants/{tenant_id}/members：邀请（已在册 409；member_roles 空 422）
  http.post("*/api/v1/tenants/:tenantId/members", async ({ params, request }) => {
    const tenant = findTenant(String(params.tenantId));
    if (!tenant) return errorOf("NOT_FOUND", "租户不存在", 404);
    const body = (await request.json().catch(() => ({}))) as { user_id?: string; member_roles?: string[] };
    const roles = body.member_roles ?? [];
    if (!body.user_id) return errorOf("VALIDATION_ERROR", "user_id 必填", 400);
    if (roles.length === 0) {
      return errorOf("VALIDATION_ERROR", "member_roles 不能为空", 422);
    }
    const rows = tenantMembers[tenant.tenant_id] ?? [];
    if (rows.some((m) => m.user_id === body.user_id)) {
      return errorOf("CONFLICT", "该用户已是租户成员", 409);
    }
    const user = platformUsers.find((u) => u.user_id === body.user_id);
    return HttpResponse.json(
      {
        member_id: `00000000-0000-4000-8000-${String(598).padStart(12, "0")}`,
        user_id: body.user_id,
        display_name: user?.display_name ?? null,
        member_roles: roles,
        status: "INVITED",
        joined_at: new Date().toISOString(),
      },
      { status: 201 },
    );
  }),

  // PATCH /tenants/{tenant_id}/members/{member_id}：改角色/禁用（roles 空 422）
  http.patch("*/api/v1/tenants/:tenantId/members/:memberId", async ({ params, request }) => {
    const tenant = findTenant(String(params.tenantId));
    if (!tenant) return errorOf("NOT_FOUND", "租户不存在", 404);
    const member = (tenantMembers[tenant.tenant_id] ?? []).find((m) => m.member_id === params.memberId);
    if (!member) return memberNotFound();
    const body = (await request.json().catch(() => ({}))) as {
      member_roles?: string[] | null;
      status?: string | null;
    };
    if (body.member_roles != null && body.member_roles.length === 0) {
      return errorOf("VALIDATION_ERROR", "member_roles 不能为空", 422);
    }
    return HttpResponse.json({
      ...member,
      ...(body.member_roles != null ? { member_roles: body.member_roles } : {}),
      ...(body.status != null ? { status: body.status } : {}),
    });
  }),

  // GET /tenants/{tenant_id}/quotas：完整配额（七字段 + tenant_id）
  http.get("*/api/v1/tenants/:tenantId/quotas", ({ params }) => {
    const tenant = findTenant(String(params.tenantId));
    if (!tenant) return errorOf("NOT_FOUND", "租户不存在", 404);
    return HttpResponse.json(tenantQuotaDetailOf(tenant));
  }),

  // PATCH /tenants/{tenant_id}/quotas：临时提额（reason 必填非空；仅三字段可调）
  http.patch("*/api/v1/tenants/:tenantId/quotas", async ({ params, request }) => {
    const tenant = findTenant(String(params.tenantId));
    if (!tenant) return errorOf("NOT_FOUND", "租户不存在", 404);
    const body = (await request.json().catch(() => ({}))) as {
      api_rate_limit?: number | null;
      storage_gb?: number | null;
      events_per_month?: number | null;
      reason?: string | null;
    };
    if (!body.reason?.trim()) {
      return errorOf("VALIDATION_ERROR", "调整原因必填", 422);
    }
    const current = tenantQuotaDetailOf(tenant);
    return HttpResponse.json({
      ...current,
      ...(body.api_rate_limit != null ? { api_rate_limit: body.api_rate_limit } : {}),
      ...(body.storage_gb != null ? { storage_gb: body.storage_gb } : {}),
      ...(body.events_per_month != null ? { events_per_month: body.events_per_month } : {}),
      updated_at: new Date().toISOString(),
    });
  }),

  // GET /tenants/{tenant_id}/usage：租户维度计量日表（演示数据复用 default 日表）
  http.get("*/api/v1/tenants/:tenantId/usage", ({ params, request }) => {
    const tenant = findTenant(String(params.tenantId));
    if (!tenant) return errorOf("NOT_FOUND", "租户不存在", 404);
    const q = new URL(request.url).searchParams;
    return HttpResponse.json(paginate(usageDaily, clampLimit(q.get("limit"), 20, 100), q.get("cursor")));
  }),

  // GET /admin/users：平台用户目录（真契约 Page[AdminUserItem] 信封——W6-08 修正旧裸数组；
  // username ASC 口径 mock 以 paginate 简化）
  http.get("*/api/v1/admin/users", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const q = new URL(request.url).searchParams;
    const sorted = [...platformUsers].sort((a, b) => a.username.localeCompare(b.username));
    return HttpResponse.json(paginate(sorted, clampLimit(q.get("limit"), 20, 100), q.get("cursor")));
  }),
];

/** 供页面单测引用的行类型（含 mock 扩展 usage 摘要）。 */
export type TenantListItem = TenantRow & { usage: ReturnType<typeof tenantUsageSummaryOf> };
