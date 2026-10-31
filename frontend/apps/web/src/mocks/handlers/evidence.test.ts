import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { setupServer } from "msw/node";
import { handlers } from "../handlers";
import { CASE_ORDER_B, EVID_ORDER_B_SNAPSHOT } from "../data/ids";

const server = setupServer(...handlers);
const BASE = "http://mock.test";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("evidence handlers", () => {
  it("总量 20（KPI 证据数量数据源）", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/evidence?limit=1`)).json()) as { total: number };
    expect(body.total).toBe(20);
  });

  it("ref_type=CASE&ref_id=订单B案例 → 4 份链上证据（订单/库存/PO/交期）", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/evidence?ref_type=CASE&ref_id=${CASE_ORDER_B}`)).json()) as { total: number };
    expect(body.total).toBe(4);
  });

  it("verify → valid=true", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/evidence/${EVID_ORDER_B_SNAPSHOT}/verify`)).json()) as { valid: boolean };
    expect(body.valid).toBe(true);
  });

  it("reindex POST {scope:ALL} → 202；任务轮询 RUNNING → SUCCEEDED（stats total/mismatched）", async () => {
    const resp = await fetch(`${BASE}/api/v1/admin/evidence/reindex`, {
      method: "POST",
      body: JSON.stringify({ scope: "ALL" }),
    });
    expect(resp.status).toBe(202);
    const accepted = (await resp.json()) as { task_id: string; status: string };
    expect(accepted).toMatchObject({ status: "RUNNING" });

    // 首次轮询 RUNNING；二次起终态 SUCCEEDED + stats（证据总量 20）
    const first = (await (await fetch(`${BASE}/api/v1/admin/quality/tasks/${accepted.task_id}`)).json()) as {
      status: string;
      stats?: { total?: number; mismatched?: number };
    };
    expect(first.status).toBe("RUNNING");
    const second = (await (await fetch(`${BASE}/api/v1/admin/quality/tasks/${accepted.task_id}`)).json()) as {
      status: string;
      finished_at: string | null;
      stats: { total: number; rechecked: number; mismatched: number };
    };
    expect(second.status).toBe("SUCCEEDED");
    expect(second.finished_at).not.toBeNull();
    expect(second.stats).toMatchObject({ total: 20, rechecked: 20, mismatched: 0 });
  });
});
