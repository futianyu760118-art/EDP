import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "../../app/providers/ThemeProvider";
import { routes } from "../../app/router";
import { useSessionStore, type AuthTokenResponse } from "../auth/session-store";
import { DEMO_NOW } from "../../mocks/lib/demo-time";
import { SYNC_ID } from "../../mocks/data/ids";
import { resetAdaptersMock } from "../../mocks/handlers/adapters";
import { server } from "../../mocks/server";

function sessionOf(): AuthTokenResponse {
  return {
    access_token: "t-admin1",
    refresh_token: "r-admin1",
    expires_in: 7200,
    tenant: {
      tenant_id: "00000000-0000-0000-0000-000000000001",
      slug: "default",
      name: "默认租户",
      status: "ACTIVE",
    },
    user: {
      user_id: "00000000-0000-0000-0000-000000000002",
      username: "admin1",
      roles: ["ADMIN"],
      is_platform_admin: false,
    },
  };
}

function renderAdapters() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: ["/admin/adapters"] });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

const $ = (id: string) => document.querySelector(`[data-dom-id="${id}"]`) as HTMLElement;
const btn = (id: string) => $(id) as HTMLButtonElement;
const input = (id: string) => $(id) as HTMLInputElement;
const select = (id: string) => $(id) as HTMLSelectElement;
const rows = () => document.querySelectorAll('[data-dom-id^="adapter-row-"]');

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  resetAdaptersMock();
  vi.useRealTimers();
});
afterAll(() => server.close());
beforeEach(() => {
  // 相对时间（relTime）以系统时钟计算：钉到 fixtures 演示锚，保证「N 分钟前」确定
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(DEMO_NOW);
  useSessionStore.getState().setSession(sessionOf());
});

describe("AdaptersPage 适配器管理（MSW 模式渲染路由）", () => {
  it("7 数据列 + 操作列：演示扩展（access/team/mode/相对时间）+ health/status 语义色 + 行操作", async () => {
    renderAdapters();
    await waitFor(() => expect(rows().length).toBe(5));

    const headers = Array.from(document.querySelectorAll('[data-dom-id="adapters-table"] thead th')).map(
      (th) => th.textContent,
    );
    expect(headers).toEqual(["系统", "接入方式", "责任团队", "最近同步", "健康度", "状态", "模式", "操作"]);

    const erp = $("adapter-row-erp")!;
    expect(erp.querySelector("td")!.className).toContain("font-mono");
    expect(erp.textContent).toContain("REST 拉取");
    expect(erp.textContent).toContain("数据平台组");
    expect(erp.textContent).toContain("12 分钟前");
    expect(erp.textContent).toContain("99.9%");
    expect(erp.textContent).toContain("运行中");
    expect(erp.textContent).toContain("mock");
    expect(erp.innerHTML).toContain("bg-state-success-bg");

    // plm 降级：status/health warning 色
    const plm = $("adapter-row-plm")!;
    expect(plm.textContent).toContain("降级");
    expect(plm.innerHTML).toContain("bg-state-warning-bg");

    expect($("adapter-test-erp")).not.toBeNull();
    expect($("adapter-log-erp")).not.toBeNull();
  });

  it("真模式契约行（无演示扩展）→ access/team「—」降级 + health OK 绿 + 相对时间", async () => {
    server.use(
      http.get("*/api/v1/admin/adapters", () =>
        HttpResponse.json({
          items: [
            {
              adapter: "erp",
              mode: "mock",
              status: "运行中",
              health: "OK",
              last_sync_at: "2026-09-28T08:18:00.000Z",
            },
          ],
          next_cursor: null,
        }),
      ),
    );
    renderAdapters();
    await waitFor(() => expect(rows().length).toBe(1));

    const erp = $("adapter-row-erp")!;
    expect(erp.textContent).toContain("OK");
    expect(erp.textContent).toContain("12 分钟前");
    // access/team 两列降级「—」（恰好两处）
    expect(erp.textContent!.match(/—/g)).toHaveLength(2);
  });

  it("新增弹窗：认证折叠面板默认收起 → 展开 → POST /systems body 断言 → 201 toast + 关闭", async () => {
    const calls: { name?: string; type?: string; endpoint?: string; auth_config?: unknown }[] = [];
    server.use(
      http.post("*/api/v1/systems", async ({ request }) => {
        calls.push((await request.json()) as typeof calls[number]);
        return HttpResponse.json(
          {
            system_id: "00000000-0000-4000-8000-0000000961001",
            name: "wms-gateway",
            status: "ACTIVE",
            created_at: "2026-09-28T08:30:00.000Z",
          },
          { status: 201 },
        );
      }),
    );
    renderAdapters();
    await waitFor(() => expect(rows().length).toBe(5));

    fireEvent.click(btn("adapter-add"));
    await waitFor(() => expect($("adapter-create-form")).not.toBeNull());
    // 折叠面板默认收起（#15）
    expect($("adapter-auth-body")).toBeNull();
    expect(btn("adapter-auth-toggle").getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(btn("adapter-auth-toggle"));
    await waitFor(() => expect($("adapter-auth-body")).not.toBeNull());
    fireEvent.change($("adapter-auth-kind"), { target: { value: "basic" } });
    fireEvent.change($("adapter-secret-ref"), { target: { value: "ENV:WMS_KEY" } });

    fireEvent.change($("adapter-name"), { target: { value: "wms-gateway" } });
    fireEvent.change($("adapter-endpoint"), { target: { value: "https://wms.example/api" } });
    fireEvent.click(btn("modal-form-submit"));

    await waitFor(() =>
      expect(calls).toEqual([
        {
          name: "wms-gateway",
          type: "SOURCE",
          endpoint: "https://wms.example/api",
          auth_config: { kind: "basic", secret_ref: "ENV:WMS_KEY" },
        },
      ]),
    );
    expect(await screen.findByText("适配器已注册")).toBeInTheDocument();
    await waitFor(() => expect($("adapter-create-form")).toBeNull());
  });

  it("新增弹窗 409：同名（erp）→ 行内错误保留表单", async () => {
    renderAdapters();
    await waitFor(() => expect(rows().length).toBe(5));

    fireEvent.click(btn("adapter-add"));
    await waitFor(() => expect($("adapter-create-form")).not.toBeNull());
    fireEvent.change($("adapter-name"), { target: { value: "erp" } });
    fireEvent.change($("adapter-endpoint"), { target: { value: "https://erp.example/api" } });
    fireEvent.click(btn("modal-form-submit"));

    await waitFor(() => expect($("adapter-create-error")).not.toBeNull());
    expect($("adapter-create-error")!.textContent).toContain("适配器名称已存在");
    expect($("adapter-create-form")).not.toBeNull();
  });

  it("测试连接：预填当前行 + POST mode=incremental → 终态 stats 四计数 + 「连接正常」", async () => {
    const calls: { adapter: string; body: { mode?: string } }[] = [];
    server.use(
      http.post("*/api/v1/admin/adapters/:adapterName/sync", async ({ params, request }) => {
        calls.push({
          adapter: String(params.adapterName),
          body: (await request.json()) as { mode?: string },
        });
        return HttpResponse.json(
          { sync_id: SYNC_ID, status: "RUNNING", started_at: "2026-09-28T08:30:00.000Z" },
          { status: 202 },
        );
      }),
    );
    renderAdapters();
    await waitFor(() => expect(rows().length).toBe(5));

    fireEvent.click(btn("adapter-test-erp"));
    await waitFor(() => expect($("adapter-test-modal")).not.toBeNull());
    expect(($("adapter-test-target") as HTMLSelectElement).value).toBe("erp");

    fireEvent.click(btn("modal-form-submit"));
    await waitFor(() => expect(calls).toEqual([{ adapter: "erp", body: { mode: "incremental" } }]));

    // 覆写 POST 未登记轮询态 → status 直接终态（fixtures SUCCEEDED）
    const stats = await waitFor(() => {
      const el = $("adapter-test-stats");
      expect(el).not.toBeNull();
      return el!;
    });
    for (const value of ["1200", "1180", "20", "0"]) {
      expect(stats.textContent).toContain(value);
    }
    expect($("adapter-test-ok")!.textContent).toContain("连接正常");
  });

  it("测试连接轮询推进：RUNNING →（1s）→ SUCCEEDED + 时间线完成行", async () => {
    renderAdapters();
    await waitFor(() => expect(rows().length).toBe(5));

    fireEvent.click(btn("adapter-test-erp"));
    await waitFor(() => expect($("adapter-test-modal")).not.toBeNull());
    fireEvent.click(btn("modal-form-submit"));

    // 首次 status 轮询 → RUNNING 行
    await waitFor(() => expect($("adapter-test-running")).not.toBeNull());
    expect($("adapter-test-timeline")!.textContent).toContain("同步执行中");

    // 1s 轮询 → 终态 SUCCEEDED（stats + 连接正常 + 同步完成）
    await waitFor(
      () => {
        expect($("adapter-test-ok")).not.toBeNull();
        expect($("adapter-test-timeline")!.textContent).toContain("同步完成");
        expect($("adapter-test-running")).toBeNull();
      },
      { timeout: 5_000 },
    );
    expect($("adapter-test-stats")!.textContent).toContain("1200");
  });

  it("数据源连接向导：三步前进/回退保持输入 + 摘要回显 + 提交 POST /systems 后关闭", async () => {
    const calls: { name?: string; type?: string; endpoint?: string; auth_config?: unknown }[] = [];
    server.use(
      http.post("*/api/v1/systems", async ({ request }) => {
        calls.push((await request.json()) as typeof calls[number]);
        return HttpResponse.json(
          {
            system_id: "00000000-0000-4000-8000-0000000961002",
            name: "scada-gw",
            status: "ACTIVE",
            created_at: "2026-09-28T08:30:00.000Z",
          },
          { status: 201 },
        );
      }),
    );
    renderAdapters();
    await waitFor(() => expect(rows().length).toBe(5));

    fireEvent.click(btn("connect-open"));
    await waitFor(() => expect($("connect-wizard")).not.toBeNull());
    expect($("wizard-step-1")).not.toBeNull();
    expect(btn("wizard-prev").disabled).toBe(true); // 首步禁用回退（#7）
    expect(btn("wizard-next").disabled).toBe(true); // 未填名称/Endpoint 禁用前进

    fireEvent.change($("wizard-name"), { target: { value: "scada-gw" } });
    fireEvent.change($("wizard-type"), { target: { value: "CONSUMER" } });
    fireEvent.change($("wizard-endpoint"), { target: { value: "https://scada.example" } });
    await waitFor(() => expect(btn("wizard-next").disabled).toBe(false));

    fireEvent.click(btn("wizard-next"));
    await waitFor(() => expect($("wizard-step-2")).not.toBeNull());
    // 认证配置折叠面板展开态（#15）
    expect($("wizard-auth-body")).not.toBeNull();
    fireEvent.change($("wizard-secret-ref"), { target: { value: "ENV:SCADA_KEY" } });

    fireEvent.click(btn("wizard-next"));
    await waitFor(() => expect($("wizard-step-3")).not.toBeNull());
    const summary = $("wizard-summary")!;
    expect(summary.textContent).toContain("scada-gw");
    expect(summary.textContent).toContain("CONSUMER · 消费系统");
    expect(summary.textContent).toContain("https://scada.example");
    expect(summary.textContent).toContain("apikey");
    expect(summary.textContent).toContain("ENV:SCADA_KEY");

    // 回退两步 → 输入保留 → 再前进摘要回显（#7 可回退）
    fireEvent.click(btn("wizard-prev"));
    await waitFor(() => expect($("wizard-step-2")).not.toBeNull());
    fireEvent.click(btn("wizard-prev"));
    await waitFor(() => expect($("wizard-step-1")).not.toBeNull());
    expect(($("wizard-name") as HTMLInputElement).value).toBe("scada-gw");
    fireEvent.click(btn("wizard-next"));
    fireEvent.click(btn("wizard-next"));
    await waitFor(() => expect($("wizard-step-3")).not.toBeNull());
    expect($("wizard-summary")!.textContent).toContain("ENV:SCADA_KEY");

    fireEvent.click(btn("wizard-next")); // 末步 = 完成 → 提交
    await waitFor(() =>
      expect(calls).toEqual([
        {
          name: "scada-gw",
          type: "CONSUMER",
          endpoint: "https://scada.example",
          auth_config: { kind: "apikey", secret_ref: "ENV:SCADA_KEY" },
        },
      ]),
    );
    await waitFor(() => expect($("connect-wizard")).toBeNull());
  });

  it("日志抽屉：历史下拉（默认最新）切换 FAILED 任务 + stats/时间线两态", async () => {
    renderAdapters();
    await waitFor(() => expect(rows().length).toBe(5));

    fireEvent.click(btn("adapter-log-erp"));
    await waitFor(() => expect($("adapter-log-body")).not.toBeNull());
    // 默认最新一次：sync_id + stats 四计数 + 完成时间线
    expect($("adapter-log-sync-id")!.textContent).toContain(SYNC_ID);
    const stats = $("adapter-log-stats")!;
    for (const value of ["1200", "1180", "20", "0"]) {
      expect(stats.textContent).toContain(value);
    }
    expect($("adapter-log-timeline")!.textContent).toContain("同步完成");

    // 历史下拉三条（latest SUCCEEDED + full SUCCEEDED + replay FAILED）
    const history = $("adapter-log-history") as HTMLSelectElement;
    expect(history.options.length).toBe(3);
    const failedId = "00000000-0000-4000-8000-000000000912";
    expect(Array.from(history.options).some((o) => o.value === failedId)).toBe(true);

    fireEvent.change(history, { target: { value: failedId } });
    await waitFor(() =>
      expect($("adapter-log-sync-id")!.textContent).toContain("000000000912"),
    );
    const failedStats = $("adapter-log-stats")!;
    expect(failedStats.textContent).toContain("210");
    expect($("adapter-log-failed-row")).not.toBeNull();
    expect($("adapter-log-timeline")!.textContent).toContain("同步失败");
  });

  it("刷新按钮 → 重拉清单（请求计数 +1）", async () => {
    let listCalls = 0;
    server.use(
      http.get("*/api/v1/admin/adapters", ({ request }) => {
        // 保留演示数据（覆盖仅为计数）
        void request;
        listCalls += 1;
        return HttpResponse.json({
          items: [
            { adapter: "erp", mode: "mock", status: "运行中", health: "OK", last_sync: "2026-09-28T08:18:00.000Z", access: "REST 拉取", team: "数据平台组", health_pct: 99.9 },
          ],
          next_cursor: null,
          total: 1,
        });
      }),
    );
    renderAdapters();
    await waitFor(() => expect(listCalls).toBeGreaterThanOrEqual(1));
    const before = listCalls;
    fireEvent.click(btn("adapters-refresh"));
    await waitFor(() => expect(listCalls).toBeGreaterThan(before));
  });

  it("T50 编辑：注册系统 → 行出现编辑按钮 → 弹窗预填 → 保存 PUT → 关闭", async () => {
    renderAdapters();
    await waitFor(() => expect(rows().length).toBe(5));

    // 注册（新增弹窗：DB_PULL 通道 + DSN + 结构化表配置）
    fireEvent.click(btn("adapter-add"));
    await waitFor(() => expect($("adapter-create-form")).not.toBeNull());
    fireEvent.change(input("adapter-name"), { target: { value: "spc-edit" } });
    fireEvent.change(select("adapter-channel"), { target: { value: "DB_PULL" } });
    fireEvent.change(input("adapter-dsn"), { target: { value: "postgresql://u:p@h:5432/db" } });
    fireEvent.click(btn("table-spec-add"));
    fireEvent.change(input("table-spec-table-0"), { target: { value: "scm_material" } });
    fireEvent.change(input("table-spec-increment-0"), { target: { value: "update_time" } });
    fireEvent.change(input("table-spec-excluded-0"), { target: { value: "contact_phone, fax" } });
    fireEvent.click(btn("modal-form-submit"));
    await waitFor(() => expect($("adapter-edit-spc-edit")).not.toBeNull());

    // 打开编辑弹窗 → 预填（名称只读 + DSN + 逐表行回显）
    fireEvent.click(btn("adapter-edit-spc-edit"));
    await waitFor(() => expect($("adapter-edit-form")).not.toBeNull());
    await waitFor(() => expect(input("adapter-edit-name").value).toBe("spc-edit"));
    expect(input("adapter-edit-dsn").value).toContain("postgresql://");
    expect(input("table-spec-table-0").value).toBe("scm_material");
    expect(input("table-spec-increment-0").value).toBe("update_time");
    expect(input("table-spec-excluded-0").value).toContain("contact_phone");

    // 修改 DSN → 保存 → 弹窗关闭
    fireEvent.change(input("adapter-edit-dsn"), { target: { value: "postgresql://u:p@h:5432/db2" } });
    fireEvent.click(btn("modal-form-submit"));
    await waitFor(() => expect($("adapter-edit-form")).toBeNull());
  });

  it("T50 删除：危险确认 → DELETE → 行移除", async () => {
    renderAdapters();
    await waitFor(() => expect(rows().length).toBe(5));

    fireEvent.click(btn("adapter-add"));
    await waitFor(() => expect($("adapter-create-form")).not.toBeNull());
    fireEvent.change(input("adapter-name"), { target: { value: "spc-del" } });
    fireEvent.change(select("adapter-channel"), { target: { value: "DB_PULL" } });
    fireEvent.change(input("adapter-dsn"), { target: { value: "postgresql://u:p@h:5432/db" } });
    fireEvent.click(btn("table-spec-add"));
    fireEvent.change(input("table-spec-table-0"), { target: { value: "scm_material" } });
    fireEvent.click(btn("modal-form-submit"));
    await waitFor(() => expect($("adapter-delete-spc-del")).not.toBeNull());

    fireEvent.click(btn("adapter-delete-spc-del"));
    await waitFor(() => expect(btn("danger-confirm")).toBeTruthy());
    fireEvent.click(btn("danger-confirm"));
    await waitFor(() => expect($("adapter-row-spc-del")).toBeNull());
  });

  it("T50 未配置行：REST 注册 → 清单出现（未配置 pill、无测试/日志按钮、可编辑）", async () => {
    renderAdapters();
    await waitFor(() => expect(rows().length).toBe(5));

    fireEvent.click(btn("adapter-add"));
    await waitFor(() => expect($("adapter-create-form")).not.toBeNull());
    fireEvent.change(input("adapter-name"), { target: { value: "rest-plain" } });
    fireEvent.change(input("adapter-endpoint"), { target: { value: "https://x/api" } });
    fireEvent.click(btn("modal-form-submit"));

    // 行出现：未配置 pill；测试连接/日志不显示；编辑可点
    await waitFor(() => expect($("adapter-row-rest-plain")).not.toBeNull());
    expect($("adapter-row-rest-plain")!.textContent).toContain("未配置");
    expect(document.querySelector('[data-dom-id="adapter-test-rest-plain"]')).toBeNull();
    expect(document.querySelector('[data-dom-id="adapter-log-rest-plain"]')).toBeNull();
    expect(btn("adapter-edit-rest-plain")).toBeTruthy();
  });

  // EDP-601 空态收口：空清单 → 三件套 + 语境动作（新增适配器/数据源连接向导）
  it("空清单：空态三件套（新增适配器 / 数据源连接向导动作）", async () => {
    server.use(
      http.get("*/api/v1/admin/adapters", () =>
        HttpResponse.json({ items: [], next_cursor: null, total: 0 }),
      ),
    );
    renderAdapters();

    await waitFor(() => expect($("adapters-empty")).not.toBeNull());
    expect($("adapters-empty")!.textContent).toContain("暂无适配器");
    expect($("adapters-empty")!.textContent).toContain("新增适配器");
    expect($("adapters-empty")!.textContent).toContain("数据源连接向导");
    expect($("adapters-table")).toBeNull();
  });
});
