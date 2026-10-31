import { http, HttpResponse } from "msw";
import { errorOf } from "../lib/http";
import { scenarioResponse } from "../lib/scenario";
import { coverageReport, qualityReport } from "../data/quality";
import type { QualityTask } from "../types";
import { minutesBefore } from "../lib/demo-time";

/** 任务存储（会话内；quality recheck + evidence reindex 轮询共用端点）。 */
interface TaskRow extends QualityTask {
  polls: number;
  terminalAfter: number;
  terminalStats?: Record<string, unknown>;
}
const tasks = new Map<string, TaskRow>();

/** 后台任务段日志（对齐 backend _SCOPE_SEGMENTS/_SEGMENT_LABELS 派生文案）。 */
const SCOPE_SEGMENTS: Record<string, string[]> = {
  RECONCILE: ["对账"],
  ORPHAN: ["孤儿"],
  CHECKSUM: ["抽检"],
  ALL: ["对账", "覆盖率", "孤儿", "抽检"],
};

function segmentLogs(scope: string): QualityTask["logs"] {
  const segments = SCOPE_SEGMENTS[scope] ?? SCOPE_SEGMENTS.ALL;
  const done: Record<string, string> = {
    对账: "组数 5，超差组 0",
    覆盖率: "overall 96.8%",
    孤儿: "事件悬挂 0，证据悬挂 0",
    抽检: "抽样 120，失配 1",
  };
  return [
    { ts: minutesBefore(2), level: "INFO", message: `任务启动：scope=${scope}` },
    ...segments.flatMap((label, index) => [
      { ts: minutesBefore(1.9 - index * 0.4), level: "INFO" as const, message: `${label}段开始` },
      {
        ts: minutesBefore(1.7 - index * 0.4),
        level: label === "对账" ? ("WARN" as const) : ("INFO" as const),
        message: `${label}段完成：${done[label] ?? ""}`,
      },
    ]),
  ];
}

/**
 * 登记任务（reindex handler 复用）。options.terminalAfter = 第 N 次查询后进入
 * 终态（recheck 缺省恒 RUNNING——真模式终态由后端落库；reindex 两态推进供
 * 向导轮询演示）；terminalStats 为进入终态时并入任务行的 stats。
 */
export function registerMockTask(
  task: Omit<QualityTask, "started_at" | "logs"> & { started_at?: string; logs?: QualityTask["logs"] },
  options: { terminalAfter?: number; terminalStats?: Record<string, unknown> } = {},
): QualityTask {
  const row: TaskRow = {
    task_id: task.task_id,
    task_type: task.task_type,
    status: task.status,
    scope: task.scope ?? null,
    ref_name: task.ref_name ?? null,
    started_at: task.started_at ?? minutesBefore(2),
    finished_at: task.finished_at ?? null,
    stats: task.stats ?? undefined,
    logs: task.logs ?? segmentLogs(task.scope ?? "ALL"),
    polls: 0,
    terminalAfter: options.terminalAfter ?? Number.POSITIVE_INFINITY,
    terminalStats: options.terminalStats,
  };
  tasks.set(row.task_id, row);
  return row;
}

/** 测试间复位（可变状态仅存在于 handler 模块内）。 */
export function resetQualityMock(): void {
  tasks.clear();
}

export const qualityHandlers = [
  // B.13 GET /admin/quality/reports（?date= 缺省用报告日期）
  http.get("*/api/v1/admin/quality/reports", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const date = new URL(request.url).searchParams.get("date");
    return HttpResponse.json(date ? { ...qualityReport, date } : qualityReport);
  }),

  // B.13 GET /admin/quality/coverage（Go/No-Go 周报简报）
  http.get("*/api/v1/admin/quality/coverage", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    return HttpResponse.json(coverageReport);
  }),

  // T4 POST /admin/quality/rechecks：scope ∈ RECONCILE|ORPHAN|CHECKSUM|ALL → 202 {task_id, status}
  http.post("*/api/v1/admin/quality/rechecks", async ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const body = (await request.json().catch(() => ({}))) as { scope?: string };
    const scope = body.scope ?? "ALL";
    if (SCOPE_SEGMENTS[scope] == null) {
      return errorOf("VALIDATION_ERROR", "scope 必须为 RECONCILE|ORPHAN|CHECKSUM|ALL", 400);
    }
    const task = registerMockTask({
      task_id: `TASK-20260928-${String(tasks.size + 1).padStart(4, "0")}`,
      task_type: "quality_recheck",
      status: "RUNNING",
      scope,
    });
    return HttpResponse.json({ task_id: task.task_id, status: task.status }, { status: 202 });
  }),

  // T4 GET /admin/quality/tasks/{task_id}：轮询（terminalAfter 次查询后进终态）
  http.get("*/api/v1/admin/quality/tasks/:taskId", ({ params }) => {
    const row = tasks.get(String(params.taskId));
    if (!row) return errorOf("NOT_FOUND", "任务不存在", 404);
    row.polls += 1;
    if (row.status === "RUNNING" && row.polls > row.terminalAfter) {
      row.status = "SUCCEEDED";
      row.finished_at = new Date().toISOString();
      if (row.terminalStats != null) row.stats = row.terminalStats;
    }
    return HttpResponse.json({
      task_id: row.task_id,
      task_type: row.task_type,
      status: row.status,
      scope: row.scope,
      ref_name: row.ref_name,
      started_at: row.started_at,
      finished_at: row.finished_at,
      stats: row.stats,
      logs: row.logs,
    });
  }),
];
