import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { ThemeProvider } from "../../app/providers/ThemeProvider";
import { routes } from "../../app/router";
import { useSessionStore, type AuthTokenResponse } from "../auth/session-store";
import { allowedToOf, actionRows } from "../../mocks/data/actions";
import { ACTION_B_EXPEDITE } from "../../mocks/data/cases";
import { CASE_ORDER_B } from "../../mocks/data/ids";
import { resetActionsMock } from "../../mocks/handlers/actions";
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

function renderActions(entry = "/actions") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: [entry] });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

const rows = () => document.querySelectorAll('[data-dom-id^="actions-row-"]');

const rowB = () => actionRows.find((row) => row.action_id === ACTION_B_EXPEDITE)!;

/** 打开订单 B 主线行动（APPROVED）详情抽屉。 */
async function openDrawerB() {
  fireEvent.click(document.querySelector(`[data-dom-id="actions-row-${ACTION_B_EXPEDITE}"]`)!);
  await waitFor(() =>
    expect(document.querySelector('[data-dom-id="action-drawer"]')).not.toBeNull(),
  );
  await waitFor(() =>
    expect(document.querySelector('[data-dom-id="state-machine"]')).not.toBeNull(),
  );
}

/** 转移确认小弹窗：点击 allowed_to 按钮 → 确认转移。 */
async function confirmTransition(toStatus: string) {
  fireEvent.click(document.querySelector(`[data-dom-id="transition-btn-${toStatus}"]`)!);
  await waitFor(() =>
    expect(document.querySelector('[data-dom-id="transition-modal"]')).not.toBeNull(),
  );
  fireEvent.click(screen.getByRole("button", { name: /确认转移/ }));
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  resetActionsMock();
});
afterAll(() => server.close());
beforeEach(() => {
  useSessionStore.getState().setSession(sessionOf("manager1", ["MANAGER"]));
});

/**
 * fixtures 锚定（mocks/data/actions.ts）：8 条行动（订单 B 主线 APPROVED +
 * 7 条铺 9 态/筛选基数）；created_at DESC 首行 = 加急采购物料X。
 */
describe("ActionsPage 行动列表（MSW 模式渲染路由）", () => {
  it("表格渲染 8 行 + 总数千分位；status/owner 筛选生效", async () => {
    renderActions();
    await waitFor(() => expect(rows().length).toBe(8));
    expect(rows()[0].textContent).toContain("加急采购物料X");
    expect(document.querySelector('[data-dom-id="pagination-range"]')!.textContent).toContain("共 8 条");

    fireEvent.change(document.querySelector('[data-dom-id="actions-filter-status"]')!, {
      target: { value: "EXECUTING" },
    });
    await waitFor(() => expect(rows().length).toBe(1));
    expect(rows()[0].textContent).toContain("核查在途 PO-2026-00771 到货窗口");

    fireEvent.change(document.querySelector('[data-dom-id="actions-filter-status"]')!, {
      target: { value: "" },
    });
    await waitFor(() => expect(rows().length).toBe(8));
    fireEvent.change(document.querySelector('[data-dom-id="actions-filter-owner"]')!, {
      target: { value: "user:purchasing_li" },
    });
    await waitFor(() => expect(rows().length).toBe(2));
  });

  it("?case_id= 初始筛选（T9 行动卡跳转落地）→ 单行 + 案例短 ID chip 可移除", async () => {
    renderActions(`/actions?case_id=${CASE_ORDER_B}`);
    await waitFor(() => expect(rows().length).toBe(1));
    expect(rows()[0].textContent).toContain("加急采购物料X");

    fireEvent.click(document.querySelector('[data-dom-id="actions-filter-case-remove"]')!);
    await waitFor(() => expect(rows().length).toBe(8));
  });
});

describe("ActionDetailDrawer 9 态状态轴与状态机操作（MSW）", () => {
  it("状态轴：当前节点实心（state-current）/ 已走路径（state-walked）/ 未达 muted（state-pending）/ 分支弱化（state-branch）", async () => {
    renderActions();
    await waitFor(() => expect(rows().length).toBe(8));
    await openDrawerB();

    const classOf = (name: string) =>
      document.querySelector(`[data-dom-id="state-node-${name}"]`)!.className;
    // B 行动当前 APPROVED（主线第 4 态）
    expect(classOf("APPROVED")).toContain("state-current");
    expect(classOf("PROPOSED")).toContain("state-walked");
    expect(classOf("ASSIGNED")).toContain("state-walked");
    expect(classOf("EXECUTING")).toContain("state-pending");
    expect(classOf("VERIFIED")).toContain("state-pending");
    // REJECTED/CANCELLED 分支弱化线
    expect(classOf("REJECTED")).toContain("state-branch");
    expect(classOf("CANCELLED")).toContain("state-branch");
    // 已走路径 primary 高亮连线存在
    expect(document.querySelector('[data-dom-id="state-machine"] .state-line-walked')).not.toBeNull();
  });

  it("allowed_to 按钮渲染：APPROVED → EXECUTING（Human-Only 人形图标 + tooltip）与 CANCELLED；转移弹窗提交成功 → 详情刷新", async () => {
    renderActions();
    await waitFor(() => expect(rows().length).toBe(8));
    await openDrawerB();

    const executing = document.querySelector('[data-dom-id="transition-btn-EXECUTING"]') as HTMLElement;
    expect(executing).not.toBeNull();
    expect(executing.getAttribute("title")).toBe("仅人工可执行");
    expect(
      document.querySelector('[data-dom-id="transition-human-only-EXECUTING"]'),
    ).not.toBeNull();
    expect(document.querySelector('[data-dom-id="transition-btn-CANCELLED"]')).not.toBeNull();

    fireEvent.click(executing);
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="transition-modal"]')).not.toBeNull(),
    );
    fireEvent.change(document.querySelector('[data-dom-id="transition-comment"]')!, {
      target: { value: "已联系供应商启动加急" },
    });
    fireEvent.click(screen.getByRole("button", { name: /确认转移/ }));

    // 200 → invalidate 重拉：当前节点推进 EXECUTING，按钮组切换 COMPLETED/CANCELLED
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="state-node-EXECUTING"]')!.className).toContain(
        "state-current",
      ),
    );
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="transition-btn-COMPLETED"]')).not.toBeNull(),
    );
    expect(document.querySelector('[data-dom-id="transition-btn-EXECUTING"]')).toBeNull();
  });

  it("422 INVALID_TRANSITION → toast + 按响应 allowed_to 重渲染按钮组", async () => {
    // 详情首答带「过期」allowed_to（VERIFIED），422 后重拉恢复服务端口径（APPROVED 目录）
    let detailCalls = 0;
    server.use(
      http.get("*/api/v1/actions/:actionId", () => {
        detailCalls += 1;
        const stale = detailCalls <= 1;
        return HttpResponse.json({
          ...rowB(),
          allowed_to: stale
            ? [{ to_status: "VERIFIED", human_only: false }]
            : allowedToOf(rowB().status),
        });
      }),
    );
    renderActions();
    await waitFor(() => expect(rows().length).toBe(8));
    await openDrawerB();

    // 首答（过期目录）：仅 VERIFIED 按钮
    expect(document.querySelector('[data-dom-id="transition-btn-VERIFIED"]')).not.toBeNull();
    expect(document.querySelector('[data-dom-id="transition-btn-EXECUTING"]')).toBeNull();

    // APPROVED→VERIFIED 非法转移 → 422（error.allowed_to = 服务端目录）→ toast + 重拉
    await confirmTransition("VERIFIED");
    expect(await screen.findByText("当前状态不允许该转移，可流转操作已更新")).toBeInTheDocument();
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="transition-btn-VERIFIED"]')).toBeNull(),
    );
    expect(document.querySelector('[data-dom-id="transition-btn-EXECUTING"]')).not.toBeNull();
    expect(document.querySelector('[data-dom-id="transition-btn-CANCELLED"]')).not.toBeNull();
    expect(detailCalls).toBe(2);
  });

  it("409 CONFLICT →「数据已被他人修改，已刷新」逐字 toast + 自动重拉详情（请求计数断言）", async () => {
    // 详情首答为过期状态 PROPOSED（真实行已 APPROVED）：提交 PROPOSED→ASSIGNED 触发 409
    let detailCalls = 0;
    server.use(
      http.get("*/api/v1/actions/:actionId", () => {
        detailCalls += 1;
        const stale = detailCalls <= 1;
        const base = rowB();
        return HttpResponse.json(
          stale
            ? { ...base, status: "PROPOSED", allowed_to: allowedToOf("PROPOSED") }
            : { ...base, allowed_to: allowedToOf(base.status) },
        );
      }),
    );
    renderActions();
    await waitFor(() => expect(rows().length).toBe(8));
    await openDrawerB();

    expect(document.querySelector('[data-dom-id="action-drawer-status"]')!.textContent).toContain(
      "PROPOSED",
    );
    await confirmTransition("ASSIGNED");

    expect(await screen.findByText("数据已被他人修改，已刷新")).toBeInTheDocument();
    // 自动重拉：第二答为真实状态 APPROVED（pill 与状态轴同步回正）
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="action-drawer-status"]')!.textContent).toContain(
        "APPROVED",
      ),
    );
    expect(detailCalls).toBe(2);
  });

  it("终态行动（VERIFIED）→ 无 allowed_to 按钮，当前节点落在主线终点", async () => {
    renderActions();
    await waitFor(() => expect(rows().length).toBe(8));
    // S-030 审计（VERIFIED）：按行文本定位
    const verifiedRow = Array.from(rows()).find((r) =>
      r.textContent?.includes("S-030 供应商替代认证审计"),
    );
    fireEvent.click(verifiedRow!);
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="state-machine"]')).not.toBeNull(),
    );

    expect(document.querySelector('[data-dom-id="action-drawer-status"]')!.textContent).toContain(
      "VERIFIED",
    );
    expect(document.querySelector('[data-dom-id^="transition-btn-"]')).toBeNull();
    expect(screen.getByText("终态，无可流转操作")).toBeInTheDocument();
    expect(document.querySelector('[data-dom-id="state-node-VERIFIED"]')!.className).toContain(
      "state-current",
    );
  });
});
