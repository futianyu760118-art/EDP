import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

function paginationText(): string {
  return document.querySelector('[data-dom-id="pagination-range"]')?.textContent ?? "";
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(() => {
  useSessionStore.getState().setSession(sessionOf("manager1", ["MANAGER"]));
});

/**
 * fixtures 锚定（mocks/data）：23 对象按 updated_at DESC（B 2h/E 3h/H 4h 先列，
 * 其余 6h 平手按 object_id DESC）→ 第 1 页 20 条含 B/E/H/…/J（第 17 位），第 2 页
 * 3 条（R1/C/A）。能力结果事件派生：P1×3（B=order_risk、E=order_quality、
 * J=order_risk）→ At Risk；P0×1（H）→ Blocking；DQ×1（I）→ DQ Exception；
 * P2/P3×4（A/C/G/PRJD）→ Watch；其余 14 无信号 → Healthy。
 */
describe("RegistryPage 列表主体（MSW 模式渲染路由）", () => {
  it("23 个 fixtures 对象跨两页渲染：首页 20 卡 + 下一页 3 卡 + 分页文案", async () => {
    renderRegistry();

    await waitFor(() => expect(cards().length).toBe(20));
    expect(paginationText()).toBe("显示 1–20 条，共 23 条");
    // 订单 I（钉住 dq 索引链路）；限定卡片区，排除状态下拉的 option 文本
    const grid = document.querySelector('[data-dom-id="objects-grid"]') as HTMLElement;
    expect(within(grid).getAllByText("DQ Exception")).toHaveLength(1);
    expect(document.querySelector('[data-dom-id="pagination-page"]')?.textContent).toBe("1");

    fireEvent.click(document.querySelector('[data-dom-id="pagination-next"]')!);
    await waitFor(() => expect(cards().length).toBe(3));
    expect(paginationText()).toBe("显示 21–23 条，共 23 条");
    expect(
      (document.querySelector('[data-dom-id="pagination-next"]') as HTMLButtonElement).disabled,
    ).toBe(true);

    fireEvent.click(document.querySelector('[data-dom-id="pagination-prev"]')!);
    await waitFor(() => expect(cards().length).toBe(20));
    expect(paginationText()).toBe("显示 1–20 条，共 23 条");
  });

  it("搜索 SO-2026-00123 → 仅 1 卡（source_id 精确匹配，前端过滤当前页）", async () => {
    renderRegistry();

    await waitFor(() => expect(cards().length).toBe(20));
    fireEvent.change(document.querySelector('[data-dom-id="objects-search"]')!, {
      target: { value: "SO-2026-00123" },
    });

    await waitFor(() => expect(cards().length).toBe(1));
    expect(screen.getByText("订单 B · 关键料缺失")).toBeInTheDocument();
    expect(paginationText()).toBe("显示 1–1 条，共 1 条");
  });

  it("状态选 At Risk → 仅 3 个 P1 派生对象（B/E/J，均在首页结果集内）", async () => {
    renderRegistry();

    await waitFor(() => expect(cards().length).toBe(20));
    fireEvent.change(document.querySelector('[data-dom-id="objects-status"]')!, {
      target: { value: "At Risk" },
    });

    await waitFor(() => expect(cards().length).toBe(3));
    expect(screen.getByText("订单 B · 关键料缺失")).toBeInTheDocument();
    expect(screen.getByText("订单 E · 高值低库存")).toBeInTheDocument();
    expect(screen.getByText("订单 J · 供应商交叉")).toBeInTheDocument();
    expect(paginationText()).toBe("显示 1–3 条，共 3 条");
  });

  it("表格视图：9 列列头 + 首页 20 行 + 行内状态 pill", async () => {
    renderRegistry();

    await waitFor(() => expect(cards().length).toBe(20));
    fireEvent.click(screen.getByRole("button", { name: "表格" }));

    const table = (await waitFor(() => {
      const el = document.querySelector('[data-dom-id="objects-table"]');
      expect(el).not.toBeNull();
      return el as HTMLElement;
    }))!;
    for (const h of ["对象", "类型", "名称", "域", "来源", "状态", "Rev", "更新时间", "操作"]) {
      expect(within(table).getByText(h)).toBeInTheDocument();
    }
    await waitFor(() =>
      expect(table.querySelectorAll('[data-dom-id="object-row"]')).toHaveLength(20),
    );
    expect(within(table).getAllByText("Blocking")).toHaveLength(1); // ORDER_H（P0）
  });

  it("域选 Sales → 后端 owner_domain 过滤：10 卡 + 单页共 10 条 + 可移除 chip", async () => {
    renderRegistry();

    await waitFor(() => expect(cards().length).toBe(20));
    fireEvent.change(document.querySelector('[data-dom-id="objects-domain"]')!, {
      target: { value: "sales" },
    });

    await waitFor(() => expect(cards().length).toBe(10));
    expect(paginationText()).toBe("显示 1–10 条，共 10 条");
    expect(screen.getByText("域：Sales")).toBeInTheDocument();

    fireEvent.click(document.querySelector('[data-dom-id="chip-remove-domain"]')!);
    await waitFor(() => expect(cards().length).toBe(20));
    expect(paginationText()).toBe("显示 1–20 条，共 23 条");
  });

  it("无匹配 → 空态（未找到业务对象 + 双按钮）→ 清空筛选恢复 23 条", async () => {
    renderRegistry();

    await waitFor(() => expect(cards().length).toBe(20));
    fireEvent.change(document.querySelector('[data-dom-id="objects-search"]')!, {
      target: { value: "NO-SUCH-ID" },
    });

    expect(await screen.findByText("未找到业务对象")).toBeInTheDocument();
    expect(
      screen.getByText("当前搜索条件没有匹配结果，请调整筛选条件或新建对象。"),
    ).toBeInTheDocument();
    expect(screen.getByText("新建对象")).toBeInTheDocument();

    fireEvent.click(document.querySelector('[data-dom-id="empty-secondary-action"]')!);
    await waitFor(() => expect(cards().length).toBe(20));
    expect(paginationText()).toBe("显示 1–20 条，共 23 条");
    fireEvent.click(document.querySelector('[data-dom-id="pagination-next"]')!);
    await waitFor(() => expect(cards().length).toBe(3));
  });
});
