import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { ThemeProvider } from "../../app/providers/ThemeProvider";
import { routes } from "../../app/router";
import { useSessionStore, type AuthTokenResponse } from "../auth/session-store";
import { server } from "../../mocks/server";
import { EVT_ORDER_B_RISK } from "../../mocks/data/ids";

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

function renderOverview() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: ["/admin/overview"] });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(() => {
  useSessionStore.getState().setSession(sessionOf("manager1", ["MANAGER"]));
});

/**
 * fixtures 锚定（mocks/data）：topExceptions（P1×3）occurred_at DESC 首条 = ORDER_B
 * （EVT_ORDER_B_RISK，5 小时前）——对象 OBJ_ORDER_B：amount 120000 / delivery_date 2026-10-15；
 * 事件共 12 条，DESC 前 4 全为 inventory.changed（1h/2h/3h/4h）；证据 object_id 过滤命中 2 条
 * （具名快照 5h + 例行快照 28h），证据空态（"暂无关联证据"）不在此 fixtures 路径上触发。
 */
describe("风险抽屉（T5：列表点击/Hero 入口 → 抽屉联动）", () => {
  it("点击第一张风险卡 → 抽屉出现：RSK- 短 ID / 对象金额与交付日期 / 4 节点时间线 / 2 条证据；X 关闭消失", async () => {
    renderOverview();

    const firstCard = await waitFor(() => {
      const cards = document.querySelectorAll('[data-dom-id="risk-card"]');
      expect(cards.length).toBe(3);
      return cards[0] as HTMLElement;
    });
    fireEvent.click(firstCard);

    const drawer = await waitFor(() => {
      const el = document.querySelector('[data-dom-id="risk-drawer"]');
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });
    // W4 泛化（W3-31 收口）：短 ID 统一尾 8；result_type 随事件详情异步到达
    expect(within(drawer).getAllByText(`RSK-${EVT_ORDER_B_RISK.slice(-8)}`).length).toBeGreaterThan(0);
    await waitFor(() => expect(within(drawer).getByText("ORDER_RISK")).toBeInTheDocument());

    await waitFor(() => {
      expect(drawer.querySelector('[data-dom-id="risk-drawer-amount"]')?.textContent).toBe("120,000");
    });
    expect(drawer.querySelector('[data-dom-id="risk-drawer-delivery"]')?.textContent).toBe("2026-10-15");

    await waitFor(() => {
      expect(within(drawer).getAllByText("inventory.changed")).toHaveLength(4);
    });
    await waitFor(() => {
      expect(drawer.querySelectorAll('[data-dom-id="risk-evidence-row"]')).toHaveLength(2);
    });

    fireEvent.click(drawer.querySelector('[data-dom-id="risk-drawer-close"]')!);
    await waitFor(() => {
      expect(document.querySelector('[data-dom-id="risk-drawer"]')).toBeNull();
    });
  });

  it("Hero「查看风险详情」同样打开抽屉（锚定第一条 P1）", async () => {
    renderOverview();

    fireEvent.click(await screen.findByRole("button", { name: "查看风险详情" }));

    const drawer = await waitFor(() => {
      const el = document.querySelector('[data-dom-id="risk-drawer"]');
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });
    expect(within(drawer).getAllByText(`RSK-${EVT_ORDER_B_RISK.slice(-8)}`).length).toBeGreaterThan(0);
    await waitFor(() => {
      expect(drawer.querySelector('[data-dom-id="risk-drawer-amount"]')?.textContent).toBe("120,000");
    });
  });
});
