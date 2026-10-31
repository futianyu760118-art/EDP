import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { ThemeProvider } from "../../app/providers/ThemeProvider";
import { routes } from "../../app/router";
import { useSessionStore, type AuthTokenResponse } from "../auth/session-store";
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

const step1 = () => document.querySelector('[data-dom-id="reindex-step-1"]');
const nextBtn = () => document.querySelector('[data-dom-id="reindex-next"]') as HTMLButtonElement;

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(() => {
  useSessionStore.getState().setSession(sessionOf());
});

describe("ReindexWizard 重建索引三步向导（T6 真端点：全量 + tasks 轮询）", () => {
  it("三步前进/后退；提交 202 → RUNNING → 轮询 SUCCEEDED（stats total/mismatched）→ 完成关闭", async () => {
    renderEvidence();

    // 真模式按钮直接可用（无 W5 禁用 tooltip）
    const openBtn = await waitFor(() => {
      const el = document.querySelector('[data-dom-id="evidence-reindex-btn"]');
      expect(el).not.toBeNull();
      return el as HTMLButtonElement;
    });
    expect(openBtn.disabled).toBe(false);
    fireEvent.click(openBtn);

    // 步骤 1：全量范围（scope=ALL 唯一）
    await waitFor(() => expect(step1()).not.toBeNull());
    expect(step1()!.textContent).toContain("全量范围");
    expect(nextBtn().disabled).toBe(false);

    fireEvent.click(nextBtn());
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="reindex-step-2"]')).not.toBeNull(),
    );
    expect(document.querySelector('[data-dom-id="reindex-step-2"]')!.textContent).toContain(
      "checksum 重算",
    );

    fireEvent.click(document.querySelector('[data-dom-id="reindex-next"]')!);
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="reindex-step-3"]')).not.toBeNull(),
    );
    // 摘要回显：范围/规则
    const step3 = document.querySelector('[data-dom-id="reindex-step-3"]')!;
    expect(step3.textContent).toContain("全量");
    expect(step3.textContent).toContain("完整性");

    // 返回上一步可回退
    fireEvent.click(document.querySelector('[data-dom-id="reindex-prev"]')!);
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="reindex-step-2"]')).not.toBeNull(),
    );
    fireEvent.click(document.querySelector('[data-dom-id="reindex-next"]')!);

    fireEvent.click(document.querySelector('[data-dom-id="reindex-submit"]')!);
    // 202 → 首轮 RUNNING
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="reindex-running"]')).not.toBeNull(),
    );
    // 轮询（1s）→ SUCCEEDED：stats total=20 / mismatched=0
    await waitFor(
      () => {
        expect(document.querySelector('[data-dom-id="reindex-result"]')).not.toBeNull();
      },
      { timeout: 5_000 },
    );
    expect(document.querySelector('[data-dom-id="reindex-stats-total"]')!.textContent).toBe("20");
    expect(
      document.querySelector('[data-dom-id="reindex-stats-mismatched"]')!.textContent,
    ).toBe("0");

    fireEvent.click(document.querySelector('[data-dom-id="reindex-done"]')!);
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="reindex-step-1"]')).toBeNull(),
    );
  });

  it("终态 FAILED → 失败态呈现（任务号 + 重试提示）", async () => {
    server.use(
      http.post("*/api/v1/admin/evidence/reindex", () =>
        HttpResponse.json(
          {
            task_id: "00000000-0000-4000-8000-000000000951",
            status: "RUNNING",
          },
          { status: 202 },
        ),
      ),
      http.get("*/api/v1/admin/quality/tasks/:taskId", () =>
        HttpResponse.json({
          task_id: "00000000-0000-4000-8000-000000000951",
          task_type: "evidence_reindex",
          status: "FAILED",
          scope: "ALL",
          started_at: "2026-09-28T08:30:00.000Z",
          finished_at: "2026-09-28T08:30:05.000Z",
          logs: [{ ts: "2026-09-28T08:30:04.000Z", level: "ERROR", message: "重算失败：存储连接中断" }],
        }),
      ),
    );
    renderEvidence();

    fireEvent.click(
      await waitFor(() => {
        const el = document.querySelector('[data-dom-id="evidence-reindex-btn"]');
        expect(el).not.toBeNull();
        return el as HTMLButtonElement;
      }),
    );
    await waitFor(() => expect(step1()).not.toBeNull());
    fireEvent.click(nextBtn());
    fireEvent.click(document.querySelector('[data-dom-id="reindex-next"]')!);
    fireEvent.click(document.querySelector('[data-dom-id="reindex-submit"]')!);

    await waitFor(
      () => {
        expect(document.querySelector('[data-dom-id="reindex-failed"]')).not.toBeNull();
      },
      { timeout: 5_000 },
    );
    expect(document.querySelector('[data-dom-id="reindex-failed"]')!.textContent).toContain(
      "000000000951",
    );
    expect(document.querySelector('[data-dom-id="reindex-failed"]')!.textContent).toContain(
      "重索引失败",
    );
  });
});
