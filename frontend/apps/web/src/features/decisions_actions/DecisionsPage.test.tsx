import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { ThemeProvider } from "../../app/providers/ThemeProvider";
import { routes } from "../../app/router";
import { useSessionStore, type AuthTokenResponse } from "../auth/session-store";
import { CASE_H_COMBINED } from "../../mocks/data/cases";
import { markCaseDecided, resetDecisionMocks } from "../../mocks/handlers/decisions";
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

function renderDecisions() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: ["/decisions"] });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

const rows = () => document.querySelectorAll('[data-dom-id^="decisions-row-"]');

/** 打开首行（fixtures：P0 订单 H 案例 DC-20260928-008）审批表单。 */
async function openFirstForm() {
  fireEvent.click(document.querySelector('[data-dom-id^="decisions-approve-"]')!);
  await waitFor(() =>
    expect(document.querySelector('[data-dom-id="decision-form"]')).not.toBeNull(),
  );
}

function submitForm() {
  fireEvent.click(screen.getByRole("button", { name: /提交决策/ }));
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  resetDecisionMocks();
});
afterAll(() => server.close());
beforeEach(() => {
  useSessionStore.getState().setSession(sessionOf("manager1", ["MANAGER"]));
});

/**
 * fixtures 锚定（mocks/data/cases.ts）：OPEN 20 条 = 故事 4（H P0 / E J P1 / C P2）
 * + 例行 16；pending 排序 risk（P0 优先）+ created_at ASC → 首行 = 订单 H。
 */
describe("DecisionsPage 待决列表与决策表单（MSW 模式渲染路由）", () => {
  it("表格渲染 20 行；头部「待决 20」角徽（total_pending）首行为 P0 订单 H", async () => {
    renderDecisions();

    await waitFor(() => expect(rows().length).toBe(20));
    expect(document.querySelector('[data-dom-id="decisions-table"]')).not.toBeNull();
    const badge = document.querySelector('[data-dom-id="decisions-pending-badge"]')!;
    expect(badge.textContent).toContain("待决 20");
    expect(rows()[0].textContent).toContain("DC-20260928-008");
  });

  it("total_pending=0 → 角徽隐藏 + 空态三件套", async () => {
    server.use(
      http.get("*/api/v1/ebms/decisions/pending", () =>
        HttpResponse.json({ items: [], total_pending: 0 }),
      ),
    );
    renderDecisions();

    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="decisions-empty"]')).not.toBeNull(),
    );
    expect(screen.getByText("暂无待决案例")).toBeInTheDocument();
    expect(document.querySelector('[data-dom-id="decisions-pending-badge"]')).toBeNull();
  });

  it("表单选项 radio 渲染（key+label）+ Human-Only 人形图标与 tooltip；提交 → 决策已提交 + 案例移出待决", async () => {
    // override 响应体捕获请求字段，复用 markCaseDecided 保持默认 handler 的待决移除语义
    const bodies: Record<string, unknown>[] = [];
    server.use(
      http.post("*/api/v1/decisions/cases/:caseId/records", async ({ request }) => {
        bodies.push((await request.json()) as Record<string, unknown>);
        markCaseDecided(CASE_H_COMBINED);
        return HttpResponse.json(
          {
            case_id: CASE_H_COMBINED,
            decision_id: "00000000-0000-4000-8000-000000000819",
            case_status: "DECIDED",
            decision_time: "2026-09-28T08:30:00.000Z",
          },
          { status: 201 },
        );
      }),
    );
    renderDecisions();
    await waitFor(() => expect(rows().length).toBe(20));

    await openFirstForm();
    // 选项 radio = case.options（H 案例为通用三选项 CONFIRM/ADJUST/REJECT）
    expect(screen.getByLabelText("确认执行（CONFIRM）")).toBeInTheDocument();
    expect(screen.getByLabelText("调整方案（ADJUST）")).toBeInTheDocument();
    expect(screen.getByLabelText("拒绝建议（REJECT）")).toBeInTheDocument();
    // Human-Only 人形图标 + tooltip「仅人工可执行」
    expect(screen.getByTitle("仅人工可执行")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("确认执行（CONFIRM）"));
    fireEvent.change(document.querySelector('[data-dom-id="decision-form-comment"]')!, {
      target: { value: "先确认执行，同步通知采购" },
    });
    submitForm();

    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toEqual({
      chosen_option: "CONFIRM",
      comment: "先确认执行，同步通知采购",
      decision_type: "HUMAN",
    });
    expect(await screen.findByText("决策已提交")).toBeInTheDocument();
    // 列表刷新：已决策案例移出待决（20 → 19）
    await waitFor(() => expect(rows().length).toBe(19));
    expect(document.querySelector('[data-dom-id="decision-form"]')).toBeNull();
  });

  it("403 GUARD_POLICY_DENIED → 13.9.2 逐字文案「该操作仅限人工执行」且表单保持打开", async () => {
    server.use(
      http.post("*/api/v1/decisions/cases/*/records", () =>
        HttpResponse.json(
          { error: { code: "GUARD_POLICY_DENIED", message: "策略拒绝该操作", request_id: "mock" } },
          { status: 403 },
        ),
      ),
    );
    renderDecisions();
    await waitFor(() => expect(rows().length).toBe(20));

    await openFirstForm();
    fireEvent.click(screen.getByLabelText("确认执行（CONFIRM）"));
    submitForm();

    expect(await screen.findByText("该操作仅限人工执行")).toBeInTheDocument();
    expect(document.querySelector('[data-dom-id="decision-form"]')).not.toBeNull();
  });

  it("空选项提交 → 行内「请选择一个选项」", async () => {
    renderDecisions();
    await waitFor(() => expect(rows().length).toBe(20));

    await openFirstForm();
    submitForm();

    expect(await screen.findByText("请选择一个选项")).toBeInTheDocument();
    expect(document.querySelector('[data-dom-id="decision-form"]')).not.toBeNull();
  });
});
