import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { setupServer } from "msw/node";
import { handlers } from "../handlers";
import { OBJ_ORDER_B } from "../data/ids";

const server = setupServer(...handlers);
const BASE = "http://mock.test";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("registry handlers", () => {
  it("列表：object_type=ORDER 过滤 + total=10 + 分页", async () => {
    const resp = await fetch(`${BASE}/api/v1/objects?object_type=ORDER&limit=3`);
    const body = (await resp.json()) as { items: { object_type: string }[]; next_cursor: string | null; total: number };
    expect(resp.status).toBe(200);
    expect(body.total).toBe(10);
    expect(body.items).toHaveLength(3);
    expect(body.next_cursor).toBeTruthy();
    expect(body.items.every((i) => i.object_type === "ORDER")).toBe(true);
  });

  it("组合键查询：erp/SO-2026-00123 → 订单 B rev7", async () => {
    const resp = await fetch(`${BASE}/api/v1/objects?source_system=erp&source_id=SO-2026-00123`);
    const body = (await resp.json()) as { items: { revision: number }[]; total: number };
    expect(body.total).toBe(1);
    expect(body.items[0].revision).toBe(7);
  });

  it("点查 404（不泄露存在性）", async () => {
    const resp = await fetch(`${BASE}/api/v1/objects/00000000-0000-4000-8000-00000000dead`);
    expect(resp.status).toBe(404);
    expect(await resp.json()).toMatchObject({ error: { code: "NOT_FOUND" } });
  });

  it("新建 201 → 同键再提交 200 且 revision+1", async () => {
    const payload = {
      object_type: "ORDER",
      owner_domain: "sales",
      source_system: "erp",
      source_id: "SO-2026-00999",
      attributes: { name: "测试订单" },
    };
    const r1 = await fetch(`${BASE}/api/v1/objects`, { method: "POST", body: JSON.stringify(payload) });
    expect(r1.status).toBe(201);
    expect(((await r1.json()) as { revision: number }).revision).toBe(1);
    const r2 = await fetch(`${BASE}/api/v1/objects`, {
      method: "POST",
      body: JSON.stringify({ ...payload, idempotency: { expected_revision: 1 } }),
    });
    expect(r2.status).toBe(200);
    expect(((await r2.json()) as { revision: number }).revision).toBe(2);
  });

  it("乐观锁冲突：expected_revision 不符 → 409 + current_revision=7", async () => {
    const resp = await fetch(`${BASE}/api/v1/objects`, {
      method: "POST",
      body: JSON.stringify({
        object_type: "ORDER",
        owner_domain: "sales",
        source_system: "erp",
        source_id: "SO-2026-00123",
        idempotency: { expected_revision: 3 },
      }),
    });
    expect(resp.status).toBe(409);
    expect(await resp.json()).toMatchObject({ error: { code: "CONFLICT", current_revision: 7 } });
  });

  it("history：订单 B → 7 条 OBJECT_UPSERT 轨迹", async () => {
    const resp = await fetch(`${BASE}/api/v1/objects/${OBJ_ORDER_B}/history`);
    const body = (await resp.json()) as { revisions: { revision: number; action: string }[] };
    expect(body.revisions).toHaveLength(7);
    expect(body.revisions.at(-1)).toMatchObject({ revision: 7, action: "OBJECT_UPSERT" });
  });

  it("场景注入：X-Mock-Scenario=429 → RATE_LIMITED + Retry-After", async () => {
    const resp = await fetch(`${BASE}/api/v1/objects`, { headers: { "X-Mock-Scenario": "429" } });
    expect(resp.status).toBe(429);
    expect(resp.headers.get("Retry-After")).toBe("1");
  });
});
