import { http, HttpResponse } from "msw";
import { caseRows, findCaseDetail } from "../data/cases";
import { clampLimit, paginate } from "../lib/cursor";
import { errorOf } from "../lib/http";
import { scenarioResponse } from "../lib/scenario";

/** B.5/W4 EDP-028：决策案例列表（status/risk_level 过滤 + 游标分页）与闭环聚合详情。 */
export const caseHandlers = [
  // GET /decisions/cases：created_at DESC（case_id tiebreak）；列表为简投影
  http.get("*/api/v1/decisions/cases", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const q = new URL(request.url).searchParams;
    const status = q.get("status");
    const risk = q.get("risk_level");
    const filtered = [...caseRows]
      .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.case_id.localeCompare(a.case_id))
      .filter((row) => {
        if (status && row.status !== status) return false;
        if (risk && row.risk_level !== risk) return false;
        return true;
      });
    return HttpResponse.json(paginate(filtered, clampLimit(q.get("limit"), 20, 100), q.get("cursor")));
  }),

  // GET /decisions/cases/{case_id}：闭环聚合详情（event/steps/actions/evidence_chain）
  http.get("*/api/v1/decisions/cases/:caseId", ({ params }) => {
    const detail = findCaseDetail(String(params.caseId));
    if (!detail) return errorOf("NOT_FOUND", "资源不存在", 404);
    return HttpResponse.json(detail);
  }),
];
