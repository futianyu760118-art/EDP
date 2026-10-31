import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { setupServer } from "msw/node";
import { handlers } from "../handlers";

const server = setupServer(...handlers);
const BASE = "http://mock.test";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("ebms & audit handlers", () => {
  it("异常默认 OPEN：7 条；P1 过滤：3 条", async () => {
    const open = (await (await fetch(`${BASE}/api/v1/ebms/exceptions`)).json()) as { total: number };
    expect(open.total).toBe(7);
    const p1 = (await (await fetch(`${BASE}/api/v1/ebms/exceptions?severity=P1`)).json()) as { total: number };
    expect(p1.total).toBe(3);
  });

  it("status=RESOLVED：仅场景 8（数据不一致）1 条", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/ebms/exceptions?status=RESOLVED`)).json()) as {
      items: { result_type: string }[];
      total: number;
    };
    expect(body.total).toBe(1);
    expect(body.items[0].result_type).toBe("DATA_QUALITY");
  });

  it("P1 前 3 条用于总览风险列表（limit=3）", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/ebms/exceptions?severity=P1&limit=3`)).json()) as {
      items: { risk_level: string }[];
    };
    expect(body.items).toHaveLength(3);
    expect(body.items.every((i) => i.risk_level === "P1")).toBe(true);
  });

  it("audit-logs：action=GUARD_DENIED → 2 条（越权举证）", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/audit-logs?action=GUARD_DENIED`)).json()) as { total: number };
    expect(body.total).toBe(2);
  });

  it("audit-logs 点查与 404", async () => {
    const found = await fetch(`${BASE}/api/v1/audit-logs/10230`);
    expect(found.status).toBe(200);
    const missing = await fetch(`${BASE}/api/v1/audit-logs/99999`);
    expect(missing.status).toBe(404);
  });
});
