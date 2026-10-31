import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { setupServer } from "msw/node";
import { handlers } from "../handlers";
import { capabilityRows } from "../data/catalog";

const server = setupServer(...handlers);
const BASE = "http://mock.test";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

/** W3R 能力注册 handler（T9 capability 数据源）：Page 信封 + domain/status 过滤。 */
describe("catalog handlers（GET /capabilities）", () => {
  it("全量：Page 信封（items/next_cursor/total）与 fixtures 对齐", async () => {
    const page = (await (await fetch(`${BASE}/api/v1/capabilities`)).json()) as {
      items: { capability_id: string; name: string }[];
      next_cursor: string | null;
      total: number;
    };
    expect(page.items).toHaveLength(capabilityRows.length);
    expect(page.total).toBe(capabilityRows.length);
    expect(page.next_cursor).toBeNull();
    expect(page.items.map((c) => c.name)).toContain("订单风险评估");
  });

  it("domain/status 过滤：delivery × ACTIVE 子集", async () => {
    const page = (await (
      await fetch(`${BASE}/api/v1/capabilities?domain=delivery&status=ACTIVE`)
    ).json()) as { items: { domain: string; status: string }[] };
    expect(page.items.length).toBeGreaterThan(0);
    expect(page.items.every((c) => c.domain === "delivery" && c.status === "ACTIVE")).toBe(true);
  });
});
