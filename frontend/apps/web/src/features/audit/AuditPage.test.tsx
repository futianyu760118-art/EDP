import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "../../app/providers/ThemeProvider";
import { routes } from "../../app/router";
import { useSessionStore, type AuthTokenResponse } from "../auth/session-store";
import {
  POLICY_DECISION_REVIEW,
  POLICY_EVIDENCE_EXPORT,
} from "../../mocks/data/audit";
import { resetAuditMock } from "../../mocks/handlers/audit";
import { server } from "../../mocks/server";
import { deriveActionLabel } from "./vocab";

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

function renderAudit(entry = "/admin/audit") {
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

const logRows = () => document.querySelectorAll('[data-dom-id^="audit-row-"]');
const policyRows = () => document.querySelectorAll('[data-dom-id^="policy-row-"]');

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  resetAuditMock();
});
afterAll(() => server.close());
beforeEach(() => {
  useSessionStore.getState().setSession(sessionOf("admin1", ["ADMIN"]));
});

/**
 * fixtures 锚定（mocks/data/audit.ts）：14 条审计（含 2 条 GUARD_DENIED +
 * 1 条 RATE_LIMITED + 1 条裸名 records）；策略 3 条（ACTIVE×2 + DISABLED×1）。
 */
describe("AuditPage 日志 tab（MSW 模式渲染路由）", () => {
  it("7 列渲染 + 词表中文标签 + 裸名 records 消歧 + GUARD_DENIED/RATE_LIMITED 行 error 高亮", async () => {
    renderAudit();
    await waitFor(() => expect(logRows().length).toBe(14));

    const headers = Array.from(
      document.querySelectorAll('[data-dom-id="audit-table"] thead th'),
    ).map((th) => th.textContent);
    expect(headers).toEqual(["时间", "ID", "操作者", "操作", "资源", "结果摘要", "级别"]);
    expect(document.querySelector('[data-dom-id="pagination-range"]')!.textContent).toContain(
      "共 14 条",
    );

    // 词表：显式常量 + 前缀派生（action mono 与中文 label 双行）
    expect(screen.getAllByText("越权拦截")).toHaveLength(2);
    expect(screen.getByText("限流拒绝")).toBeInTheDocument();
    expect(screen.getByText("证据创建")).toBeInTheDocument();
    expect(screen.getByText("适配器同步失败")).toBeInTheDocument();
    expect(screen.getByText("案例创建")).toBeInTheDocument();

    // W3-13：裸名 records + EVIDENCE_CREATE → evidence.records
    expect(document.querySelector('[data-dom-id="audit-row-10233"]')!.textContent).toContain(
      "evidence.records",
    );

    // 拒绝级（GUARD_DENIED / RATE_LIMITED）整行 -error 语义色高亮；正常行无
    for (const id of [10229, 10230, 10232]) {
      const cls = document.querySelector(`[data-dom-id="audit-row-${id}"]`)!.className;
      expect(cls).toContain("audit-row-error");
      expect(cls).toContain("bg-state-error-bg");
    }
    expect(document.querySelector('[data-dom-id="audit-row-10226"]')!.className).not.toContain(
      "audit-row-error",
    );
  });

  it("筛选→chips→请求参数断言（since/until 传参）；chips 单独移除不清空全部", async () => {
    const urls: string[] = [];
    server.use(
      http.get("*/api/v1/audit-logs", ({ request }) => {
        urls.push(request.url);
        return HttpResponse.json({ items: [], next_cursor: null, total: 0 });
      }),
    );
    renderAudit();
    await waitFor(() => expect(urls.length).toBeGreaterThan(0));

    fireEvent.change(document.querySelector('[data-dom-id="audit-filter-actor"]')!, {
      target: { value: "adapter:erp" },
    });
    fireEvent.change(document.querySelector('[data-dom-id="audit-filter-action"]')!, {
      target: { value: "GUARD_DENIED" },
    });
    fireEvent.change(document.querySelector('[data-dom-id="audit-filter-since"]')!, {
      target: { value: "2026-09-27" },
    });
    fireEvent.change(document.querySelector('[data-dom-id="audit-filter-until"]')!, {
      target: { value: "2026-09-28" },
    });

    await waitFor(() => {
      const last = new URL(urls[urls.length - 1]);
      expect(last.searchParams.get("actor_id")).toBe("adapter:erp");
      expect(last.searchParams.get("action")).toBe("GUARD_DENIED");
      expect(last.searchParams.get("since")).toBe("2026-09-27T00:00:00Z");
      expect(last.searchParams.get("until")).toBe("2026-09-28T23:59:59Z");
    });

    // 已生效 chips
    expect(screen.getByText("操作人：adapter:erp")).toBeInTheDocument();
    expect(screen.getByText("动作：GUARD_DENIED")).toBeInTheDocument();
    expect(screen.getByText("开始：2026-09-27")).toBeInTheDocument();
    expect(screen.getByText("结束：2026-09-28")).toBeInTheDocument();

    // W3R 修复语义：移除单个 chip 只清对应参数，其余保留
    fireEvent.click(document.querySelector('[data-dom-id="chip-remove-actor_id"]')!);
    await waitFor(() => {
      const last = new URL(urls[urls.length - 1]);
      expect(last.searchParams.get("actor_id")).toBeNull();
      expect(last.searchParams.get("action")).toBe("GUARD_DENIED");
      expect(last.searchParams.get("since")).toBe("2026-09-27T00:00:00Z");
      expect(last.searchParams.get("until")).toBe("2026-09-28T23:59:59Z");
    });
    expect(document.querySelectorAll('[data-dom-id^="chip-remove-"]').length).toBe(3);

    // 再移除 since：仅清 since
    fireEvent.click(document.querySelector('[data-dom-id="chip-remove-since"]')!);
    await waitFor(() => {
      const last = new URL(urls[urls.length - 1]);
      expect(last.searchParams.get("since")).toBeNull();
      expect(last.searchParams.get("until")).toBe("2026-09-28T23:59:59Z");
    });
    expect(screen.getByText("动作：GUARD_DENIED")).toBeInTheDocument();
  });

  it("导出弹窗：参数与接口一一对应回显当前筛选 + 导出 CSV 触发下载", async () => {
    // jsdom 无 Blob URL：mock createObjectURL/revoke + 拦截锚点点击
    const createObjectURL = vi.fn(() => "blob:audit-export");
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, "createObjectURL", {
      writable: true,
      configurable: true,
      value: createObjectURL,
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      writable: true,
      configurable: true,
      value: revokeObjectURL,
    });
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});

    renderAudit();
    await waitFor(() => expect(logRows().length).toBe(14));

    // 先生效一个筛选（导出范围回显数据源与列表共用）
    fireEvent.change(document.querySelector('[data-dom-id="audit-filter-action"]')!, {
      target: { value: "GUARD_DENIED" },
    });
    await waitFor(() => screen.getByText("动作：GUARD_DENIED"));

    fireEvent.click(document.querySelector('[data-dom-id="audit-export"]')!);
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="audit-export-modal"]')).not.toBeNull(),
    );
    // 回显：参数名与 GET /audit-logs 查询参数一一对应
    expect(document.querySelector('[data-dom-id="audit-export-echo-action"]')!.textContent).toBe(
      "GUARD_DENIED",
    );
    expect(
      document.querySelector('[data-dom-id="audit-export-echo-resource_type"]')!.textContent,
    ).toBe("全部");
    expect(document.querySelector('[data-dom-id="audit-export-echo-since"]')!.textContent).toBe(
      "全部",
    );
    expect(
      document.querySelector('[data-dom-id="audit-export-filename"]')!,
    ).toHaveValue("audit-log-export");

    fireEvent.click(screen.getByRole("button", { name: /导出 CSV/ }));
    await waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1));
    expect(clickSpy).toHaveBeenCalled();
    // 当前筛选（action=GUARD_DENIED）命中 2 条
    expect(await screen.findByText("已导出 2 条审计日志")).toBeInTheDocument();

    clickSpy.mockRestore();
  });
});

describe("AuditPage 策略 tab（EDP-032 CRUD）", () => {
  it("策略列表 3 条 + 三维范围摘要/通配语义", async () => {
    renderAudit();
    fireEvent.click(document.querySelector('[data-dom-id="audit-tab-policies"]')!);
    await waitFor(() => expect(policyRows().length).toBe(3));

    const evidenceRow = document.querySelector(
      `[data-dom-id="policy-row-${POLICY_EVIDENCE_EXPORT}"]`,
    )!;
    expect(evidenceRow.textContent).toContain("证据导出管控");
    expect(evidenceRow.textContent).toContain("evidence.records");
    expect(evidenceRow.textContent).toContain("EVIDENCE_*");
    // actor_types 空 = 通配
    expect(evidenceRow.textContent).toContain("全部（通配）");
    expect(evidenceRow.textContent).toContain("站内消息 + 邮件");
  });

  it("新建策略：表单（资源/动作多选 + PREFIX_* 提示 + 触发者）→ POST → 列表出现", async () => {
    renderAudit();
    // 头部「新建策略」：切策略 tab + 打开弹窗
    fireEvent.click(document.querySelector('[data-dom-id="policy-create"]')!);
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="policy-table"]')).not.toBeNull(),
    );
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="policy-create-form"]')).not.toBeNull(),
    );
    // PREFIX_* 通配提示文案
    expect(
      document.querySelector('[data-dom-id="policy-action-hint"]')!.textContent,
    ).toContain("EVIDENCE_*");

    fireEvent.change(document.querySelector('[data-dom-id="policy-name"]')!, {
      target: { value: "越权拦截告警" },
    });
    fireEvent.change(document.querySelector('[data-dom-id="policy-description"]')!, {
      target: { value: "GUARD_DENIED 命中即通知" },
    });
    // 动作候选 + 触发者 AI（POST body 三维）
    fireEvent.click(
      document.querySelector('[data-dom-id="policy-action-input-candidate-GUARD_DENIED"]')!,
    );
    fireEvent.click(document.querySelector('[data-dom-id="policy-actor-AI"]')!);
    fireEvent.click(screen.getByRole("button", { name: /确认创建/ }));

    // 201 → invalidate → 列表出现新策略（默认 handler 落可变行集）
    await waitFor(() => expect(policyRows().length).toBe(4));
    const newRow = Array.from(policyRows()).find((row) =>
      row.textContent?.includes("越权拦截告警"),
    );
    expect(newRow).toBeDefined();
    expect(newRow!.textContent).toContain("GUARD_DENIED");
    expect(newRow!.textContent).toContain("AI");
    // resource_types 未选 = 通配
    expect(newRow!.textContent).toContain("全部（通配）");
    expect(await screen.findByText("策略已创建")).toBeInTheDocument();
  });

  it("启停开关 → PATCH {status} 断言", async () => {
    let patchUrl = "";
    let patchBody: Record<string, unknown> | undefined;
    server.use(
      http.patch("*/api/v1/admin/audit-policies/:policyId", async ({ params, request }) => {
        patchUrl = String(request.url);
        patchBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          policy_id: String(params.policyId),
          name: "证据导出管控",
          description: null,
          resource_types: ["evidence.records"],
          actions: ["EVIDENCE_*"],
          actor_types: [],
          notify_channel: null,
          status: (patchBody?.status as string) ?? "DISABLED",
          created_at: "2026-08-29T08:30:00.000Z",
          updated_at: "2026-09-28T08:31:00.000Z",
          created_by: "user:admin",
          updated_by: "user:admin",
        });
      }),
    );
    renderAudit();
    fireEvent.click(document.querySelector('[data-dom-id="audit-tab-policies"]')!);
    await waitFor(() => expect(policyRows().length).toBe(3));

    const toggle = document.querySelector(
      `[data-dom-id="policy-toggle-${POLICY_EVIDENCE_EXPORT}"]`,
    ) as HTMLButtonElement;
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    fireEvent.click(toggle);

    await waitFor(() => expect(patchBody).toEqual({ status: "DISABLED" }));
    expect(patchUrl).toContain(POLICY_EVIDENCE_EXPORT);
    expect(await screen.findByText("策略「证据导出管控」已停用")).toBeInTheDocument();
  });

  it("删除：危险确认（一般级）→ 取消不触发 → 确认 DELETE 断言", async () => {
    let deletedUrl = "";
    server.use(
      http.delete("*/api/v1/admin/audit-policies/:policyId", ({ request }) => {
        deletedUrl = String(request.url);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderAudit();
    fireEvent.click(document.querySelector('[data-dom-id="audit-tab-policies"]')!);
    await waitFor(() => expect(policyRows().length).toBe(3));

    const openConfirm = () =>
      fireEvent.click(
        document.querySelector(`[data-dom-id="policy-delete-${POLICY_DECISION_REVIEW}"]`)!,
      );
    openConfirm();
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="danger-confirm"]')).not.toBeNull(),
    );
    expect(document.querySelector('[data-dom-id="audit-page"]')!.textContent).toContain(
      "操作不可恢复",
    );

    // 取消：不触发 DELETE
    fireEvent.click(document.querySelector('[data-dom-id="danger-cancel"]')!);
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="danger-confirm"]')).toBeNull(),
    );
    expect(deletedUrl).toBe("");

    // 确认：DELETE /admin/audit-policies/{id}
    openConfirm();
    await waitFor(() =>
      expect(document.querySelector('[data-dom-id="danger-confirm"]')).not.toBeNull(),
    );
    fireEvent.click(document.querySelector('[data-dom-id="danger-confirm"]')!);
    await waitFor(() => expect(deletedUrl).toContain(POLICY_DECISION_REVIEW));
    expect(await screen.findByText("策略「决策人工复核」已删除")).toBeInTheDocument();
  });
});

describe("审计词表预留前缀（W4 终审 Minor：POLICY_*/QUALITY_* 中文映射兜底）", () => {
  it("POLICY_*：前缀+动词派生已覆盖策略 CRUD（audit.policies 行写即派生）", () => {
    expect(deriveActionLabel("POLICY_CREATE")).toBe("策略创建");
    expect(deriveActionLabel("POLICY_UPDATE")).toBe("策略更新");
    expect(deriveActionLabel("POLICY_DELETE")).toBe("策略删除");
  });

  it("QUALITY_*：预留前缀映射（词表键对齐后端质量事件 event_type 实测常量）", () => {
    expect(deriveActionLabel("QUALITY_CHECKSUM_FAILED")).toBe("质量校验和失败");
    expect(deriveActionLabel("QUALITY_RECHECK_SUCCEEDED")).toBe("质量复检成功");
    expect(deriveActionLabel("QUALITY_RECHECK_FAILED")).toBe("质量复检失败");
    expect(deriveActionLabel("QUALITY_REINDEX_MISMATCH")).toBe("质量重索引失配");
    expect(deriveActionLabel("QUALITY_REINDEX_SUCCEEDED")).toBe("质量重索引成功");
    expect(deriveActionLabel("QUALITY_REINDEX_FAILED")).toBe("质量重索引失败");
  });
});
