import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { setupServer } from "msw/node";
import { handlers } from "../handlers";
import { SYNC_ID } from "../data/ids";

const server = setupServer(...handlers);
const BASE = "http://mock.test";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("health & adapters handlers", () => {
  it("health：HA 角色 primary + 备份恢复验证 PASSED + ops_metrics", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/health?deep=true`)).json()) as {
      db_ha: { role: string };
      backup?: { last_restore_verify: string };
      ops_metrics?: { p95_latency_ms: number; evidence_count: number };
    };
    expect(body.db_ha.role).toBe("primary");
    expect(body.backup?.last_restore_verify).toBe("PASSED");
    expect(body.ops_metrics?.evidence_count).toBe(20);
    expect(body.ops_metrics?.p95_latency_ms).toBeLessThan(2000);
  });

  it("ops_metrics.idempotency_hit_rate 为 0~1 比值（真后端口径，渲染端 ×100）", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/health`)).json()) as {
      ops_metrics?: { idempotency_hit_rate: number };
    };
    const rate = body.ops_metrics?.idempotency_hit_rate ?? -1;
    expect(rate).toBeGreaterThan(0);
    expect(rate).toBeLessThanOrEqual(1);
  });

  it("outbox status：pending=3 failed=0", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/admin/outbox/status`)).json()) as { pending: number; failed: number };
    expect(body).toMatchObject({ pending: 3, failed: 0 });
  });

  it("adapters 清单：5 个，plm 降级", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/admin/adapters`)).json()) as {
      items: { adapter: string; health: string }[];
      total: number;
    };
    expect(body.total).toBe(5);
    expect(body.items.find((a) => a.adapter === "plm")?.health).toBe("DEGRADED");
  });

  it("sync：replay 模式 202 RUNNING；非法 mode 400；未知适配器 404", async () => {
    const ok = await fetch(`${BASE}/api/v1/admin/adapters/erp/sync`, {
      method: "POST",
      body: JSON.stringify({ mode: "replay", since: "2026-09-28T00:00:00Z" }),
    });
    expect(ok.status).toBe(202);
    expect(await ok.json()).toMatchObject({ sync_id: SYNC_ID, status: "RUNNING" });

    const bad = await fetch(`${BASE}/api/v1/admin/adapters/erp/sync`, {
      method: "POST",
      body: JSON.stringify({ mode: "whatever" }),
    });
    expect(bad.status).toBe(400);

    const missing = await fetch(`${BASE}/api/v1/admin/adapters/nope/sync`, {
      method: "POST",
      body: JSON.stringify({ mode: "full" }),
    });
    expect(missing.status).toBe(404);
  });
});
