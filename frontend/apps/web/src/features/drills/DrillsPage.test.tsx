import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "../../app/providers/ThemeProvider";
import { routes } from "../../app/router";
import { useSessionStore, type AuthTokenResponse } from "../auth/session-store";
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

function renderDrills() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: ["/admin/drills"] });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

const card = (id: string) => document.querySelector(`[data-dom-id="${id}"]`);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  vi.unstubAllEnvs();
});
afterAll(() => server.close());
beforeEach(() => {
  useSessionStore.getState().setSession(sessionOf());
});

describe("DrillsPage 演练回放（MSW 模式渲染路由）", () => {
  it("三卡渲染：中文名映射；SUCCEEDED 卡 RTO/RPO 数字 + readings 键值 + 绿 pill；PLANNED 卡「—」+「未执行」+ 灰 pill", async () => {
    renderDrills();

    await waitFor(() => expect(card("drills-card-switchover")).not.toBeNull());

    // drill_type → 中文名映射 + mono 小字
    expect(card("drills-card-switchover")!.textContent).toContain("主备切换");
    expect(card("drills-card-switchover-type")!.textContent).toBe("switchover");
    expect(card("drills-card-pitr")!.textContent).toContain("整库 PITR 恢复");
    expect(card("drills-card-tenant_restore")!.textContent).toContain("租户级恢复");
    expect(card("drills-card-tenant_restore-type")!.textContent).toBe("tenant_restore");

    // SUCCEEDED 卡：RTO/RPO 实测数字 + 绿 pill + readings 键值 + 拓扑 + 手册
    expect(card("drills-card-switchover-rto")!.textContent).toContain("0 秒");
    // T9（W5-21-b）：switchover rto=0 加注「healthz 零中断口径，DB 写面见 readings」
    expect(card("drills-card-switchover-rto-note")!.textContent).toContain(
      "healthz 零中断口径，DB 写面见 readings",
    );
    expect(card("drills-card-switchover-rpo")!.textContent).toContain("0 ms");
    expect(card("drills-card-switchover-pill")!.querySelector("span")!.className).toContain(
      "bg-state-success",
    );
    const readings = card("drills-card-switchover-readings")!;
    expect(readings.textContent).toContain("切换成功率");
    expect(readings.textContent).toContain("2/2（pg1→pg2→pg1 双向往返）");
    expect(readings.textContent).toContain("80/80 全 200");
    expect(card("drills-card-switchover")!.textContent).toContain(
      "etcd×1 + patroni×2 + haproxy + pgbackrest",
    );
    expect(card("drills-card-switchover-executed")!.textContent).not.toContain("未执行");
    expect(card("drills-card-switchover-manual")!.textContent).toContain(
      "手册：docs/demo/w5-drills.md",
    );

    // pitr/tenant_restore（W6 T15 回填实测，fixtures 对齐真文件）：SUCCEEDED 数字 + 绿 pill + readings 非空
    expect(card("drills-card-pitr-rto")!.textContent).toContain("22.1 秒");
    expect(card("drills-card-pitr-rpo")!.textContent).toContain("0 ms");
    expect(card("drills-card-pitr-pill")!.querySelector("span")!.className).toContain(
      "bg-state-success",
    );
    expect(card("drills-card-pitr-readings")!.textContent).toContain("恢复备份集");
    expect(card("drills-card-pitr-executed")!.textContent).not.toContain("未执行");
    expect(card("drills-card-tenant_restore-rto")!.textContent).toContain("23.8 秒");
    expect(card("drills-card-tenant_restore-readings")!.textContent).toContain("误删范围");
    expect(card("drills-card-tenant_restore-manual")!.textContent).toContain(
      "手册：docs/demo/w5-drills.md",
    );
  });

  it("PLANNED 卡（未执行）：数字「—」+ 灰 pill + readings 区块隐藏", async () => {
    server.use(
      http.get("*/api/v1/admin/drills", () =>
        HttpResponse.json({
          items: [
            {
              drill_type: "pitr",
              executed_at: null,
              topology: "etcd×1 + patroni×2 + pgbackrest(repo=MinIO S3)",
              rto_seconds: null,
              rpo_seconds: null,
              result: "PLANNED",
              readings: {},
              manual_url: "docs/demo/w5-drills.md",
            },
          ],
        }),
      ),
    );
    renderDrills();

    await waitFor(() => expect(card("drills-card-pitr")).not.toBeNull());
    expect(card("drills-card-pitr-rto")!.textContent).toContain("—");
    expect(card("drills-card-pitr-rpo")!.textContent).toContain("—");
    expect(card("drills-card-pitr-executed")!.textContent).toContain("未执行");
    expect(card("drills-card-pitr-pill")!.querySelector("span")!.className).toContain("bg-muted");
    expect(card("drills-card-pitr-readings")).toBeNull();
  });

  it("空 items：空态三件套", async () => {
    server.use(
      http.get("*/api/v1/admin/drills", () => HttpResponse.json({ items: [] })),
    );
    renderDrills();

    await waitFor(() => expect(card("drills-empty")).not.toBeNull());
    expect(card("drills-empty")!.textContent).toContain("暂无演练记录");
    expect(card("drills-empty")!.textContent).toContain("演练记录尚未生成");
    expect(card("drills-card-switchover")).toBeNull();
  });

  it("千分位格式化：rto_seconds=1234 → 「1,234 秒」；rpo_seconds=2 → 「2,000 ms」", async () => {
    server.use(
      http.get("*/api/v1/admin/drills", () =>
        HttpResponse.json({
          items: [
            {
              drill_type: "switchover",
              executed_at: "2026-09-18T08:19:22+08:00",
              topology: "etcd×1 + patroni×2 + pgbackrest",
              rto_seconds: 1234,
              rpo_seconds: 2,
              result: "SUCCEEDED",
              readings: {},
              manual_url: "docs/demo/w5-drills.md",
            },
          ],
        }),
      ),
    );
    renderDrills();

    await waitFor(() => expect(card("drills-card-switchover-rto")).not.toBeNull());
    expect(card("drills-card-switchover-rto")!.textContent).toContain("1,234 秒");
    expect(card("drills-card-switchover-rpo")!.textContent).toContain("2,000 ms");
    // rto≠0 → 零中断加注不渲染
    expect(card("drills-card-switchover-rto-note")).toBeNull();
  });
});
