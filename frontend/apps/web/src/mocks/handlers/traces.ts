import { http, HttpResponse } from "msw";
import { clampLimit, paginate } from "../lib/cursor";
import { errorOf } from "../lib/http";
import { scenarioResponse } from "../lib/scenario";
import { traceDetails } from "../data/traces";

/** B.10 列表项简投影：剥 tool_calls 与 input_context/output_structured/token_usage 大 JSON。 */
function toListItem(t: (typeof traceDetails)[number]) {
  return {
    trace_id: t.trace_id,
    agent_id: t.agent_id,
    task_id: t.task_id,
    capability_id: t.capability_id,
    status: t.status,
    started_at: t.started_at,
    finished_at: t.finished_at,
  };
}

export const traceHandlers = [
  // GET /traces：agent_id/task_id/capability_id/since 过滤 + 游标分页（started_at DESC, trace_id DESC）
  http.get("*/api/v1/traces", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const q = new URL(request.url).searchParams;
    const agentId = q.get("agent_id");
    const taskId = q.get("task_id");
    const capabilityId = q.get("capability_id");
    const since = q.get("since");
    const sorted = [...traceDetails]
      .sort((a, b) => b.started_at.localeCompare(a.started_at) || b.trace_id.localeCompare(a.trace_id))
      .filter((t) => {
        if (agentId && t.agent_id !== agentId) return false;
        if (taskId && t.task_id !== taskId) return false;
        if (capabilityId && t.capability_id !== capabilityId) return false;
        if (since && t.started_at < since) return false;
        return true;
      })
      .map(toListItem);
    return HttpResponse.json(paginate(sorted, clampLimit(q.get("limit")), q.get("cursor")));
  }),

  // GET /traces/{trace_id}：完整轨迹（tool_calls[] seq 升序）；跨租户/不存在统一 404
  http.get("*/api/v1/traces/:traceId", ({ params }) => {
    const found = traceDetails.find((t) => t.trace_id === String(params.traceId));
    if (!found) return errorOf("NOT_FOUND", "资源不存在", 404);
    return HttpResponse.json({ ...found, tool_calls: [...(found.tool_calls ?? [])].sort((a, b) => a.seq - b.seq) });
  }),
];
