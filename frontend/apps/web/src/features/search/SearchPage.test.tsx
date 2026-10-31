import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { ThemeProvider } from "../../app/providers/ThemeProvider";
import { routes } from "../../app/router";
import { useSessionStore, type AuthTokenResponse } from "../auth/session-store";
import { server } from "../../mocks/server";

function sessionOf(username: string): AuthTokenResponse {
  return {
    access_token: `t-${username}`,
    refresh_token: `r-${username}`,
    expires_in: 7200,
    tenant: {
      tenant_id: "00000000-0000-4000-8000-000000000001",
      slug: "default",
      name: "默认租户",
      status: "ACTIVE",
    },
    user: {
      user_id: "00000000-0000-4000-8000-000000000002",
      username,
      roles: ["ANALYST"],
      is_platform_admin: false,
    },
  };
}

function renderSearch(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
  return router;
}

const $ = (id: string) => document.querySelector(`[data-dom-id="${id}"]`);
const rows = (id: string) => document.querySelectorAll(`[data-dom-id="${id}"]`);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(() => {
  useSessionStore.getState().setSession(sessionOf("analyst1"));
});

/** T8 全局搜索页（EDP-601）：MSW fixtures 命中三组（handlers/search.ts）/ 空结果三件套 / q 参数联动。 */
describe("SearchPage 全局搜索（MSW 模式渲染路由）", () => {
  it("命中：q=order → 三组区块 + 计数 + 行内容 + 汇总条", async () => {
    renderSearch("/search?q=order");

    await waitFor(() => expect($("search-section-objects")).not.toBeNull());
    expect($("search-section-objects-count")!.textContent).toContain("2 条");
    expect($("search-section-events-count")!.textContent).toContain("2 条");
    expect($("search-section-evidence-count")!.textContent).toContain("2 条");

    // 行内容：object_type pill / source_id / 事件类型中文 / 证据 ref
    expect(rows("search-object-row").length).toBe(2);
    expect($("search-section-objects")!.textContent).toContain("sales_order");
    expect($("search-section-objects")!.textContent).toContain("SO-2026-00123");
    expect($("search-section-events")!.textContent).toContain("订单风险");
    expect($("search-section-evidence")!.textContent).toContain("ORDER-2026-0099");

    // 汇总：total = 2+2+2
    expect($("search-summary")!.textContent).toContain("共 6 条结果");
  });

  it("空结果：q=zzz → 空态三件套 + 清除搜索回空引导", async () => {
    const router = renderSearch("/search?q=zzz");

    await waitFor(() => expect($("search-empty")).not.toBeNull());
    expect($("search-empty")!.textContent).toContain("未找到相关结果");
    expect($("search-empty")!.textContent).toContain("zzz");

    fireEvent.click($("empty-primary-action")!);
    await waitFor(() => expect(router.state.location.search).toBe(""));
    await waitFor(() => expect($("search-idle")).not.toBeNull());
    expect($("search-idle")!.textContent).toContain("输入关键词开始搜索");
  });

  it("空态次动作「查看业务对象」→ /admin/registry", async () => {
    const router = renderSearch("/search?q=zzz");
    await waitFor(() => expect($("search-empty")).not.toBeNull());

    fireEvent.click($("empty-secondary-action")!);
    await waitFor(() => expect(router.state.location.pathname).toBe("/admin/registry"));
  });

  it("URL q 变化重新查询：命中 → 无命中切空态", async () => {
    const router = renderSearch("/search?q=order");
    await waitFor(() => expect($("search-section-objects")).not.toBeNull());

    void router.navigate("/search?q=zzz");
    await waitFor(() => expect($("search-empty")).not.toBeNull());
    expect($("search-section-objects")).toBeNull();
  });

  it("无 q：输入引导（不发包）", async () => {
    let called = 0;
    server.use(
      http.get("*/api/v1/search", () => {
        called += 1;
        return HttpResponse.json({ objects: [], events: [], evidence: [], query: "", total: 0 });
      }),
    );
    renderSearch("/search");

    await waitFor(() => expect($("search-idle")).not.toBeNull());
    expect(called).toBe(0);
  });
});
