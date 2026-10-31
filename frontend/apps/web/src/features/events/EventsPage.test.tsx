import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "../../app/providers/ThemeProvider";
import { routes } from "../../app/router";
import { useSessionStore, type AuthTokenResponse } from "../auth/session-store";
import { findEvent } from "../../mocks/data/events";
import { EVT_ORDER_A_RISK, EVT_ORDER_B_RISK, EVT_ORDER_H_RISK } from "../../mocks/data/ids";
import { server } from "../../mocks/server";

function sessionOf(username: string, roles: string[]): AuthTokenResponse {
  return {
    access_token: `t-${username}`,
    refresh_token: `r-${username}`,
    expires_in: 7200,
    tenant: {
      tenant_id: "00000000-0000-0000-0000-000000000001",
      slug: "default",
      name: "默认租户",
      status: "ACTIVE",
    },
    user: {
      user_id: "00000000-0000-0000-0000-000000000002",
      username,
      roles,
      is_platform_admin: false,
    },
  };
}

function renderEvents() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: ["/admin/events"] });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

function rows(): NodeListOf<HTMLElement> {
  return document.querySelectorAll('[data-dom-id="event-row"]');
}

function paginationText(): string {
  return document.querySelector('[data-dom-id="pagination-range"]')?.textContent ?? "";
}

const nextBtn = () => document.querySelector('[data-dom-id="pagination-next"]') as HTMLButtonElement;
const prevBtn = () => document.querySelector('[data-dom-id="pagination-prev"]') as HTMLButtonElement;

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  vi.useRealTimers();
});
afterAll(() => server.close());
beforeEach(() => {
  // 默认 24H 窗口以系统时钟计算：钉到 fixtures 演示锚（mocks/lib/demo-time DEMO_NOW），
  // 保证窗口内条数确定（否则真实时钟越过锚点后用例随时间漂移）。
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-09-28T08:30:00.000Z"));
  useSessionStore.getState().setSession(sessionOf("manager1", ["MANAGER"]));
});

/**
 * fixtures 锚定（mocks/data/events）：锚点前 24H 窗口内 24 条——PLM 失败 1 + 库存例行
 * 16 + 能力结果 B/C/E/H/J 5 + 案例创建 1 + 交期变更 1；事件总数 55。
 */
describe("EventsPage 事件流（MSW 模式渲染路由）", () => {
  it("KPI 四卡对齐 health.ops_metrics（18,421 / 0.81s / 99.40% / 6）", async () => {
    renderEvents();

    const band = await waitFor(() => {
      const el = document.querySelector('[data-dom-id="events-kpi-band"]');
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });
    await waitFor(() => expect(within(band).getByText("18,421")).toBeInTheDocument());
    expect(within(band).getByText("峰值 742 / 小时")).toBeInTheDocument();
    expect(within(band).getByText("0.81s")).toBeInTheDocument();
    expect(within(band).getByText("99.40%")).toBeInTheDocument();
    expect(within(band).getByText("重复事件极少")).toBeInTheDocument();
    expect(within(band).getByText("6")).toBeInTheDocument();
    expect(within(band).getByText("待人工复核")).toBeInTheDocument();
  });

  it("9 列表格：首页 20 行 + 分页文案（含 total）→ 下一页 4 行", async () => {
    renderEvents();

    const table = (await waitFor(() => {
      const el = document.querySelector('[data-dom-id="events-table"]');
      expect(el).not.toBeNull();
      return el as HTMLElement;
    }))!;
    for (const h of ["事件", "类型", "对象", "描述", "发生时间", "接入耗时", "来源", "状态", "操作"]) {
      expect(within(table).getByText(h)).toBeInTheDocument();
    }

    await waitFor(() => expect(rows().length).toBe(20));
    expect(paginationText()).toBe("显示 1–20 条，共 24 条");
    expect(document.querySelector('[data-dom-id="pagination-page"]')?.textContent).toBe("1");

    fireEvent.click(document.querySelector('[data-dom-id="pagination-next"]')!);
    await waitFor(() => expect(rows().length).toBe(4));
    expect(paginationText()).toBe("显示 21–24 条，共 24 条");
    expect(
      (document.querySelector('[data-dom-id="pagination-next"]') as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("类型筛选 capability.result.order_risk → 4 行（窗口内 B/C/H/J）+ 可移除 chip", async () => {
    renderEvents();

    await waitFor(() => expect(rows().length).toBe(20));
    fireEvent.change(document.querySelector('[data-dom-id="events-type"]')!, {
      target: { value: "capability.result.order_risk" },
    });

    await waitFor(() => expect(rows().length).toBe(4));
    expect(paginationText()).toBe("显示 1–4 条，共 4 条");
    expect(screen.getByText("类型：订单风险")).toBeInTheDocument();

    fireEvent.click(document.querySelector('[data-dom-id="chip-remove-type"]')!);
    await waitFor(() => expect(rows().length).toBe(20));
    expect(paginationText()).toBe("显示 1–20 条，共 24 条");
  });

  it("筛选无结果（ORDER_SNAPSHOT 展示型事件未迁入）→ 空态双动作 → 清空筛选恢复", async () => {
    renderEvents();

    await waitFor(() => expect(rows().length).toBe(20));
    fireEvent.change(document.querySelector('[data-dom-id="events-type"]')!, {
      target: { value: "ORDER_SNAPSHOT" },
    });

    expect(await screen.findByText("未找到事件")).toBeInTheDocument();
    expect(document.querySelector('[data-dom-id="events-empty"]')).not.toBeNull();
    expect(document.querySelector('[data-dom-id="empty-primary-action"]')?.textContent).toBe(
      "清空筛选",
    );
    expect(document.querySelector('[data-dom-id="empty-secondary-action"]')?.textContent).toBe(
      "回放事件",
    );

    fireEvent.click(document.querySelector('[data-dom-id="empty-primary-action"]')!);
    await waitFor(() => expect(rows().length).toBe(20));
    expect(paginationText()).toBe("显示 1–20 条，共 24 条");
  });

  it("total 缺失（真实契约降级）→ 隐藏计数文案，游标前进/后退仍可用", async () => {
    const ORDER_B = findEvent(EVT_ORDER_B_RISK)!;
    const ORDER_H = findEvent(EVT_ORDER_H_RISK)!;
    const ORDER_A = findEvent(EVT_ORDER_A_RISK)!;
    server.use(
      http.get("*/api/v1/events", ({ request }) => {
        const cursor = new URL(request.url).searchParams.get("cursor");
        if (cursor === "c1") return HttpResponse.json({ items: [ORDER_A], next_cursor: null });
        return HttpResponse.json({ items: [ORDER_B, ORDER_H], next_cursor: "c1" });
      }),
    );

    renderEvents();

    await waitFor(() => expect(rows().length).toBe(2));
    expect(document.querySelector('[data-dom-id="events-pagination-fallback"]')).not.toBeNull();
    expect(document.querySelector('[data-dom-id="pagination-range"]')).toBeNull();
    expect(prevBtn().disabled).toBe(true);
    expect(nextBtn().disabled).toBe(false);

    fireEvent.click(nextBtn());
    await waitFor(() => expect(rows().length).toBe(1));
    expect(nextBtn().disabled).toBe(true);
    expect(prevBtn().disabled).toBe(false);

    fireEvent.click(prevBtn());
    await waitFor(() => expect(rows().length).toBe(2));
    expect(prevBtn().disabled).toBe(true);
  });

  it("翻页请求在途 → 上/下一页禁用（keepPreviousData 下防竞态双击）", async () => {
    const ORDER_B = findEvent(EVT_ORDER_B_RISK)!;
    const ORDER_H = findEvent(EVT_ORDER_H_RISK)!;
    const ORDER_A = findEvent(EVT_ORDER_A_RISK)!;
    let release: (() => void) | null = null;
    server.use(
      http.get("*/api/v1/events", async ({ request }) => {
        const cursor = new URL(request.url).searchParams.get("cursor");
        if (cursor == null) {
          return HttpResponse.json({ items: [ORDER_B, ORDER_H], next_cursor: "c1", total: 2 });
        }
        await new Promise<void>((resolve) => {
          release = resolve;
        });
        return HttpResponse.json({ items: [ORDER_A], next_cursor: null, total: 2 });
      }),
    );

    renderEvents();

    await waitFor(() => expect(rows().length).toBe(2));
    fireEvent.click(nextBtn());
    await waitFor(() => expect(nextBtn().disabled).toBe(true));
    expect(prevBtn().disabled).toBe(true);

    release!();
    await waitFor(() => expect(rows().length).toBe(1));
    expect(prevBtn().disabled).toBe(false);
  });
});
