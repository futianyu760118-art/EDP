import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { ThemeProvider } from "../../app/providers/ThemeProvider";
import { routes } from "../../app/router";
import { useSessionStore, type AuthTokenResponse } from "../auth/session-store";
import { qualityReport } from "../../mocks/data/quality";
import { server } from "../../mocks/server";

function sessionOf(): AuthTokenResponse {
  return {
    access_token: "t-manager1",
    refresh_token: "r-manager1",
    expires_in: 7200,
    tenant: {
      tenant_id: "00000000-0000-0000-0000-000000000001",
      slug: "default",
      name: "默认租户",
      status: "ACTIVE",
    },
    user: {
      user_id: "00000000-0000-0000-0000-000000000002",
      username: "manager1",
      roles: ["MANAGER"],
      is_platform_admin: false,
    },
  };
}

function renderQuality() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: ["/admin/quality"] });
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
  useSessionStore.getState().setSession(sessionOf());
});

describe("QualityPage 数据质量（真端点形状渲染）", () => {
  it("KPI 四卡（校验通过率文案）+ 四段维度评分 + 异常卡与合并提示", async () => {
    renderQuality();

    const band = await waitFor(() => {
      const el = document.querySelector('[data-dom-id="quality-kpi-band"]');
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });
    // kpi 派生对齐后端 T3 口径：overall=四维均分 99、sla=抽检通过率 99.2、
    // completeness=coverage.overall 96.8、pending=7
    expect(band.textContent).toContain("校验通过率");
    expect(band.textContent).toContain("99%");
    expect(band.textContent).toContain("99.2%");
    expect(band.textContent).toContain("96.8%");
    expect(band.textContent).toContain("7");

    // 四段维度标识（reconciliation/coverage/orphans/checksum）全 success 色
    await waitFor(() =>
      expect(document.querySelectorAll('[data-dom-id^="quality-dim-"]').length).toBe(4),
    );
    expect(
      document.querySelector('[data-dom-id="quality-dim-coverage"]')!.className,
    ).toContain("bg-state-success");

    await waitFor(() =>
      expect(document.querySelectorAll('[data-dom-id^="quality-exception-"]').length).toBe(3),
    );
    expect(document.querySelector('[data-dom-id="quality-merged"]')!.textContent).toContain(
      "剩余 4 项异常",
    );
  });

  it("重校验弹窗：范围单选（默认全部四段）→ POST scope → 202 打开任务日志抽屉", async () => {
    const bodies: { scope?: string }[] = [];
    server.use(
      http.post("*/api/v1/admin/quality/rechecks", async ({ request }) => {
        bodies.push((await request.json()) as { scope?: string });
        return HttpResponse.json(
          { task_id: "TASK-20260928-7777", status: "RUNNING" },
          { status: 202 },
        );
      }),
      http.get("*/api/v1/admin/quality/tasks/:taskId", () =>
        HttpResponse.json({
          task_id: "TASK-20260928-7777",
          task_type: "quality_recheck",
          status: "RUNNING",
          scope: "CHECKSUM",
          started_at: "2026-09-28T08:30:00.000Z",
          logs: [
            { ts: "2026-09-28T08:30:01.000Z", level: "INFO", message: "任务启动：scope=CHECKSUM" },
            { ts: "2026-09-28T08:30:02.000Z", level: "INFO", message: "抽检段完成：抽样 120，失配 1" },
          ],
        }),
      ),
    );
    renderQuality();

    const button = await waitFor(() => {
      const el = document.querySelector('[data-dom-id="quality-recheck-btn"]');
      expect(el).not.toBeNull();
      return el as HTMLButtonElement;
    });
    expect(button.disabled).toBe(false);
    fireEvent.click(button);

    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="recheck-body"]')).not.toBeNull(),
    );
    // 默认选中全部四段
    expect(
      document.querySelector('[data-dom-id="recheck-scope-ALL"]')!.getAttribute("aria-pressed"),
    ).toBe("true");
    // 切到校验和抽检段
    fireEvent.click(document.querySelector('[data-dom-id="recheck-scope-CHECKSUM"]')!);
    expect(
      document.querySelector('[data-dom-id="recheck-scope-CHECKSUM"]')!.getAttribute("aria-pressed"),
    ).toBe("true");
    fireEvent.click(document.querySelector('[data-dom-id="recheck-submit"]')!);

    await waitFor(() => expect(bodies).toEqual([{ scope: "CHECKSUM" }]));
    // 提交成功 → 打开任务日志抽屉（logs 进度时间线 + scope 元信息）
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="quality-task-body"]')).not.toBeNull(),
    );
    expect(screen.getByText("TASK-20260928-7777")).toBeInTheDocument();
    expect(document.querySelector('[data-dom-id="quality-task-logs"]')!.textContent).toContain(
      "任务启动：scope=CHECKSUM",
    );
    expect(screen.getByText("运行中")).toBeInTheDocument();
  });

  it("任务终态 FAILED：抽屉失败 pill 呈现", async () => {
    server.use(
      http.get("*/api/v1/admin/quality/tasks/:taskId", () =>
        HttpResponse.json({
          task_id: "TASK-20260928-8888",
          task_type: "quality_recheck",
          status: "FAILED",
          scope: "ALL",
          started_at: "2026-09-28T08:30:00.000Z",
          finished_at: "2026-09-28T08:31:00.000Z",
          logs: [{ ts: "2026-09-28T08:30:30.000Z", level: "ERROR", message: "对账段异常：连接超时" }],
        }),
      ),
    );
    renderQuality();

    fireEvent.click(
      await waitFor(() => {
        const el = document.querySelector('[data-dom-id="quality-recheck-btn"]');
        expect(el).not.toBeNull();
        return el as HTMLButtonElement;
      }),
    );
    fireEvent.click(await waitFor(() => {
      const el = document.querySelector('[data-dom-id="recheck-submit"]');
      expect(el).not.toBeNull();
      return el as HTMLButtonElement;
    }));

    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="quality-task-body"]')).not.toBeNull(),
    );
    expect(screen.getByText("失败")).toBeInTheDocument();
    expect(document.querySelector('[data-dom-id="quality-task-logs"]')!.textContent).toContain(
      "对账段异常",
    );
  });

  it("报告端点失败 → 错误态面板（非降级占位），重校验入口仍可用", async () => {
    server.use(
      http.get("*/api/v1/admin/quality/reports", () =>
        HttpResponse.json(
          { error: { code: "NOT_FOUND", message: "Not Found", request_id: "t" } },
          { status: 404 },
        ),
      ),
    );
    renderQuality();

    await waitFor(
      () => expect(document.querySelector('[data-dom-id="quality-error"]')).not.toBeNull(),
      { timeout: 3_000 },
    );
    const button = document.querySelector('[data-dom-id="quality-recheck-btn"]') as HTMLButtonElement;
    expect(button.disabled).toBe(false);
  });

  // EDP-601 空态收口：异常空段（报告 pending 同步归零）→ 三件套 + 运行重校验动作
  it("异常空段：空态三件套（运行重校验动作），无合并提示", async () => {
    server.use(
      http.get("*/api/v1/admin/quality/reports", () =>
        HttpResponse.json({
          ...qualityReport,
          kpi: { ...qualityReport.kpi, pending_exceptions: 0, high_priority: 0 },
        }),
      ),
      http.get("*/api/v1/ebms/exceptions", () =>
        HttpResponse.json({ items: [], next_cursor: null, total: 0 }),
      ),
    );
    renderQuality();

    const empty = await waitFor(() => {
      const el = document.querySelector('[data-dom-id="quality-exceptions-empty"]');
      expect(el).not.toBeNull();
      return el!;
    });
    expect(empty.textContent).toContain("当前无待处理异常");
    expect(empty.textContent).toContain("运行重校验");
    expect(document.querySelector('[data-dom-id="quality-merged"]')).toBeNull();
  });
});
