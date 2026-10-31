import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

function renderTools() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: ["/admin/tools"] });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

function fieldInput(key: string): HTMLInputElement {
  return document.querySelector(`[data-dom-id="tools-field-${key}"] input`) as HTMLInputElement;
}

function submit() {
  fireEvent.click(screen.getByRole("button", { name: /执行试查/ }));
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(() => {
  useSessionStore.getState().setSession(sessionOf("analyst1", ["ANALYST"]));
});

/**
 * T12 工具页（EDP-503）：六接口 chips + 试查表单动态字段 + JSON 只读呈现 +
 * evidence_hint 行 + 404 按 13.9.2 errorSpec 呈现（fixtures：mocks/data/tools.ts）。
 */
describe("ToolsPage 六接口在线试查（MSW 模式渲染路由）", () => {
  it("页头六 chips + 默认订单详情接口渲染 order_no 字段", async () => {
    renderTools();

    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="tools-page"]')).not.toBeNull(),
    );
    expect(document.querySelectorAll('[data-dom-id^="tools-chip-"]').length).toBe(6);
    expect(document.querySelector('[data-dom-id="tools-field-order_no"]')).not.toBeNull();
    expect(document.querySelector('[data-dom-id="tools-interface"]')!.textContent).toContain("订单详情");
  });

  it("接口切换 → 查询键字段随之变化（订单 order_no → 库存 material_code）", async () => {
    renderTools();
    await waitFor(() => expect(fieldInput("order_no")).not.toBeNull());

    fireEvent.change(document.querySelector('[data-dom-id="tools-interface"]')!, {
      target: { value: "inventory" },
    });

    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="tools-field-material_code"]')).not.toBeNull(),
    );
    expect(document.querySelector('[data-dom-id="tools-field-order_no"]')).toBeNull();
    expect(fieldInput("material_code").placeholder).toContain("X-100");

    // 采购单接口为双可选键（material_code + status）
    fireEvent.change(document.querySelector('[data-dom-id="tools-interface"]')!, {
      target: { value: "purchase_orders" },
    });
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="tools-field-status"]')).not.toBeNull(),
    );
  });

  it("订单试查 → 只读 JSON 渲染 + evidence_hint 证据行（obj 短 ID 文本）", async () => {
    renderTools();
    await waitFor(() => expect(fieldInput("order_no")).not.toBeNull());

    fireEvent.change(fieldInput("order_no"), { target: { value: "SO-2026-00123" } });
    submit();

    const pre = await waitFor(() => {
      const el = document.querySelector('[data-dom-id="tools-result-json"]');
      expect(el).not.toBeNull();
      return el!;
    });
    expect(pre.textContent).toContain("SO-2026-00123");
    expect(pre.textContent).toContain("120000");
    // 证据行：evidence_hint.object_id → 订单 B（mockUuid(102) 尾 8 = 00000102）
    const evidences = document.querySelectorAll('[data-dom-id="tools-evidence-row"]');
    expect(evidences.length).toBe(1);
    expect(evidences[0].textContent).toContain("obj-00000102");
    // 证据页暂无 focus 定位参数 → 行内仅文本（无跳转链接）
    expect(evidences[0].querySelector("a")).toBeNull();
    // 复制按钮随结果呈现
    expect(document.querySelector('[data-dom-id="tools-copy"]')).not.toBeNull();
  });

  it("对象不存在 → 404 NOT_FOUND 按 13.9.2 呈现「资源不存在」", async () => {
    renderTools();
    await waitFor(() => expect(fieldInput("order_no")).not.toBeNull());

    fireEvent.change(fieldInput("order_no"), { target: { value: "SO-4040-NONE" } });
    submit();

    const errorBox = await waitFor(() => {
      const el = document.querySelector('[data-dom-id="tools-error"]');
      expect(el).not.toBeNull();
      return el!;
    });
    expect(errorBox.textContent).toContain("NOT_FOUND");
    expect(errorBox.textContent).toContain("资源不存在");
    expect(document.querySelector('[data-dom-id="tools-result"]')).toBeNull();
  });

  it("供应商交期试查（必填 supplier_code）→ 行级 lead_times 渲染", async () => {
    renderTools();
    fireEvent.change(document.querySelector('[data-dom-id="tools-interface"]')!, {
      target: { value: "supplier_lead_times" },
    });
    await waitFor(() => expect(fieldInput("supplier_code")).not.toBeNull());

    fireEvent.change(fieldInput("supplier_code"), { target: { value: "S-118" } });
    submit();

    const pre = await waitFor(() => {
      const el = document.querySelector('[data-dom-id="tools-result-json"]');
      expect(el).not.toBeNull();
      return el!;
    });
    expect(pre.textContent).toContain("lead_time_days");
    expect(pre.textContent).toContain("14");
    expect(document.querySelectorAll('[data-dom-id="tools-evidence-row"]').length).toBe(1);
  });
});
