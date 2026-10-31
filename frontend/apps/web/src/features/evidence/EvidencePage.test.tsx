import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "../../app/providers/ThemeProvider";
import { routes } from "../../app/router";
import { useSessionStore, type AuthTokenResponse } from "../auth/session-store";
import { evidence } from "../../mocks/data/evidence";
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

function renderEvidence() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: ["/admin/evidence"] });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

const cards = () => document.querySelectorAll('[data-dom-id^="evidence-card-"]');
const chain = () => document.querySelector('[data-dom-id="evidence-chain"]');
const chainEmpty = () => document.querySelector('[data-dom-id="evidence-chain-empty"]');
const summary = () =>
  document.querySelector('[data-dom-id="chain-verify-summary"]')?.textContent ?? "";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  vi.unstubAllEnvs();
});
afterAll(() => server.close());
beforeEach(() => {
  useSessionStore.getState().setSession(sessionOf("manager1", ["MANAGER"]));
});

describe("EvidencePage 证据库（MSW 模式渲染路由）", () => {
  it("KPI 带 + 列表渲染 fixtures 全量；未选中时链图空态", async () => {
    renderEvidence();

    const band = await waitFor(() => {
      const el = document.querySelector('[data-dom-id="evidence-kpi-band"]');
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });
    expect(band.textContent).toContain("证据数量");
    await waitFor(() => expect(band.textContent).toContain(String(evidence.length)));
    await waitFor(() => expect(band.textContent).toContain("100.00%")); // evidence_valid_rate=100（mock 扩展）

    await waitFor(() => expect(cards().length).toBe(evidence.length));
    expect(chainEmpty()).not.toBeNull();
    expect(chain()).toBeNull();
  });

  it("选中证据 → 链图节点与链上校验计数；verify 点击后状态 pill 切换", async () => {
    renderEvidence();
    await waitFor(() => expect(cards().length).toBe(evidence.length));

    // 订单 B 快照（CASE link，Derived）→ 同对象仅 1 份证据
    const target = evidence[0];
    fireEvent.click(document.querySelector(`[data-dom-id="evidence-card-${target.evidence_id}"]`)!);

    await waitFor(() => expect(chain()).not.toBeNull());
    expect(chain()!.textContent).toContain(target.source_record_id);
    expect(chain()!.textContent).toContain("业务对象");
    // 同对象证据数（订单 B：快照 + 例行快照 = 2）——链节点随对象证据查询到达
    const nodeCount = evidence.filter((item) => item.object_id === target.object_id).length;
    await waitFor(() => expect(summary()).toContain(`已校验 0/${nodeCount} 份`));

    fireEvent.click(document.querySelector('[data-dom-id="evidence-verify-btn"]')!);
    await waitFor(() => expect(summary()).toContain(`已校验 1/${nodeCount} 份`));
    // 列表卡状态 pill 即时切换为 VALID（链图节点以 ✓ 图标呈现）
    await waitFor(() =>
      expect(
        document.querySelector(`[data-dom-id="evidence-card-${target.evidence_id}"]`)!.textContent,
      ).toContain("VALID"),
    );
  });

  it("卡内搜索：命中过滤、无结果空态含建议替代关键词", async () => {
    renderEvidence();
    await waitFor(() => expect(cards().length).toBe(evidence.length));

    const input = document.querySelector('[data-dom-id="evidence-search"]') as HTMLInputElement;
    fireEvent.change(input, { target: { value: "SO-2026-00123" } });
    await waitFor(() => expect(cards().length).toBe(1));
    expect(cards()[0].textContent).toContain("SO-2026-00123");

    fireEvent.change(input, { target: { value: "no-such-record" } });
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="evidence-empty"]')).not.toBeNull(),
    );
    expect(screen.getByText(/建议尝试更短的关键词/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "清空筛选" }));
    await waitFor(() => expect(cards().length).toBe(evidence.length));
  });

  it("重建索引按钮真模式直接可用（T6 端点已交付）", async () => {
    renderEvidence();

    const button = await waitFor(() => {
      const el = document.querySelector('[data-dom-id="evidence-reindex-btn"]');
      expect(el).not.toBeNull();
      return el as HTMLButtonElement;
    });
    expect(button.disabled).toBe(false);
  });
});
