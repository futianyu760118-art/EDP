import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
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

function renderOverview() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: ["/admin/overview"] });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
  return router;
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(() => {
  useSessionStore.getState().setSession(sessionOf("manager1", ["MANAGER"]));
});

describe("OverviewPage 骨架（MSW 模式渲染路由）", () => {
  it("四个区块占位容器存在", async () => {
    renderOverview();

    await waitFor(() => {
      expect(document.querySelector('[data-dom-id="overview-page"]')).not.toBeNull();
    });
    expect(document.querySelector('[data-dom-id="overview-hero"]')).not.toBeNull();
    expect(document.querySelector('[data-dom-id="overview-kpis"]')).not.toBeNull();
    expect(document.querySelector('[data-dom-id="overview-risk"]')).not.toBeNull();
    expect(document.querySelector('[data-dom-id="overview-bottom"]')).not.toBeNull();
  });

  it("路由 handle title → 面包屑「运营总览」", async () => {
    renderOverview();

    await waitFor(() => {
      expect(document.querySelector('[data-dom-id="overview-page"]')).not.toBeNull();
    });
    expect(document.querySelector('[data-slot="crumb"]')?.textContent).toBe("运营总览");
  });
});

describe("OverviewPage Hero/KPI 数据接线（MSW fixtures）", () => {
  it("Hero 标题 P1 数（ebms P1×3）与三指标（96.8% / 0.81s / 99.5%）", async () => {
    renderOverview();

    expect(await screen.findByText("今天的 EDP 状态：证据链健康，3 个 P1 风险需要处理")).toBeInTheDocument();
    await waitFor(() => {
      expect(document.querySelector('[data-dom-id="overview-hero-coverage"]')?.textContent).toBe("96.8%");
      expect(document.querySelector('[data-dom-id="overview-hero-p95"]')?.textContent).toBe("0.81s");
      expect(document.querySelector('[data-dom-id="overview-hero-success"]')?.textContent).toBe("99.5%");
    });
  });

  it("8 张 KPI 卡 label 与 fixtures 值（23 / 18,421）", async () => {
    renderOverview();

    const kpis = (await waitFor(() => {
      const el = document.querySelector('[data-dom-id="overview-kpis"]');
      expect(el).not.toBeNull();
      return el as HTMLElement;
    }))!;
    for (const label of ["业务对象", "24H 事件", "证据存储", "适配器成功率", "DLQ 队列", "P95 延迟", "审计日志量", "策略命中"]) {
      expect(within(kpis).getByText(label)).toBeInTheDocument();
    }
    expect(await within(kpis).findByText("23")).toBeInTheDocument();
    expect(await within(kpis).findByText("18,421")).toBeInTheDocument();
  });
});

describe("OverviewPage 面板级独立降级（T3 评审遗留闭环）", () => {
  it("quality coverage 500 → coverage 派生指标兜底 '—'，health/ebms 派生区正常（单点故障不拖垮整页）", async () => {
    server.use(
      http.get("*/api/v1/admin/quality/coverage", () =>
        HttpResponse.json({ error: { code: "INTERNAL", message: "mock coverage 500" } }, { status: 500 }),
      ),
    );
    renderOverview();

    // health 派生（Hero P95 + KPI 24H 事件）存活
    expect(await screen.findByText("18,421")).toBeInTheDocument();
    await waitFor(() => {
      expect(document.querySelector('[data-dom-id="overview-hero-p95"]')?.textContent).toBe("0.81s");
    });
    // coverage 派生区块（Hero 覆盖率）降级为 '—'；ebms 派生标题不受影响
    expect(document.querySelector('[data-dom-id="overview-hero-coverage"]')?.textContent).toBe("—");
    expect(screen.getByText("今天的 EDP 状态：证据链健康，3 个 P1 风险需要处理")).toBeInTheDocument();
  });

  it("health 500（反向）→ KPI 网格 7 张 ops 派生卡 '—'，coverage/objects 派生仍正常", async () => {
    server.use(
      http.get("*/api/v1/health", () =>
        HttpResponse.json({ error: { code: "INTERNAL", message: "mock health 500" } }, { status: 500 }),
      ),
    );
    renderOverview();

    // coverage 派生（Hero 覆盖率）存活
    await waitFor(() => {
      expect(document.querySelector('[data-dom-id="overview-hero-coverage"]')?.textContent).toBe("96.8%");
    });
    expect(document.querySelector('[data-dom-id="overview-hero-p95"]')?.textContent).toBe("—");

    // objects 派生卡正常出值后，其余 7 张 ops 派生卡全部 '—'
    const kpis = document.querySelector('[data-dom-id="overview-kpis"]') as HTMLElement;
    expect(await within(kpis).findByText("23")).toBeInTheDocument();
    expect(within(kpis).getAllByText("—")).toHaveLength(7);
  });
});

describe("OverviewPage T6 三栏图表与审计动态（MSW fixtures）", () => {
  it("三栏标题与数据健康子指标（校验通过率 99.2% / 完整性 96.8% / 对象覆盖率 96.8% / 孤儿事件 0）", async () => {
    renderOverview();

    const bottom = (await waitFor(() => {
      const el = document.querySelector('[data-dom-id="overview-bottom"]');
      expect(el).not.toBeNull();
      return el as HTMLElement;
    }))!;
    for (const title of ["数据健康", "证据链健康", "审计动态"]) {
      expect(within(bottom).getByText(title)).toBeInTheDocument();
    }
    expect(await within(bottom).findByText("校验通过率")).toBeInTheDocument();
    expect(within(bottom).getByText("99.2%")).toBeInTheDocument();
    // 完整性与对象覆盖率同口径（completeness = coverage.overall）→ 双 96.8%
    expect(within(bottom).getAllByText("96.8%")).toHaveLength(2);
    expect(within(bottom).getByText("0")).toBeInTheDocument();
  });

  it("MiniBarChart 24 根柱、第 15 根（idx=14）warning 高亮；峰值 aria 标注 742", async () => {
    renderOverview();

    const chart = await waitFor(() => {
      const el = document.querySelector('[data-dom-id="overview-bar-chart"]');
      expect(el).not.toBeNull();
      return el as SVGSVGElement;
    });
    const rects = chart.querySelectorAll("rect");
    expect(rects).toHaveLength(24);
    expect(rects[14].getAttribute("class")).toContain("fill-state-warning");
    expect(rects[13].getAttribute("class")).toContain("fill-primary-50");
    expect(chart.getAttribute("aria-label")).toContain("742");
  });

  it("证据链健康：环形 100%/完整 + 证据总量 20 + 依赖关系完整", async () => {
    renderOverview();

    const evidence = (await waitFor(() => {
      const el = document.querySelector('[data-dom-id="panel-evidence-health"]');
      expect(el).not.toBeNull();
      return el as HTMLElement;
    }))!;
    await waitFor(() => {
      expect(document.querySelector('[data-dom-id="overview-donut"]')).not.toBeNull();
    });
    // 环形中心数值 + 有效率行均渲染 100%（fixtures evidence_valid_rate）
    const pctTexts = await within(evidence).findAllByText("100%");
    expect(pctTexts).toHaveLength(2);
    expect(within(evidence).getByText("完整")).toBeInTheDocument();
    expect(within(evidence).getByText("20")).toBeInTheDocument();
    expect(within(evidence).getByText("依赖关系完整")).toBeInTheDocument();
  });

  it("审计动态 4 条：近 4 条含 2 条 GUARD_DENIED（error 高亮），其余 muted pill", async () => {
    renderOverview();

    const audit = (await waitFor(() => {
      const el = document.querySelector('[data-dom-id="panel-audit"]');
      expect(el).not.toBeNull();
      return el as HTMLElement;
    }))!;
    await waitFor(() => {
      expect(audit.querySelectorAll('[data-dom-id="overview-audit-row"]')).toHaveLength(4);
    });
    const deniedPills = await within(audit).findAllByText("GUARD_DENIED");
    expect(deniedPills).toHaveLength(2);
    for (const pill of deniedPills) {
      expect(pill.className).toContain("bg-state-error-bg");
    }
    const mutedPill = within(audit).getByText("ADAPTER_SYNC_FAILED");
    expect(mutedPill.className).toContain("bg-muted");
  });
});

describe("OverviewPage T6 follow-up：三栏 PanelCard 降级断言", () => {
  it("audit 500 → panel-audit-error 出现，panel-data-health 正常渲染（单点故障隔离）", async () => {
    server.use(
      http.get("*/api/v1/audit-logs", () =>
        HttpResponse.json({ error: { code: "INTERNAL", message: "mock audit 500" } }, { status: 500 }),
      ),
    );
    renderOverview();

    await waitFor(
      () => {
        expect(document.querySelector('[data-dom-id="panel-audit-error"]')).not.toBeNull();
      },
      { timeout: 4000 },
    );
    expect(document.querySelector('[data-dom-id="panel-data-health-error"]')).toBeNull();
    expect(document.querySelector('[data-dom-id="panel-evidence-health-error"]')).toBeNull();
    await waitFor(() => {
      expect(document.querySelectorAll('[data-dom-id="overview-bar-chart"] rect')).toHaveLength(24);
    });
    expect(document.querySelector('[data-dom-id="panel-audit-empty"]')).toBeNull();
  });
});
