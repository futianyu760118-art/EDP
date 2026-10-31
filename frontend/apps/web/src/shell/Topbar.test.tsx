import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { ThemeProvider } from "../app/providers/ThemeProvider";
import { routes } from "../app/router";
import { useSessionStore, type AuthTokenResponse } from "../features/auth/session-store";
import { server } from "../mocks/server";

function sessionOf(): AuthTokenResponse {
  return {
    access_token: "t-admin1",
    refresh_token: "r-admin1",
    expires_in: 7200,
    tenant: {
      tenant_id: "00000000-0000-0000-0000-000000000001",
      slug: "default",
      name: "默认租户",
      status: "ACTIVE",
    },
    user: {
      user_id: "00000000-0000-0000-0000-000000000002",
      username: "admin1",
      roles: ["ADMIN"],
      is_platform_admin: false,
    },
  };
}

function renderAt(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

const searchInput = () =>
  document.querySelector('[data-dom-id="global-search"]') as HTMLInputElement | null;

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(() => {
  useSessionStore.getState().setSession(sessionOf());
});

describe("Topbar 全局搜索 URL 回填（W6 跟进 D-14）", () => {
  it("直接进入 /search?q=xxx → 输入框回填 q", async () => {
    renderAt("/search?q=SO-2026-00123");
    await waitFor(() => expect(searchInput()?.value).toBe("SO-2026-00123"));
  });

  it("非搜索页不回填（输入框保持为空）", async () => {
    renderAt("/admin/overview");
    await waitFor(() => expect(searchInput()).not.toBeNull());
    expect(searchInput()!.value).toBe("");
  });
});
