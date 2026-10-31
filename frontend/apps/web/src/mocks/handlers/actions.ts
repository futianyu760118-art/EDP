import { http, HttpResponse } from "msw";
import { ACTION_TRANSITIONS, actionRows, allowedToOf, type ActionRow } from "../data/actions";
import { clampLimit, paginate } from "../lib/cursor";
import { errorOf } from "../lib/http";
import { iso } from "../lib/demo-time";
import { scenarioResponse } from "../lib/scenario";

/**
 * B.5/W4 EDP-020 行动三端点（列表三过滤 + 详情 + PATCH 状态机）。
 * PATCH 会推进 handler 内可变行集（浅拷贝，不动 data fixtures）；
 * 测试间复位用 resetActionsMock()（server.resetHandlers 不还原数据状态）。
 */
let rows: ActionRow[] = actionRows.map((row) => ({
  ...row,
  allowed_to: (row.allowed_to ?? []).map((t) => ({ ...t })),
}));

export function resetActionsMock(): void {
  rows = actionRows.map((row) => ({
    ...row,
    allowed_to: (row.allowed_to ?? []).map((t) => ({ ...t })),
  }));
}

export const actionHandlers = [
  // GET /actions：status/owner/case_id 过滤 + 游标分页（created_at DESC, action_id DESC）
  http.get("*/api/v1/actions", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const q = new URL(request.url).searchParams;
    const status = q.get("status");
    const owner = q.get("owner");
    const caseId = q.get("case_id");
    const filtered = [...rows]
      .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.action_id.localeCompare(a.action_id))
      .filter((row) => {
        if (status && row.status !== status) return false;
        if (owner && row.owner !== owner) return false;
        if (caseId && row.case_id !== caseId) return false;
        return true;
      })
      // 简投影（B.5）：allowed_to 随行携带
      .map(({ action_id, title, status: rowStatus, owner: rowOwner, due_date, allowed_to }) => ({
        action_id,
        title,
        status: rowStatus,
        owner: rowOwner,
        due_date,
        allowed_to: allowed_to ?? [],
      }));
    return HttpResponse.json(paginate(filtered, clampLimit(q.get("limit"), 20, 100), q.get("cursor")));
  }),

  // GET /actions/{action_id}：完整对象 + allowed_to
  http.get("*/api/v1/actions/:actionId", ({ params }) => {
    const found = rows.find((row) => row.action_id === String(params.actionId));
    if (!found) return errorOf("NOT_FOUND", "资源不存在", 404);
    return HttpResponse.json(found);
  }),

  // PATCH /actions/{action_id}/status：from 过期 409 / 非法 422（error.allowed_to）/ 成功 200
  //（Human-Only 边非 HUMAN 403 分支与 comment 落证据由后端实现，测试按需 override）
  http.patch("*/api/v1/actions/:actionId/status", async ({ params, request }) => {
    const found = rows.find((row) => row.action_id === String(params.actionId));
    if (!found) return errorOf("NOT_FOUND", "资源不存在", 404);
    const body = (await request.json()) as { from_status: string; to_status: string; comment?: string | null };
    if (found.status !== body.from_status) {
      return errorOf("CONFLICT", "数据已被他人修改，已刷新", 409);
    }
    const table = ACTION_TRANSITIONS[found.status] ?? {};
    if (!(body.to_status in table)) {
      return errorOf("INVALID_TRANSITION", "非法状态转移", 422, { allowed_to: allowedToOf(found.status) });
    }
    found.status = body.to_status;
    found.updated_at = iso("2026-09-28T08:30:00Z");
    if (body.to_status === "COMPLETED") found.completion_time = found.updated_at;
    if (body.to_status === "VERIFIED") {
      found.verified_at = found.updated_at;
      found.verified_by = "user:manager_wang";
    }
    found.allowed_to = allowedToOf(found.status);
    return HttpResponse.json({ action_id: found.action_id, status: found.status, updated_at: found.updated_at });
  }),
];
