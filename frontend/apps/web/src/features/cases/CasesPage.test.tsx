import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { ThemeProvider } from "../../app/providers/ThemeProvider";
import { routes } from "../../app/router";
import { useSessionStore, type AuthTokenResponse } from "../auth/session-store";
import { CASE_ORDER_B } from "../../mocks/data/ids";
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

function renderCases() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: ["/cases"] });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

const rows = () => document.querySelectorAll('[data-dom-id^="cases-row-"]');

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(() => {
  useSessionStore.getState().setSession(sessionOf("manager1", ["MANAGER"]));
});

/**
 * fixtures 锚定（mocks/data/cases.ts）：23 条 = 故事 7（P0×1 OPEN / P1×3 /
 * DECIDED×1=B / CANCELLED×2）+ 例行 16（OPEN P2/P3）；CASES_PAGE_LIMIT=20 →
 * 首页 20 行、次页 3 行；created_at DESC 首行 = 订单 H（P0）。
 */
describe("CasesPage 闭环案例列表（MSW 模式渲染路由）", () => {
  it("表格渲染首页 20 行；状态筛选 DECIDED → 单行 + chip 移除恢复", async () => {
    renderCases();

    await waitFor(() => expect(rows().length).toBe(20));
    expect(document.querySelector('[data-dom-id="cases-table"]')).not.toBeNull();
    expect(document.querySelector(`[data-dom-id="cases-row-${CASE_ORDER_B}"]`)!.textContent).toContain(
      "DC-20260928-007",
    );

    fireEvent.change(document.querySelector('[data-dom-id="cases-filter-status"]')!, {
      target: { value: "DECIDED" },
    });
    await waitFor(() => expect(rows().length).toBe(1));
    expect(rows()[0].textContent).toContain("DC-20260928-007");

    expect(screen.getByText("状态：已决策")).toBeInTheDocument();
    fireEvent.click(document.querySelector('[data-dom-id="chip-remove-status"]')!);
    await waitFor(() => expect(rows().length).toBe(20));
  });

  it("风险筛选 P0 → 单行；组合无结果空态 → 清空筛选恢复", async () => {
    renderCases();
    await waitFor(() => expect(rows().length).toBe(20));

    fireEvent.change(document.querySelector('[data-dom-id="cases-filter-risk"]')!, {
      target: { value: "P0" },
    });
    await waitFor(() => expect(rows().length).toBe(1));
    expect(rows()[0].textContent).toContain("SO-2026-00129");
    expect(screen.getByText("风险：P0 · 紧急")).toBeInTheDocument();

    // 组合 DECIDED + P0 → 无结果 → 空态三件套
    fireEvent.change(document.querySelector('[data-dom-id="cases-filter-status"]')!, {
      target: { value: "DECIDED" },
    });
    await waitFor(() => expect(document.querySelector('[data-dom-id="cases-empty"]')).not.toBeNull());
    expect(screen.getByText("未找到案例")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "清空筛选" }));
    await waitFor(() => expect(rows().length).toBe(20));
  });

  it("游标分页：下一页 3 行（共 23 条）→ 上一页恢复；「查看」跳转详情", async () => {
    renderCases();
    await waitFor(() => expect(rows().length).toBe(20));

    fireEvent.click(document.querySelector('[data-dom-id="pagination-next"]')!);
    await waitFor(() => expect(rows().length).toBe(3));
    expect(document.querySelector('[data-dom-id="pagination-range"]')!.textContent).toContain("共 23 条");

    fireEvent.click(document.querySelector('[data-dom-id="pagination-prev"]')!);
    await waitFor(() => expect(rows().length).toBe(20));

    fireEvent.click(document.querySelector(`[data-dom-id="cases-view-${CASE_ORDER_B}"]`)!);
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="case-detail-question"]')).not.toBeNull(),
    );
  });
});
