import { http, HttpResponse } from "msw";
import { clampLimit, paginate } from "../lib/cursor";
import { scenarioResponse } from "../lib/scenario";
import { capabilityRows } from "../data/catalog";

/**
 * W3R 能力注册（B.7，T9 前端 capability 数据源）：GET /capabilities
 * domain/status 过滤 + 游标分页；traces/memory 筛选共用（W5-13 收敛）。
 */
export const catalogHandlers = [
  http.get("*/api/v1/capabilities", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const q = new URL(request.url).searchParams;
    const domain = q.get("domain");
    const status = q.get("status");
    const filtered = [...capabilityRows]
      .sort((a, b) => a.created_at.localeCompare(b.created_at))
      .filter((row) => {
        if (domain && row.domain !== domain) return false;
        if (status && row.status !== status) return false;
        return true;
      });
    return HttpResponse.json(paginate(filtered, clampLimit(q.get("limit")), q.get("cursor")));
  }),
];
