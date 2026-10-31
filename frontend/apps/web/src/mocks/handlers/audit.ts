import { http, HttpResponse } from "msw";
import { clampLimit, paginate } from "../lib/cursor";
import { errorOf } from "../lib/http";
import { iso } from "../lib/demo-time";
import { scenarioResponse } from "../lib/scenario";
import { auditLogs, auditPolicies } from "../data/audit";
import type { PolicyCreateRequest, PolicyItem, PolicyUpdateRequest } from "../types";

/** 策略可变行集（POST/PATCH/DELETE 推进；不动 data fixtures），测试间复位 resetAuditMock()。 */
let policies: PolicyItem[] = auditPolicies.map((p) => ({ ...p }));

export function resetAuditMock(): void {
  policies = auditPolicies.map((p) => ({ ...p }));
}

const sortPolicies = (rows: PolicyItem[]) =>
  [...rows].sort((a, b) => b.created_at.localeCompare(a.created_at) || b.policy_id.localeCompare(a.policy_id));

export const auditHandlers = [
  // B.6 GET /audit-logs：actor_id/resource_type/action/since/until 过滤（对齐导出弹窗字段）+ 分页
  http.get("*/api/v1/audit-logs", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const q = new URL(request.url).searchParams;
    const filtered = [...auditLogs]
      .sort((a, b) => b.occurred_at.localeCompare(a.occurred_at) || b.audit_id - a.audit_id)
      .filter((a) => {
        if (q.get("actor_id") && a.actor_id !== q.get("actor_id")) return false;
        if (q.get("resource_type") && a.resource_type !== q.get("resource_type")) return false;
        if (q.get("action") && a.action !== q.get("action")) return false;
        if (q.get("since") && a.occurred_at < q.get("since")!) return false;
        if (q.get("until") && a.occurred_at > q.get("until")!) return false;
        return true;
      });
    return HttpResponse.json(paginate(filtered, clampLimit(q.get("limit")), q.get("cursor")));
  }),

  // B.6 GET /audit-logs/{audit_id}
  http.get("*/api/v1/audit-logs/:auditId", ({ params }) => {
    const id = Number(params.auditId);
    const found = auditLogs.find((a) => a.audit_id === id);
    if (!found) return errorOf("NOT_FOUND", "审计条目不存在", 404);
    return HttpResponse.json(found);
  }),

  // EDP-032 GET /admin/audit-policies：status 过滤 + 游标分页（created_at DESC）
  http.get("*/api/v1/admin/audit-policies", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const q = new URL(request.url).searchParams;
    const status = q.get("status");
    const filtered = sortPolicies(policies).filter((p) => !status || p.status === status);
    return HttpResponse.json(paginate(filtered, clampLimit(q.get("limit"), 20, 100), q.get("cursor")));
  }),

  // EDP-032 POST /admin/audit-policies：重名 409；201 完整对象（status=ACTIVE）
  http.post("*/api/v1/admin/audit-policies", async ({ request }) => {
    const body = (await request.json()) as Partial<PolicyCreateRequest>;
    const name = (body.name ?? "").trim();
    if (!name) return errorOf("VALIDATION_ERROR", "策略名称必填", 422);
    if (policies.some((p) => p.name === name)) {
      return errorOf("CONFLICT", "策略名称已存在", 409);
    }
    const now = iso("2026-09-28T08:30:00Z");
    const item: PolicyItem = {
      policy_id: `00000000-0000-4000-8000-${String(950 + policies.length).padStart(12, "0")}`,
      name,
      description: body.description?.trim() ? body.description.trim() : null,
      resource_types: body.resource_types ?? [],
      actions: body.actions ?? [],
      actor_types: body.actor_types ?? [],
      notify_channel: body.notify_channel ?? null,
      status: "ACTIVE",
      created_at: now,
      updated_at: now,
      created_by: "user:manager1",
      updated_by: "user:manager1",
    };
    policies.unshift(item);
    return HttpResponse.json(item, { status: 201 });
  }),

  // EDP-032 PATCH /admin/audit-policies/{id}：局部更新（name 不可改）→ 200 完整对象
  http.patch("*/api/v1/admin/audit-policies/:policyId", async ({ params, request }) => {
    const found = policies.find((p) => p.policy_id === String(params.policyId));
    if (!found) return errorOf("NOT_FOUND", "审计策略不存在", 404);
    const body = (await request.json()) as Partial<PolicyUpdateRequest>;
    if (body.description !== undefined) found.description = body.description;
    if (body.resource_types !== undefined && body.resource_types !== null) found.resource_types = body.resource_types;
    if (body.actions !== undefined && body.actions !== null) found.actions = body.actions;
    if (body.actor_types !== undefined && body.actor_types !== null) found.actor_types = body.actor_types;
    if (body.notify_channel !== undefined) found.notify_channel = body.notify_channel;
    if (body.status !== undefined && body.status !== null) found.status = body.status;
    found.updated_at = iso("2026-09-28T08:31:00Z");
    return HttpResponse.json(found);
  }),

  // EDP-032 DELETE /admin/audit-policies/{id} → 204
  http.delete("*/api/v1/admin/audit-policies/:policyId", ({ params }) => {
    const idx = policies.findIndex((p) => p.policy_id === String(params.policyId));
    if (idx < 0) return errorOf("NOT_FOUND", "审计策略不存在", 404);
    policies.splice(idx, 1);
    return new HttpResponse(null, { status: 204 });
  }),
];
