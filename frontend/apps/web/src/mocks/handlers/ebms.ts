import { http, HttpResponse } from "msw";
import { clampLimit, paginate } from "../lib/cursor";
import { scenarioResponse } from "../lib/scenario";
import { exceptions } from "../data/ebms";
import { EVT_ORDER_I_DQ } from "../data/ids";

/** B.9 mock 约定（data/ebms.ts 注释）：EVT_ORDER_I_DQ = RESOLVED，其余 OPEN。 */
const RESOLVED_EVENT = EVT_ORDER_I_DQ;

function isOpen(item: { event_id: string }): boolean {
  return item.event_id !== RESOLVED_EVENT;
}

export const ebmsHandlers = [
  // B.9 GET /ebms/exceptions：severity/status 过滤 + 分页（occurred_at DESC）
  http.get("*/api/v1/ebms/exceptions", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const q = new URL(request.url).searchParams;
    const status = q.get("status") ?? "OPEN";
    const filtered = [...exceptions]
      .sort((a, b) => b.occurred_at.localeCompare(a.occurred_at))
      .filter((e) => {
        if (q.get("severity") && e.risk_level !== q.get("severity")) return false;
        if (status === "OPEN" && !isOpen(e)) return false;
        if (status === "RESOLVED" && isOpen(e)) return false;
        return true;
      });
    return HttpResponse.json(paginate(filtered, clampLimit(q.get("limit"), 20, 100), q.get("cursor")));
  }),
];
