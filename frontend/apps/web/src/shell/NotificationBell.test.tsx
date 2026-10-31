import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { ThemeProvider } from "../app/providers/ThemeProvider";
import { events } from "../mocks/data/events";
import { EVT_QUALITY_REINDEX_OK, OBJ_ORDER_A } from "../mocks/data/ids";
import { server } from "../mocks/server";
import { NotificationBell } from "./NotificationBell";

function renderBell() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <NotificationBell />
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

const badge = () => document.querySelector('[data-dom-id="notifications-badge"]');

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(() => {
  window.localStorage.clear();
});

/** fixtures quality.* 四条（mocks/data/events.ts）：重索引成功/失配、复检成功、checksum 失败。 */
describe("NotificationBell 最小消息中心", () => {
  it("未读徽标（fixtures 4 条 quality.*）→ 点开面板渲染词表摘要 → 徽标清零", async () => {
    renderBell();

    await waitFor(() => expect(badge()?.textContent).toBe("4"));

    fireEvent.click(document.querySelector('[data-dom-id="notifications-btn"]')!);
    await waitFor(() => expect(document.querySelector('[data-dom-id="bell-panel"]')).not.toBeNull());

    const list = document.querySelector('[data-dom-id="bell-list"]')!;
    // 最近 20 条 quality. 前缀事件（客户端过滤）
    expect(list.querySelectorAll("li").length).toBe(4);
    // 词表映射：QUALITY_REINDEX_SUCCEEDED → 质量重索引成功（最新一条置顶）
    expect(list.querySelector("li")!.textContent).toContain("质量重索引成功");
    expect(list.textContent).toContain("质量重索引失配");
    expect(list.textContent).toContain("质量复检成功");
    expect(list.textContent).toContain("质量校验和失败");
    // data 摘要（reindex stats）
    expect(list.querySelector("li")!.textContent).toContain("重算 20 条");

    // 点开即清零：localStorage 水位推进 + 徽标消失
    expect(
      window.localStorage.getItem("edp.bell.lastReadTs"),
    ).toBe(events.find((e) => e.event_id === EVT_QUALITY_REINDEX_OK)!.occurred_at);
    await waitFor(() => expect(badge()).toBeNull());
  });

  it("部分已读（水位介于两条之间）→ 徽标只计更新事件", async () => {
    // 水位 = 2026-09-27T06:25Z：仅重索引成功（06:30）未读，失配（06:24）已读
    window.localStorage.setItem("edp.bell.lastReadTs", "2026-09-27T06:25:00.000Z");
    renderBell();

    await waitFor(() => expect(badge()?.textContent).toBe("1"));
  });

  it("无 quality.* 事件 → 空态「暂无质量通知」且无徽标", async () => {
    server.use(
      http.get("*/api/v1/events", () =>
        HttpResponse.json({
          items: [
            {
              event_id: "00000000-0000-4000-8000-000000000402",
              tenant_id: "00000000-0000-4000-8000-000000000001",
              event_type: "capability.result.order_risk",
              object_id: OBJ_ORDER_A,
              source_system: "agent-hub",
              occurred_at: "2026-09-28T03:30:00.000Z",
              actor_type: "AI",
              actor_id: "agent:t",
              result_type: null,
              risk_level: null,
              score: null,
              data: {},
              idempotency_key: null,
              ingest_latency_ms: 100,
              delivery_status: "DELIVERED",
              object_source_id: null,
              created_at: "2026-09-28T03:30:00.000Z",
            },
          ],
          next_cursor: null,
          total: 1,
        }),
      ),
    );
    renderBell();

    await waitFor(() => expect(badge()).toBeNull());
    fireEvent.click(document.querySelector('[data-dom-id="notifications-btn"]')!);
    await waitFor(() => expect(document.querySelector('[data-dom-id="bell-empty"]')).not.toBeNull());
    expect(document.querySelector('[data-dom-id="bell-empty"]')!.textContent).toContain(
      "暂无质量通知",
    );
  });

  // T9（W5-12 收口）：查询走后端前缀过滤——请求须携带 event_type_prefix=quality.
  it("events 请求携带 event_type_prefix=quality. → 下拉渲染质量事件", async () => {
    let seenPrefix: string | null = null;
    server.use(
      http.get("*/api/v1/events", ({ request }) => {
        seenPrefix = new URL(request.url).searchParams.get("event_type_prefix");
        const qualityOnly = events.filter((e) => e.event_type.startsWith("quality."));
        return HttpResponse.json({ items: qualityOnly, next_cursor: null, total: qualityOnly.length });
      }),
    );
    renderBell();

    await waitFor(() => expect(badge()?.textContent).toBe("4"));
    fireEvent.click(document.querySelector('[data-dom-id="notifications-btn"]')!);
    await waitFor(() => expect(document.querySelector('[data-dom-id="bell-list"]')).not.toBeNull());
    expect(document.querySelector('[data-dom-id="bell-list"]')!.textContent).toContain("质量重索引成功");
    expect(seenPrefix).toBe("quality.");
  });
});
