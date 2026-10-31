import { http, HttpResponse } from "msw";
import { caseRows, findCaseDetail } from "../data/cases";
import { errorOf } from "../lib/http";
import { iso } from "../lib/demo-time";
import { mockUuid } from "../data/ids";
import { scenarioResponse } from "../lib/scenario";

/**
 * B.9 GET /ebms/decisions/pending + B.5 POST /decisions/cases/{id}/records（W4 EDP-404）。
 * 两端点共享「本会话已决策案例」集合：提交记录后 pending 即时移除该案例
 * （后端为 cases.status 翻转 DECIDED 的等价投影）；GUARD 403 分支由测试 override。
 */
let decidedCaseIds = new Set<string>();

export function resetDecisionMocks(): void {
  decidedCaseIds = new Set();
}

/** 会话内标记案例已决策（handler 内部逻辑；测试 override 响应时复用以保持状态一致）。 */
export function markCaseDecided(caseId: string): void {
  decidedCaseIds.add(caseId);
}

const RISK_ORDER: Record<string, number> = { P0: 0, P1: 1, P2: 2, P3: 3 };

function pendingItems() {
  return caseRows
    .filter((row) => row.status === "OPEN" && !decidedCaseIds.has(row.case_id))
    .sort(
      (a, b) =>
        (RISK_ORDER[a.risk_level ?? ""] ?? 9) - (RISK_ORDER[b.risk_level ?? ""] ?? 9) ||
        a.created_at.localeCompare(b.created_at),
    )
    .map((row) => ({
      case_id: row.case_id,
      case_no: row.case_no ?? null,
      question: row.question,
      risk_level: row.risk_level ?? null,
      options: findCaseDetail(row.case_id)?.options ?? [],
      created_at: row.created_at,
    }));
}

export const decisionHandlers = [
  // B.9 GET /ebms/decisions/pending：risk（P0 优先）+ created_at ASC；total_pending 为 OPEN 全量计数
  http.get("*/api/v1/ebms/decisions/pending", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const q = new URL(request.url).searchParams;
    const all = pendingItems();
    return HttpResponse.json({
      items: all.slice(0, clampOf(q.get("limit"))),
      total_pending: all.length,
    });
  }),

  // B.5 POST /decisions/cases/{case_id}/records（Human-Only）：非 OPEN/重复 → 409
  http.post("*/api/v1/decisions/cases/:caseId/records", async ({ params, request }) => {
    const row = caseRows.find((c) => c.case_id === String(params.caseId));
    if (!row) return errorOf("NOT_FOUND", "资源不存在", 404);
    if (row.status !== "OPEN" || decidedCaseIds.has(row.case_id)) {
      return errorOf("CONFLICT", "案例已有决策记录", 409);
    }
    const body = (await request.json()) as { chosen_option?: string; comment?: string | null };
    const options = findCaseDetail(row.case_id)?.options ?? [];
    const keys = options.map((o) => String(o.key));
    if (!body.chosen_option || (keys.length > 0 && !keys.includes(body.chosen_option))) {
      return errorOf("VALIDATION_ERROR", "chosen_option 必须是案例选项之一", 400);
    }
    markCaseDecided(row.case_id);
    return HttpResponse.json(      {
        case_id: row.case_id,
        decision_id: mockUuid(819),
        case_status: "DECIDED",
        decision_time: iso("2026-09-28T08:30:00Z"),
      },
      { status: 201 },
    );
  }),
];

function clampOf(raw: string | null): number {
  const n = Number(raw ?? 20);
  if (!Number.isFinite(n)) return 20;
  return Math.min(Math.max(Math.trunc(n), 1), 100);
}
