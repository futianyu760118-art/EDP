import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { setupServer } from "msw/node";
import { handlers } from "../handlers";
import { EVT_ADAPTER_PLM_FAILED, EVT_ORDER_B_RISK, OBJ_ORDER_B } from "../data/ids";

const server = setupServer(...handlers);
const BASE = "http://mock.test";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("events handlers", () => {
  it("risk_level=P1 过滤：total=3（B/E/J）", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/events?risk_level=P1`)).json()) as {
      items: { risk_level: string }[];
      total: number;
    };
    expect(body.total).toBe(3);
    expect(body.items.every((e) => e.risk_level === "P1")).toBe(true);
  });

  it("occurred_at DESC 排序", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/events?limit=10`)).json()) as { items: { occurred_at: string }[] };
    const times = body.items.map((e) => e.occurred_at);
    expect([...times].sort().reverse()).toEqual(times);
  });

  it("字段对齐（§6.2）：ingest_latency_ms 60~299 / delivery_status / object_source_id 反查", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/events?limit=100`)).json()) as {
      items: {
        event_id: string;
        event_type: string;
        ingest_latency_ms?: number | null;
        delivery_status?: string | null;
        object_source_id?: string | null;
      }[];
    };
    expect(body.items.length).toBeGreaterThan(0);
    for (const e of body.items) {
      expect(e.ingest_latency_ms).toBeGreaterThanOrEqual(60);
      expect(e.ingest_latency_ms).toBeLessThanOrEqual(299);
      expect(["DELIVERED", "PENDING", "DEAD_LETTER"]).toContain(e.delivery_status);
      expect(typeof e.object_source_id).toBe("string");
    }
    // 场景 10 adapter.sync.failed → DEAD_LETTER；订单 B 结果事件 → SO-2026-00123
    expect(body.items.find((e) => e.event_id === EVT_ADAPTER_PLM_FAILED)?.delivery_status).toBe("DEAD_LETTER");
    expect(body.items.find((e) => e.event_id === EVT_ORDER_B_RISK)?.object_source_id).toBe("SO-2026-00123");
  });

  it("batch：缺 Idempotency-Key → 400；入库 accepted；重放 deduplicated=true", async () => {
    const noKey = await fetch(`${BASE}/api/v1/events/batch`, {
      method: "POST",
      body: JSON.stringify({ events: [] }),
    });
    expect(noKey.status).toBe(400);

    const payload = {
      events: [
        {
          event_type: "capability.result.order_risk",
          object_id: OBJ_ORDER_B,
          source_system: "agent-hub",
          occurred_at: "2026-09-28T08:00:00.000Z",
          actor_type: "AI" as const,
          actor_id: "agent:test",
          risk_level: "P2" as const,
          score: 0.5,
          data: { reason: "batch 写入测试" },
        },
      ],
    };
    const r1 = await fetch(`${BASE}/api/v1/events/batch`, {
      method: "POST",
      headers: { "Idempotency-Key": "test-key-1" },
      body: JSON.stringify(payload),
    });
    expect(await r1.json()).toMatchObject({ accepted: 1, duplicated: 0, rejected: 0, deduplicated: false });

    // batch 合成事件：刚入库 PENDING + 耗时派生 + object_source_id 反查
    const created = (await (
      await fetch(`${BASE}/api/v1/events?object_id=${OBJ_ORDER_B}&event_type=capability.result.order_risk`)
    ).json()) as {
      items: {
        actor_id: string | null;
        ingest_latency_ms?: number | null;
        delivery_status?: string | null;
        object_source_id?: string | null;
      }[];
    };
    const synthetic = created.items.find((e) => e.actor_id === "agent:test");
    expect(synthetic).toMatchObject({ delivery_status: "PENDING", object_source_id: "SO-2026-00123" });
    expect(synthetic?.ingest_latency_ms).toBeGreaterThanOrEqual(60);
    expect(synthetic?.ingest_latency_ms).toBeLessThanOrEqual(299);

    const r2 = await fetch(`${BASE}/api/v1/events/batch`, {
      method: "POST",
      headers: { "Idempotency-Key": "test-key-1" },
      body: JSON.stringify(payload),
    });
    expect(await r2.json()).toMatchObject({ accepted: 1, deduplicated: true });

    // 入库后 P2 计数 4 → 5
    const list = (await (await fetch(`${BASE}/api/v1/events?risk_level=P2`)).json()) as { total: number };
    expect(list.total).toBe(5);
  });

  it("since 闭区间过滤", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/events?since=2026-09-28T05:00:00.000Z`)).json()) as {
      items: { occurred_at: string }[];
    };
    expect(body.items.every((e) => e.occurred_at >= "2026-09-28T05:00:00.000Z")).toBe(true);
  });
});
