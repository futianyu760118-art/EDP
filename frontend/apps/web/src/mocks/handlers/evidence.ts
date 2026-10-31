import { http, HttpResponse } from "msw";
import { clampLimit, paginate } from "../lib/cursor";
import { errorOf } from "../lib/http";
import { scenarioResponse } from "../lib/scenario";
import { evidence } from "../data/evidence";
import { mockUuid } from "../data/ids";
import { iso } from "../lib/demo-time";
import { registerMockTask } from "./quality";

function sortedAll() {
  return [...evidence].sort((a, b) => b.captured_at.localeCompare(a.captured_at));
}

export const evidenceHandlers = [
  // B.4 GET /evidence：object_id / ref_type+ref_id（links 命中，逆向追溯链图）/
  // q（source_record_id/source_system 模糊匹配，W3R 契约扩展）过滤
  http.get("*/api/v1/evidence", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const q = new URL(request.url).searchParams;
    const refType = q.get("ref_type");
    const refId = q.get("ref_id");
    const objectId = q.get("object_id");
    const query = q.get("q")?.trim().toLowerCase();
    const filtered = sortedAll().filter((e) => {
      if (objectId && e.object_id !== objectId) return false;
      if (refType && refId && !(e.links ?? []).some((l) => l.ref_type === refType && l.ref_id === refId)) return false;
      if (
        query &&
        !e.source_record_id.toLowerCase().includes(query) &&
        !e.source_system.toLowerCase().includes(query)
      ) {
        return false;
      }
      return true;
    });
    return HttpResponse.json(paginate(filtered, clampLimit(q.get("limit")), q.get("cursor")));
  }),

  // B.4 GET /evidence/{id}
  http.get("*/api/v1/evidence/:evidenceId", ({ params }) => {
    const found = evidence.find((e) => e.evidence_id === String(params.evidenceId));
    if (!found) return errorOf("NOT_FOUND", "资源不存在", 404);
    return HttpResponse.json(found);
  }),

  // B.4 GET /evidence/{id}/verify：mock 恒 valid=true（篡改检测由后端 EDP-008 实现）
  http.get("*/api/v1/evidence/:evidenceId/verify", ({ params }) => {
    const found = evidence.find((e) => e.evidence_id === String(params.evidenceId));
    if (!found) return errorOf("NOT_FOUND", "资源不存在", 404);
    return HttpResponse.json({ evidence_id: found.evidence_id, valid: true, verified_at: iso("2026-09-28T08:30:00Z") });
  }),

  // T6 POST /admin/evidence/reindex：scope=ALL → 202 {task_id, status}；
  // 任务轮询走 GET /admin/quality/tasks/{id}（首次 RUNNING，二次起 SUCCEEDED + stats）
  http.post("*/api/v1/admin/evidence/reindex", async ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const body = (await request.json().catch(() => ({}))) as { scope?: string };
    if (body.scope != null && body.scope !== "ALL") {
      return errorOf("VALIDATION_ERROR", "scope 当前仅支持 ALL", 400);
    }
    const task = registerMockTask(
      {
        task_id: mockUuid(950),
        task_type: "evidence_reindex",
        status: "RUNNING",
        scope: "ALL",
        started_at: iso("2026-09-28T08:30:00Z"),
        logs: [{ ts: iso("2026-09-28T08:30:00Z"), level: "INFO", message: `全量重算开始：共 ${evidence.length} 条证据` }],
      },
      { terminalAfter: 1, terminalStats: { total: evidence.length, rechecked: evidence.length, mismatched: 0 } },
    );
    return HttpResponse.json({ task_id: task.task_id, status: task.status }, { status: 202 });
  }),
];
