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

function renderMemory() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: ["/admin/memory"] });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

const rows = () => document.querySelectorAll('[data-dom-id^="memory-row-"]');

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(() => {
  useSessionStore.getState().setSession(sessionOf("analyst1", ["ANALYST"]));
});

/**
 * T12 记忆页（EDP-503，只读）：筛选 chips + 三态 status pill + 无审批操作按钮
 * （评审由 Agent 中枢接管 W6）+ 行展开 content 全文（fixtures：mocks/data/memory.ts）。
 */
describe("MemoryPage 候选记忆只读检索（MSW 模式渲染路由）", () => {
  it("默认列表 5 条 + 三态 status pill（CANDIDATE/APPROVED/REJECTED）+ 页头 W6 留痕", async () => {
    renderMemory();

    await waitFor(() => expect(rows().length).toBe(5));
    const texts = Array.from(rows()).map((r) => r.textContent!);
    expect(texts.some((t) => t.includes("CANDIDATE"))).toBe(true);
    expect(texts.some((t) => t.includes("APPROVED"))).toBe(true);
    expect(texts.some((t) => t.includes("REJECTED"))).toBe(true);
    // 首行为最新 created_at（订单 B 缺口候选，hoursBefore(6)）
    expect(rows()[0].textContent).toContain("SO-2026-00123");
    expect(document.querySelector('[data-dom-id="memory-page"]')!.textContent).toContain(
      "评审操作由 Agent 中枢接管（W6）",
    );
  });

  it("无审批操作按钮（评审 W6 接管）", async () => {
    renderMemory();
    await waitFor(() => expect(rows().length).toBe(5));

    // 表格内仅允许 MonoId 复制按钮（只读），无任何审批/操作按钮（分页导航在表外）
    const tableButtons = Array.from(
      document.querySelector('[data-dom-id="memory-table"]')!.querySelectorAll("button"),
    );
    expect(tableButtons.length).toBeGreaterThan(0);
    expect(tableButtons.every((b) => b.getAttribute("data-dom-id") === "mono-id-copy")).toBe(true);
    // 精确名匹配：不存在审批动作按钮（全名匹配，不与「已采纳 APPROVED」等筛选 chip 冲突）
    for (const name of ["采纳", "通过", "驳回", "拒绝", "评审", "APPROVE", "REJECT"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
  });

  it("status 筛选 chips：CANDIDATE → 3 条；REJECTED → 1 条", async () => {
    renderMemory();
    await waitFor(() => expect(rows().length).toBe(5));

    fireEvent.click(document.querySelector('[data-dom-id="memory-status-CANDIDATE"]')!);
    await waitFor(() => expect(rows().length).toBe(3));
    expect(
      Array.from(rows()).every((r) => r.textContent!.includes("CANDIDATE")),
    ).toBe(true);

    fireEvent.click(document.querySelector('[data-dom-id="memory-status-REJECTED"]')!);
    await waitFor(() => expect(rows().length).toBe(1));
  });

  it("capability 筛选 chips：数据质量检查 → 1 条（已采纳双记录合并记忆）", async () => {
    renderMemory();
    await waitFor(() => expect(rows().length).toBe(5));

    fireEvent.click(document.querySelector('[data-dom-id="memory-capability-00000000-0000-4000-8000-000000000803"]')!);
    await waitFor(() => expect(rows().length).toBe(1));
    expect(rows()[0].textContent).toContain("APPROVED");
  });

  // T9（W5-13 收敛）：chips 来自 GET /capabilities 接口——第四能力（无轨迹fixtures）chip 渲染且筛选落空态
  it("capability chips 来自 capabilities 接口：第四能力 chip 渲染 + 筛选空态", async () => {
    renderMemory();
    await waitFor(() => expect(rows().length).toBe(5));

    const fourthChip = await waitFor(() => {
      const el = document.querySelector(
        '[data-dom-id="memory-capability-00000000-0000-4000-8000-000000000804"]',
      );
      expect(el).not.toBeNull();
      return el!;
    });
    expect(fourthChip.textContent).toBe("供应商延期监控");

    fireEvent.click(fourthChip);
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="memory-empty"]')).not.toBeNull(),
    );
  });

  it("行点击展开只读详情：content 全文 JSON + 来源/评审信息；再点收起", async () => {
    renderMemory();
    await waitFor(() => expect(rows().length).toBe(5));

    fireEvent.click(rows()[0]);
    const detail = await waitFor(() => {
      const el = document.querySelector('[data-dom-id^="memory-detail-"]');
      expect(el).not.toBeNull();
      return el!;
    });
    // content 全文（JSON 序列化呈现，含 summary 与建议动作键）
    expect(detail.textContent).toContain("suggested_action");
    expect(detail.textContent).toContain("催货 PO-2026-00771");
    // 来源类型（TRACE）+ 评审信息未评审回退 —
    expect(detail.textContent).toContain("TRACE");
    expect(detail.textContent).toContain("—");

    fireEvent.click(rows()[0]);
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id^="memory-detail-"]')).toBeNull(),
    );
  });

  it("筛选无匹配 → 空态 + 文案留痕（评审 W6 接管）", async () => {
    renderMemory();
    await waitFor(() => expect(rows().length).toBe(5));

    fireEvent.click(document.querySelector('[data-dom-id="memory-status-REJECTED"]')!);
    await waitFor(() => expect(rows().length).toBe(1));

    // REJECTED（订单风险评估能力）∩ 产品就绪度能力 → 无匹配
    fireEvent.click(document.querySelector('[data-dom-id="memory-capability-00000000-0000-4000-8000-000000000802"]')!);
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="memory-empty"]')).not.toBeNull(),
    );
    expect(screen.getByText("暂无候选记忆")).toBeInTheDocument();
  });
});
