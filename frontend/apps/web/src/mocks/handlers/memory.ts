import { http, HttpResponse } from "msw";
import { clampLimit, paginate } from "../lib/cursor";
import { scenarioResponse } from "../lib/scenario";
import { memoryItems } from "../data/memory";

/**
 * B.11 记忆候选（W5 只读）：GET /memories status/capability_id 过滤 + 游标分页
 * （created_at DESC, memory_id tiebreak）。评审 PATCH 由 W6 Agent 中枢接管，本轮不设。
 */
export const memoryHandlers = [
  http.get("*/api/v1/memories", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const q = new URL(request.url).searchParams;
    const status = q.get("status");
    const capabilityId = q.get("capability_id");
    const sorted = [...memoryItems]
      .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.memory_id.localeCompare(a.memory_id))
      .filter((m) => {
        if (status && m.status !== status) return false;
        if (capabilityId && m.capability_id !== capabilityId) return false;
        return true;
      });
    return HttpResponse.json(paginate(sorted, clampLimit(q.get("limit")), q.get("cursor")));
  }),
];
