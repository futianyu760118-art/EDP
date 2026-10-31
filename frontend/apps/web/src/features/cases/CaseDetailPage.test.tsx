import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { ThemeProvider } from "../../app/providers/ThemeProvider";
import { routes } from "../../app/router";
import { useSessionStore, type AuthTokenResponse } from "../auth/session-store";
import {
  CASE_ORDER_B,
  EVID_ORDER_B_INVENTORY,
  EVID_ORDER_B_SNAPSHOT,
  EVT_ORDER_B_RISK,
} from "../../mocks/data/ids";
import { CASE_G_VIP } from "../../mocks/data/cases";
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

function renderDetail(caseId: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: [`/cases/${caseId}`] });
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
 * fixtures 锚定（mocks/data/cases.ts detailB）：5 步时间线（DECISION 与 APPROVED
 * 快照两个 Human-Only 节点）、四层证据链（RESULT 1 / DECISION 1 / EVIDENCE 4 /
 * SOURCE 6）、1 项 APPROVED 行动（allowed_to=EXECUTING+CANCELLED）。
 */
describe("CaseDetailPage 案例详情一屏闭环叙事（MSW 模式渲染路由）", () => {
  it("四区渲染：问题卡（context/选项 radio 只读）/ 证据链四层 / Steps 时间线 / 关联行动卡", async () => {
    renderDetail(CASE_ORDER_B);

    // ① 问题卡
    const question = await waitFor(() => {
      const el = document.querySelector('[data-dom-id="case-detail-question"]');
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });
    expect(question.textContent).toContain("订单 SO-2026-00123 存在缺料风险");
    expect(question.textContent).toContain("订单金额");
    expect(question.textContent).toContain("120,000");
    expect(question.textContent).toContain("物料缺口");
    const radios = question.querySelectorAll("input[type='radio']");
    expect(radios.length).toBe(3);
    expect(Array.from(radios).every((r) => (r as HTMLInputElement).disabled)).toBe(true);
    expect((document.querySelector('[data-dom-id="case-option-EXPEDITE"]') as HTMLInputElement).checked).toBe(true);
    expect((document.querySelector('[data-dom-id="case-option-SUBSTITUTE"]') as HTMLInputElement).checked).toBe(false);

    // ② 证据链四层（RESULT/DECISION/EVIDENCE/SOURCE 各有节点）
    const chain = document.querySelector('[data-dom-id="case-chain"]')!;
    for (const layer of ["RESULT", "DECISION", "EVIDENCE", "SOURCE"]) {
      const group = chain.querySelector(`[data-dom-id="case-chain-layer-${layer}"]`);
      expect(group, `layer ${layer}`).not.toBeNull();
      expect(group!.querySelectorAll('[data-dom-id^="case-chain-node-"]').length).toBeGreaterThan(0);
    }
    expect(
      chain.querySelectorAll('[data-dom-id="case-chain-layer-EVIDENCE"] [data-dom-id^="case-chain-node-"]').length,
    ).toBe(4);

    // ③ Steps 时间线 ≥3 且 Human-Only 人形图标存在
    const steps = document.querySelector('[data-dom-id="case-steps"]')!;
    await waitFor(() =>
      expect(steps.querySelectorAll('[data-dom-id="case-step-item"]').length).toBeGreaterThanOrEqual(3),
    );
    expect(steps.querySelectorAll('[data-dom-id="case-step-human-only"]').length).toBe(2);

    // ④ 关联行动卡
    const actions = document.querySelector('[data-dom-id="case-actions"]')!;
    expect(actions.textContent).toContain("加急采购物料X");
    expect(actions.textContent).toContain("user:purchasing_li");
    expect(actions.querySelectorAll('[data-dom-id="case-action-transition"]').length).toBe(2);
    expect(
      actions.querySelector(`a[href="/actions?case_id=${CASE_ORDER_B}"]`),
    ).not.toBeNull();
  });

  it("证据链 verify：EVIDENCE 节点点击「校验」→ VALID/INVALID pill 即时切换", async () => {
    renderDetail(CASE_ORDER_B);

    const snapNode = await waitFor(() => {
      const el = document.querySelector(`[data-dom-id="case-chain-node-${EVID_ORDER_B_SNAPSHOT}"]`);
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });
    fireEvent.click(snapNode.querySelector('[data-dom-id="case-chain-verify-btn"]')!);
    await waitFor(() =>
      expect(
        document.querySelector(`[data-dom-id="case-chain-node-${EVID_ORDER_B_SNAPSHOT}"] [data-dom-id="case-chain-verify-state"]`)!.textContent,
      ).toBe("VALID"),
    );

    // 覆盖 verify handler → INVALID 分支（篡改检测语义）
    server.use(
      http.get(`*/api/v1/evidence/${EVID_ORDER_B_INVENTORY}/verify`, () =>
        HttpResponse.json({
          evidence_id: EVID_ORDER_B_INVENTORY,
          valid: false,
          verified_at: "2026-09-28T08:30:00.000Z",
        }),
      ),
    );
    const invNode = document.querySelector(`[data-dom-id="case-chain-node-${EVID_ORDER_B_INVENTORY}"]`)!;
    fireEvent.click(invNode.querySelector('[data-dom-id="case-chain-verify-btn"]')!);
    await waitFor(() =>
      expect(
        document.querySelector(`[data-dom-id="case-chain-node-${EVID_ORDER_B_INVENTORY}"] [data-dom-id="case-chain-verify-state"]`)!.textContent,
      ).toBe("INVALID"),
    );
  });

  it("「关联风险」→ 泛化 RiskDrawer 打开（尾 8 短 ID）→ X 关闭", async () => {
    renderDetail(CASE_ORDER_B);

    // 详情就绪（event 到位）后按钮才可用
    const riskBtn = await waitFor(() => {
      const el = document.querySelector('[data-dom-id="case-detail-risk-btn"]') as HTMLButtonElement;
      expect(el).not.toBeNull();
      expect(el.disabled).toBe(false);
      return el;
    });
    fireEvent.click(riskBtn);

    const drawer = await waitFor(() => {
      const el = document.querySelector('[data-dom-id="risk-drawer"]');
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });
    // W3-31 收口：短 ID 统一尾 8；result_type 随事件详情异步到达
    expect(within(drawer).getAllByText(`RSK-${EVT_ORDER_B_RISK.slice(-8)}`).length).toBeGreaterThan(0);
    await waitFor(() => expect(within(drawer).getByText("ORDER_RISK")).toBeInTheDocument());
    await waitFor(() => {
      expect(drawer.querySelector('[data-dom-id="risk-drawer-amount"]')?.textContent).toBe("120,000");
    });

    fireEvent.click(drawer.querySelector('[data-dom-id="risk-drawer-close"]')!);
    await waitFor(() => {
      expect(document.querySelector('[data-dom-id="risk-drawer"]')).toBeNull();
    });
  });

  it("event 缺省案例（已取消 G）：「关联风险」按钮禁用", async () => {
    renderDetail(CASE_G_VIP);

    const button = await waitFor(() => {
      const el = document.querySelector('[data-dom-id="case-detail-risk-btn"]') as HTMLButtonElement;
      expect(el).not.toBeNull();
      return el;
    });
    expect(button.disabled).toBe(true);
  });
});
