import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { ThemeProvider } from "../../app/providers/ThemeProvider";
import { routes } from "../../app/router";
import { useSessionStore, type AuthTokenResponse } from "../auth/session-store";
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

function renderRegistry() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: ["/admin/registry"] });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

function cards(): NodeListOf<HTMLElement> {
  return document.querySelectorAll('[data-dom-id="object-card"]');
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(() => {
  useSessionStore.getState().setSession(sessionOf("manager1", ["MANAGER"]));
});

/**
 * 首卡 = 订单 B（SO-2026-00123，updated_at 2h 最新；P1 → At Risk；revision 7
 * → mock history 按 revision 生成 7 条 OBJECT_UPSERT 轨迹）。
 */
describe("DetailDrawer 详情抽屉（卡片详情入口）", () => {
  it("打开 → 头部 MonoId/pill + 基本信息六格 + history 时间线 7 节点 + attributes 折叠 + X 关闭", async () => {
    renderRegistry();
    await waitFor(() => expect(cards().length).toBe(20));

    fireEvent.click(document.querySelector('[data-dom-id="object-card-detail"]')!);
    const drawer = (await waitFor(() => {
      const el = document.querySelector('[data-dom-id="object-drawer"]');
      expect(el).not.toBeNull();
      return el as HTMLElement;
    }))!;

    // 头部：MonoId(source_id) + 派生 pill + 名称
    expect(within(drawer).getAllByText("SO-2026-00123").length).toBeGreaterThan(0);
    expect(within(drawer).getAllByText("At Risk").length).toBeGreaterThan(0);
    expect(within(drawer).getByText("订单 B · 关键料缺失")).toBeInTheDocument();

    // 基本信息六格
    const info = drawer.querySelector('[data-dom-id="object-drawer-info"]') as HTMLElement;
    for (const label of ["类型", "域", "来源", "状态", "创建时间", "更新时间"]) {
      expect(within(info).getByText(label)).toBeInTheDocument();
    }
    expect(within(info).getByText("ORDER")).toBeInTheDocument();
    expect(within(info).getByText("Sales")).toBeInTheDocument();
    expect(within(info).getByText("ERP")).toBeInTheDocument();

    // revision 时间线：节点数 = mock history 长度（订单 B revision 7）
    await waitFor(() => {
      expect(within(drawer).getAllByText(/OBJECT_UPSERT → Rev \d+/)).toHaveLength(7);
    });
    expect(within(drawer).getAllByText("adapter:erp").length).toBeGreaterThan(0);

    // attributes 折叠展开后 JSON 原文
    fireEvent.click(within(drawer).getByText("attributes"));
    expect(await within(drawer).findByText(/customer_code/)).toBeInTheDocument();

    fireEvent.click(document.querySelector('[data-dom-id="object-drawer-close"]')!);
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="object-drawer"]')).toBeNull(),
    );
  });
});
