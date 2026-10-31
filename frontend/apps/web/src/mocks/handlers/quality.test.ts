import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { setupServer } from "msw/node";
import { handlers } from "../handlers";

const server = setupServer(...handlers);
const BASE = "http://mock.test";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("quality handlers", () => {
  it("reports：coverage 96.8、对账 5 行（含 real 无水位降级行）、维度 4 段、KPI 待处理 7", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/admin/quality/reports`)).json()) as {
      coverage: { overall_pct: number };
      reconciliation: { source_count: number | null }[];
      dimensions: { domain: string }[];
      kpi: { pending_exceptions: number; high_priority: number; sla_pct: number };
    };
    expect(body.coverage.overall_pct).toBe(96.8);
    expect(body.reconciliation).toHaveLength(5);
    expect(body.reconciliation.some((row) => row.source_count === null)).toBe(true);
    // 四段标识（T3 derive_dimensions 值域）
    expect(body.dimensions.map((d) => d.domain)).toEqual([
      "reconciliation",
      "coverage",
      "orphans",
      "checksum",
    ]);
    expect(body.kpi.pending_exceptions).toBe(7);
    expect(body.kpi.high_priority).toBe(4);
    // sla = 抽检通过率 100*(120-1)/120
    expect(body.kpi.sla_pct).toBe(99.2);
  });

  it("coverage 简报结构", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/admin/quality/coverage`)).json()) as { overall_pct: number; by_type: unknown[] };
    expect(body.overall_pct).toBe(96.8);
    expect(body.by_type.length).toBeGreaterThanOrEqual(6);
  });

  it("重校验 POST {scope} → 202 {task_id,status}；任务详情 RUNNING 含任务启动/WARN 行", async () => {
    const resp = await fetch(`${BASE}/api/v1/admin/quality/rechecks`, {
      method: "POST",
      body: JSON.stringify({ scope: "ALL" }),
    });
    expect(resp.status).toBe(202);
    const accepted = (await resp.json()) as { task_id: string; status: string };
    expect(accepted.task_id).toMatch(/^TASK-20260928-\d{4}$/);
    expect(accepted.status).toBe("RUNNING");

    const detail = (await (await fetch(`${BASE}/api/v1/admin/quality/tasks/${accepted.task_id}`)).json()) as {
      status: string;
      scope: string | null;
      logs: { level: string; message: string }[];
    };
    expect(detail.status).toBe("RUNNING");
    expect(detail.scope).toBe("ALL");
    expect(detail.logs[0].message).toContain("任务启动：scope=ALL");
    expect(detail.logs.some((l) => l.level === "WARN")).toBe(true);
  });

  it("非法 scope → 400", async () => {
    const resp = await fetch(`${BASE}/api/v1/admin/quality/rechecks`, {
      method: "POST",
      body: JSON.stringify({ scope: "EXCEPTIONS" }),
    });
    expect(resp.status).toBe(400);
  });

  it("任务 404", async () => {
    const resp = await fetch(`${BASE}/api/v1/admin/quality/tasks/TASK-20260928-9999`);
    expect(resp.status).toBe(404);
  });
});
