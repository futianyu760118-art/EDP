import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "../../app/providers/ThemeProvider";
import { routes } from "../../app/router";
import { useSessionStore, type AuthTokenResponse } from "../auth/session-store";
import { TENANT_ACME_ID } from "../../mocks/data/tenants";
import { server } from "../../mocks/server";

function sessionOf(username: string, roles: string[]): AuthTokenResponse {
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
      user_id: "00000000-0000-0000-0000-000000000002",
      username,
      roles,
      is_platform_admin: true,
    },
  };
}

function renderTenants() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: ["/tenants"] });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
  return queryClient;
}

const rows = () => document.querySelectorAll('[data-dom-id^="tenants-row-"]');

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(() => {
  useSessionStore.getState().setSession(sessionOf("admin", ["PLATFORM_ADMIN"]));
});

/**
 * fixtures 锚定（mocks/data/tenants.ts）：10 租户 = ACTIVE×7 / SUSPENDED×2 /
 * CANCELLED×1，计划 TRIAL×2 / STANDARD×4 / PREMIUM×3 / DEDICATED×1；
 * TENANTS_PAGE_LIMIT=8 → 首页 8 行、次页 2 行（created_at DESC 首行 default）。
 */
describe("TenantsPage 租户列表（MSW 模式渲染路由）", () => {
  it("表格渲染首页 8 行；状态筛选 SUSPENDED → 2 行 + chip 移除恢复", async () => {
    renderTenants();

    await waitFor(() => expect(rows().length).toBe(8));
    expect(document.querySelector('[data-dom-id="tenants-table"]')).not.toBeNull();
    expect(document.querySelector(`[data-dom-id="tenants-row-${TENANT_ACME_ID}"]`)!.textContent).toContain(
      "acme",
    );
    // acme 曾临时提额 → 用量摘要来自 mock 扩展 usage
    expect(document.querySelector(`[data-dom-id="tenants-usage-${TENANT_ACME_ID}"]`)!.textContent).toContain(
      "GB",
    );

    fireEvent.change(document.querySelector('[data-dom-id="tenants-filter-status"]')!, {
      target: { value: "SUSPENDED" },
    });
    await waitFor(() => expect(rows().length).toBe(2));
    expect(rows()[0].textContent).toContain("已暂停");

    expect(screen.getByText("状态：已暂停")).toBeInTheDocument();
    fireEvent.click(document.querySelector('[data-dom-id="chip-remove-status"]')!);
    await waitFor(() => expect(rows().length).toBe(8));
  });

  it("套餐筛选 TRIAL → 2 行；组合无结果空态 → 清空筛选恢复；游标分页次页 2 行", async () => {
    renderTenants();
    await waitFor(() => expect(rows().length).toBe(8));

    fireEvent.change(document.querySelector('[data-dom-id="tenants-filter-plan"]')!, {
      target: { value: "TRIAL" },
    });
    await waitFor(() => expect(rows().length).toBe(2));
    expect(screen.getByText("套餐：体验版")).toBeInTheDocument();

    // 组合 CANCELLED + TRIAL → 无结果 → 空态三件套
    fireEvent.change(document.querySelector('[data-dom-id="tenants-filter-status"]')!, {
      target: { value: "CANCELLED" },
    });
    await waitFor(() => expect(document.querySelector('[data-dom-id="tenants-empty"]')).not.toBeNull());
    expect(screen.getByText("未找到租户")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "清空筛选" }));
    await waitFor(() => expect(rows().length).toBe(8));

    const nextBtn = document.querySelector('[data-dom-id="pagination-next"]') as HTMLButtonElement;
    await waitFor(() => expect(nextBtn.disabled).toBe(false));
    fireEvent.click(nextBtn);
    await waitFor(() => expect(rows().length).toBe(2));
    expect(document.querySelector('[data-dom-id="pagination-range"]')!.textContent).toContain("共 10 条");

    fireEvent.click(document.querySelector('[data-dom-id="pagination-prev"]')!);
    await waitFor(() => expect(rows().length).toBe(8));
  });

  it("新建租户：无编码输入（自动生成）+ 提交请求体断言 + 临时口令展示；409 行内错误", async () => {
    let createBody: Record<string, unknown> | undefined;
    server.use(
      http.post("*/api/v1/tenants", async ({ request }) => {
        createBody = (await request.json()) as Record<string, unknown>;
        if (createBody?.name === "冲突租户") {
          return HttpResponse.json(
            { error: { code: "CONFLICT", message: "创建冲突", request_id: "mock" } },
            { status: 409 },
          );
        }
        return HttpResponse.json(
          {
            tenant_id: "00000000-0000-4000-8000-000000000599",
            slug: `ten-${new Date().getFullYear()}-0007`,
            name: createBody?.name ?? "",
            status: "ACTIVE",
            created_at: "2026-09-28T08:00:00.000Z",
            initial_admin_user_id: "00000000-0000-0000-0000-000000000009",
            temporary_password: "Tmp-9k2f-Xq7b",
          },
          { status: 201 },
        );
      }),
    );
    renderTenants();
    await waitFor(() => expect(rows().length).toBe(8));

    fireEvent.click(document.querySelector('[data-dom-id="tenant-create"]')!);
    await waitFor(() => expect(document.querySelector('[data-dom-id="tenant-create-form"]')).not.toBeNull());

    // 编码输入框已移除（服务端自动生成 ten-YYYY-NNNN）
    expect(document.querySelector('[data-dom-id="tenant-slug"]')).toBeNull();

    fireEvent.change(document.querySelector('[data-dom-id="tenant-name"]')!, {
      target: { value: "试点租户" },
    });
    fireEvent.click(document.querySelector('[data-dom-id="tenant-plan-PREMIUM"]')!);
    fireEvent.change(document.querySelector('[data-dom-id="tenant-admin-username"]')!, {
      target: { value: "pilot-admin" },
    });
    fireEvent.change(document.querySelector('[data-dom-id="tenant-admin-email"]')!, {
      target: { value: "admin@pilot.example.com" },
    });
    fireEvent.change(document.querySelector('[data-dom-id="tenant-admin-display"]')!, {
      target: { value: "试点管理员" },
    });
    // 初始口令留空 → 服务端生成临时口令
    fireEvent.click(document.querySelector('[data-dom-id="modal-form-submit"]')!);

    await waitFor(() => expect(createBody).toBeDefined());
    expect(createBody).toEqual({
      name: "试点租户",
      plan: "PREMIUM",
      admin: {
        username: "pilot-admin",
        email: "admin@pilot.example.com",
        display_name: "试点管理员",
      },
    });
    // 201 → 成功页展示自动生成编码 + 一次性临时口令展示行
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="tenant-create-success"]')).not.toBeNull(),
    );
    expect(document.querySelector('[data-dom-id="tenant-create-success"]')!.textContent).toContain(
      `ten-${new Date().getFullYear()}-0007`,
    );
    expect(document.querySelector('[data-dom-id="temp-password-value"]')!.textContent).toBe("Tmp-9k2f-Xq7b");
    expect(screen.getByText(/仅此一次可见/)).toBeInTheDocument();
    fireEvent.click(document.querySelector('[data-dom-id="modal-form-submit"]')!); // 完成 → 关闭

    // 再开一次：服务端 409 → 行内错误提示
    fireEvent.click(document.querySelector('[data-dom-id="tenant-create"]')!);
    await waitFor(() => expect(document.querySelector('[data-dom-id="tenant-create-form"]')).not.toBeNull());
    fireEvent.change(document.querySelector('[data-dom-id="tenant-name"]')!, {
      target: { value: "冲突租户" },
    });
    fireEvent.change(document.querySelector('[data-dom-id="tenant-admin-username"]')!, {
      target: { value: "admin2" },
    });
    fireEvent.change(document.querySelector('[data-dom-id="tenant-admin-email"]')!, {
      target: { value: "admin2@example.com" },
    });
    fireEvent.change(document.querySelector('[data-dom-id="tenant-admin-display"]')!, {
      target: { value: "二号管理员" },
    });
    fireEvent.click(document.querySelector('[data-dom-id="modal-form-submit"]')!);
    await waitFor(() => expect(document.querySelector('[data-dom-id="tenant-create-error"]')).not.toBeNull());
    expect(document.querySelector('[data-dom-id="tenant-create-error"]')!.textContent).toContain(
      "创建冲突",
    );
  });

  it("切换租户：context 调用 → token 替换 → queryClient.clear → toast 已切换", async () => {
    const queryClient = renderTenants();
    await waitFor(() => expect(rows().length).toBe(8));
    const clearSpy = vi.spyOn(queryClient, "clear");

    let contextTenantId = "";
    server.use(
      http.post("*/api/v1/tenants/:tenantId/context", ({ params }) => {
        contextTenantId = String(params.tenantId);
        return HttpResponse.json({
          tenant_id: contextTenantId,
          access_token: "mock-access-ctx-acme",
          note: "token 已按目标租户上下文重签",
          switched_at: "2026-09-28T09:00:00.000Z",
        });
      }),
    );

    fireEvent.click(document.querySelector('[data-dom-id="tenants-switch"]')!);
    await waitFor(() =>
      expect(document.querySelectorAll('[data-dom-id^="tenant-option-"]').length).toBeGreaterThanOrEqual(2),
    );
    // 仅 ACTIVE：清单不含 SUSPENDED/CANCELLED 租户
    expect(document.querySelector('[data-dom-id="tenant-option-mfg-pilot"]')).toBeNull();
    expect(document.querySelector('[data-dom-id="tenant-option-legacy-erp"]')).toBeNull();

    fireEvent.click(document.querySelector('[data-dom-id="tenant-option-acme"]')!);
    fireEvent.click(document.querySelector('[data-dom-id="tenant-switch-confirm"]')!);

    await waitFor(() => expect(contextTenantId).toBe(TENANT_ACME_ID));
    await waitFor(() => expect(useSessionStore.getState().accessToken).toBe("mock-access-ctx-acme"));
    expect(useSessionStore.getState().tenant?.slug).toBe("acme");
    expect(useSessionStore.getState().tenant?.name).toBe("ACME · 华东事业群");
    await waitFor(() => expect(clearSpy).toHaveBeenCalled());
    expect(await screen.findByText("已切换")).toBeInTheDocument();
  });
});
