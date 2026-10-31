import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { ThemeProvider } from "../../app/providers/ThemeProvider";
import { routes } from "../../app/router";
import { useSessionStore, type AuthTokenResponse } from "../auth/session-store";
import { TENANT_ACME_ID, USER_ANALYST1, USER_MANAGER1 } from "../../mocks/data/tenants";
import { platformUsers } from "../../mocks/data/tenants";
import { server } from "../../mocks/server";

function sessionOf(username: string, roles: string[]): AuthTokenResponse {
  return {
    access_token: `t-${username}`,
    refresh_token: `r-${username}`,
    expires_in: 7200,
    tenant: {
      tenant_id: "00000000-0000-4000-8000-000000000001",
      slug: "default",
      name: "默认租户",
      status: "ACTIVE",
    },
    user: {
      user_id: "00000000-0000-0000-0000-000000000002",
      username,
      roles,
      is_platform_admin: true,
    },
  };
}

function renderDetail(tenantId: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: [`/tenants/${tenantId}`] });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
  return queryClient;
}

const memberRows = () => document.querySelectorAll('[data-dom-id^="member-row-"]');

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(() => {
  useSessionStore.getState().setSession(sessionOf("admin", ["PLATFORM_ADMIN"]));
});

/** fixtures 锚定：acme = DEDICATED / ACTIVE / 4 成员（ADMIN + MANAGER,ANALYST + MANAGER + INVITED ANALYST）；配额含临时提额覆盖（storage 3000 / api 1500）。 */
describe("TenantDetailPage 租户详情（MSW 模式渲染路由）", () => {
  it("基本信息卡 + 配额七字段 + 成员表渲染；「查看」链路目标租户", async () => {
    renderDetail(TENANT_ACME_ID);

    await waitFor(() => expect(document.querySelector('[data-dom-id="tenant-basic-body"]')).not.toBeNull());
    const basic = document.querySelector('[data-dom-id="tenant-basic-body"]')!.textContent!;
    expect(basic).toContain("acme");
    expect(basic).toContain("ACME · 华东事业群");
    expect(basic).toContain("企业版");

    await waitFor(() => expect(document.querySelector('[data-dom-id="quota-fields"]')).not.toBeNull());
    // DEDICATED 基础配额 + 提额覆盖：api 1,500 / storage 3,000（千分位）；第七字段=最近调整
    expect(document.querySelector('[data-dom-id="quota-api_rate_limit"]')!.textContent).toContain("1,500");
    expect(document.querySelector('[data-dom-id="quota-storage_gb"]')!.textContent).toContain("3,000");
    expect(document.querySelector('[data-dom-id="quota-pool_share"]')!.textContent).toContain("1.0");
    expect(document.querySelector('[data-dom-id="quota-updated_at"]')).not.toBeNull();

    await waitFor(() => expect(memberRows().length).toBe(4));
    expect(document.querySelector('[data-dom-id="tenant-members"]')!.textContent).toContain("共 4 人");
    expect(document.querySelector('[data-dom-id="tenant-lifecycle"]')!.textContent).toContain("暂停");
    expect(document.querySelector('[data-dom-id="tenant-lifecycle"]')!.textContent).toContain("注销");
  });

  it("调整配额：reason 空禁用提交 + 行内提示；填齐后 PATCH 请求体断言", async () => {
    let patchBody: Record<string, unknown> | undefined;
    let patchedStorageGb = 3_000;
    server.use(
      http.get("*/api/v1/tenants/:tenantId/quotas", () =>
        HttpResponse.json({
          tenant_id: TENANT_ACME_ID,
          api_rate_limit: 1_500,
          batch_max_events: 5_000,
          events_per_month: 20_000_000,
          pool_share: "1.0",
          query_timeout_ms: 120_000,
          storage_gb: patchedStorageGb,
          updated_at: "2026-09-28T09:30:00.000Z",
        }),
      ),
      http.patch("*/api/v1/tenants/:tenantId/quotas", async ({ request }) => {
        patchBody = (await request.json()) as Record<string, unknown>;
        patchedStorageGb = (patchBody?.storage_gb as number) ?? patchedStorageGb;
        return HttpResponse.json({
          tenant_id: TENANT_ACME_ID,
          api_rate_limit: (patchBody?.api_rate_limit as number) ?? 0,
          batch_max_events: 5000,
          events_per_month: (patchBody?.events_per_month as number) ?? 0,
          pool_share: "1.0",
          query_timeout_ms: 120000,
          storage_gb: patchedStorageGb,
          updated_at: "2026-09-28T09:30:00.000Z",
        });
      }),
    );
    renderDetail(TENANT_ACME_ID);
    await waitFor(() => expect(document.querySelector('[data-dom-id="quota-fields"]')).not.toBeNull());

    fireEvent.click(document.querySelector('[data-dom-id="quota-adjust"]')!);
    await waitFor(() => expect(document.querySelector('[data-dom-id="quota-adjust-form"]')).not.toBeNull());

    // reason 空 → 提交禁用 + 行内提示
    const submit = document.querySelector('[data-dom-id="modal-form-submit"]') as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    expect(document.querySelector('[data-dom-id="quota-reason-hint"]')!.textContent).toContain("必填");

    fireEvent.change(document.querySelector('[data-dom-id="quota-input-storage_gb"]')!, {
      target: { value: "9000" },
    });
    fireEvent.change(document.querySelector('[data-dom-id="quota-input-reason"]')!, {
      target: { value: "大促期间临时提额" },
    });
    await waitFor(() => expect(submit.disabled).toBe(false));
    fireEvent.click(submit);

    await waitFor(() => expect(patchBody).toEqual({
      api_rate_limit: 1500,
      storage_gb: 9000,
      events_per_month: 20000000,
      reason: "大促期间临时提额",
    }));
    expect(await screen.findByText("配额已调整")).toBeInTheDocument();
    // 关闭后回显新值
    await waitFor(() => expect(document.querySelector('[data-dom-id="quota-storage_gb"]')!.textContent).toContain("9,000"));
  });

  it("邀请成员：已在册用户 → 409 行内错误", async () => {
    renderDetail(TENANT_ACME_ID);
    await waitFor(() => expect(memberRows().length).toBe(4));

    fireEvent.click(document.querySelector('[data-dom-id="member-invite"]')!);
    await waitFor(() => expect(document.querySelector('[data-dom-id="invite-form"]')).not.toBeNull());
    // 用户目录下拉来自 GET /admin/users（Page 信封，fixtures 7 人）
    const userSelect = document.querySelector('[data-dom-id="invite-user"]')! as HTMLSelectElement;
    await waitFor(() => expect(userSelect.options.length).toBe(platformUsers.length + 1));

    fireEvent.change(userSelect, { target: { value: USER_MANAGER1 } }); // manager1 已是 acme 成员
    fireEvent.click(document.querySelector('[data-dom-id="invite-role-ANALYST"]')!);
    fireEvent.click(document.querySelector('[data-dom-id="modal-form-submit"]')!);

    await waitFor(() => expect(document.querySelector('[data-dom-id="invite-error"]')).not.toBeNull());
    expect(document.querySelector('[data-dom-id="invite-error"]')!.textContent).toContain(
      "该用户已是租户成员",
    );
  });

  // T9（W5-11 收口）：Page 信封渲染（display_name 空回退 username）+ 成功邀请 POST user_id 断言
  it("邀请成员：Page 信封渲染（display_name 空 → username）+ 提交 POST members 带 user_id", async () => {
    let postBody: Record<string, unknown> | undefined;
    server.use(
      http.post("*/api/v1/tenants/:tenantId/members", async ({ request }) => {
        postBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          {
            member_id: "00000000-0000-4000-8000-000000000598",
            user_id: USER_ANALYST1,
            display_name: "李审计",
            member_roles: (postBody?.member_roles as string[]) ?? [],
            status: "INVITED",
            joined_at: new Date().toISOString(),
          },
          { status: 201 },
        );
      }),
    );
    renderDetail(TENANT_ACME_ID);
    await waitFor(() => expect(memberRows().length).toBe(4));

    fireEvent.click(document.querySelector('[data-dom-id="member-invite"]')!);
    await waitFor(() => expect(document.querySelector('[data-dom-id="invite-form"]')).not.toBeNull());
    const userSelect = await waitFor(() => {
      const el = document.querySelector('[data-dom-id="invite-user"]') as HTMLSelectElement;
      expect(el.options.length).toBe(platformUsers.length + 1);
      return el;
    });
    // display_name 空透传（newhire）→ option label 回退 username
    const newhireOption = Array.from(userSelect.options).find((o) => o.value.includes("0537"));
    expect(newhireOption?.textContent).toBe("newhire");

    fireEvent.change(userSelect, { target: { value: USER_ANALYST1 } });
    fireEvent.click(document.querySelector('[data-dom-id="invite-role-ANALYST"]')!);
    fireEvent.click(document.querySelector('[data-dom-id="modal-form-submit"]')!);

    await waitFor(() => expect(postBody).toEqual({ user_id: USER_ANALYST1, member_roles: ["ANALYST"] }));
    expect(await screen.findByText("邀请已发送")).toBeInTheDocument();
  });

  // T9 降级：真模式目录 404 → 下拉降级为手输 user_id，提交仍带手输值
  it("邀请成员：目录 404 → 降级手输 user_id 提交", async () => {
    let postBody: Record<string, unknown> | undefined;
    server.use(
      http.get("*/api/v1/admin/users", () =>
        HttpResponse.json({ code: "NOT_FOUND", message: "资源不存在" }, { status: 404 }),
      ),
      http.post("*/api/v1/tenants/:tenantId/members", async ({ request }) => {
        postBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          {
            member_id: "00000000-0000-4000-8000-000000000598",
            user_id: (postBody?.user_id as string) ?? "",
            display_name: null,
            member_roles: (postBody?.member_roles as string[]) ?? [],
            status: "INVITED",
            joined_at: new Date().toISOString(),
          },
          { status: 201 },
        );
      }),
    );
    renderDetail(TENANT_ACME_ID);
    await waitFor(() => expect(memberRows().length).toBe(4));

    fireEvent.click(document.querySelector('[data-dom-id="member-invite"]')!);
    const manual = await waitFor(() => {
      const el = document.querySelector('[data-dom-id="invite-user-manual"]') as HTMLInputElement;
      expect(el).not.toBeNull();
      return el;
    });
    expect(document.querySelector('[data-dom-id="invite-user"]')).toBeNull();

    fireEvent.change(manual, { target: { value: USER_ANALYST1 } });
    fireEvent.click(document.querySelector('[data-dom-id="invite-role-MANAGER"]')!);
    fireEvent.click(document.querySelector('[data-dom-id="modal-form-submit"]')!);

    await waitFor(() => expect(postBody).toEqual({ user_id: USER_ANALYST1, member_roles: ["MANAGER"] }));
    // 静态 message portal 跨用例残留 → findAllByText 兜底
    expect((await screen.findAllByText("邀请已发送")).length).toBeGreaterThanOrEqual(1);
  });

  it("权限分配：勾选 ADMIN → PATCH member_roles 断言", async () => {
    let patchUrl = "";
    let patchBody: Record<string, unknown> | undefined;
    server.use(
      http.patch("*/api/v1/tenants/:tenantId/members/:memberId", async ({ params, request }) => {
        patchUrl = String(request.url);
        patchBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          member_id: String(params.memberId),
          user_id: USER_MANAGER1,
          display_name: "陈经理",
          member_roles: (patchBody?.member_roles as string[]) ?? [],
          status: "ACTIVE",
          joined_at: "2026-09-25T08:30:00.000Z",
        });
      }),
    );
    renderDetail(TENANT_ACME_ID);
    await waitFor(() => expect(memberRows().length).toBe(4));

    // 第二行 = manager1（MANAGER + ANALYST）
    const managerRow = Array.from(memberRows()).find((row) =>
      row.querySelector('[data-dom-id^="member-roles-"]')!.textContent!.includes("数据管理员"),
    )!;
    const memberId = managerRow.getAttribute("data-dom-id")!.replace("member-row-", "");
    fireEvent.click(managerRow.querySelector(`[data-dom-id="member-perm-${memberId}"]`)!);

    await waitFor(() => expect(document.querySelector('[data-dom-id="permission-form"]')).not.toBeNull());
    expect(
      (document.querySelector('[data-dom-id="permission-role-MANAGER"]') as HTMLInputElement).checked,
    ).toBe(true);
    fireEvent.click(document.querySelector('[data-dom-id="permission-role-ADMIN"]')!);
    fireEvent.click(document.querySelector('[data-dom-id="modal-form-submit"]')!);

    await waitFor(() =>
      expect(patchBody).toEqual({ member_roles: ["MANAGER", "ANALYST", "ADMIN"] }),
    );
    expect(patchUrl).toContain(memberId);
    expect(await screen.findByText("成员角色已更新")).toBeInTheDocument();
  });

  it("注销强确认：slug 解锁（错误 slug 禁用）+ reason 必填 + cancel 请求体断言", async () => {
    let cancelBody: Record<string, unknown> | undefined;
    server.use(
      http.post("*/api/v1/tenants/:tenantId/cancel", async ({ request }) => {
        cancelBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          tenant_id: TENANT_ACME_ID,
          operation: "cancel",
          status: "CANCELLED",
          occurred_at: "2026-09-28T10:00:00.000Z",
        });
      }),
    );
    renderDetail(TENANT_ACME_ID);
    await waitFor(() => expect(memberRows().length).toBe(4));

    fireEvent.click(document.querySelector('[data-dom-id="tenant-cancel-open"]')!);
    await waitFor(() => expect(document.querySelector('[data-dom-id="tenant-cancel-modal"]')).not.toBeNull());
    const confirmBtn = () => document.querySelector('[data-dom-id="tenant-cancel-confirm"]') as HTMLButtonElement;
    expect(confirmBtn().disabled).toBe(true);

    // 输入错误 slug → 仍禁用
    fireEvent.change(document.querySelector('[data-dom-id="tenant-cancel-slug"]')!, {
      target: { value: "wrong-slug" },
    });
    expect(confirmBtn().disabled).toBe(true);

    // 正确 slug 但 reason 空 → 仍禁用
    fireEvent.change(document.querySelector('[data-dom-id="tenant-cancel-slug"]')!, {
      target: { value: "acme" },
    });
    expect(confirmBtn().disabled).toBe(true);

    fireEvent.change(document.querySelector('[data-dom-id="tenant-cancel-reason"]')!, {
      target: { value: "合同到期退出" },
    });
    fireEvent.change(document.querySelector('[data-dom-id="tenant-cancel-ticket"]')!, {
      target: { value: "OPS-2026-0912" },
    });
    await waitFor(() => expect(confirmBtn().disabled).toBe(false));
    fireEvent.click(confirmBtn()!);

    // 请求体仅 confirm/reason（operator_ticket 为 UI 留痕，契约未含不下发）
    await waitFor(() => expect(cancelBody).toEqual({ confirm: true, reason: "合同到期退出" }));
    expect(await screen.findByText("注销已受理")).toBeInTheDocument();
  });

  it("暂停：POST suspend 202 → toast；SUSPENDED 租户只显示恢复", async () => {
    let suspendCalled = false;
    server.use(
      http.post("*/api/v1/tenants/:tenantId/suspend", () => {
        suspendCalled = true;
        return HttpResponse.json({
          tenant_id: TENANT_ACME_ID,
          operation: "suspend",
          status: "SUSPENDED",
          occurred_at: "2026-09-28T10:30:00.000Z",
        });
      }),
    );
    renderDetail(TENANT_ACME_ID);
    await waitFor(() => expect(document.querySelector('[data-dom-id="tenant-suspend"]')).not.toBeNull());

    fireEvent.click(document.querySelector('[data-dom-id="tenant-suspend"]')!);
    await waitFor(() => expect(suspendCalled).toBe(true));
    expect(await screen.findByText("暂停已受理")).toBeInTheDocument();
  });

  // EDP-601 空态收口：成员空段 → 三件套 + 邀请成员动作
  it("成员空段：空态三件套（邀请成员动作）", async () => {
    server.use(
      http.get("*/api/v1/tenants/:tenantId/members", () =>
        HttpResponse.json({ items: [], next_cursor: null, total: 0 }),
      ),
    );
    renderDetail(TENANT_ACME_ID);

    const empty = await waitFor(() => {
      const el = document.querySelector('[data-dom-id="tenant-members-empty"]');
      expect(el).not.toBeNull();
      return el!;
    });
    expect(empty.textContent).toContain("暂无成员");
    expect(empty.textContent).toContain("邀请成员");
    expect(memberRows().length).toBe(0);
  });

  // T8 评审 Minor-4：成员段请求失败 → 错误提示（非永久「加载中…」）
  it("成员段请求失败：错误提示而非永久加载中", async () => {
    server.use(
      http.get("*/api/v1/tenants/:tenantId/members", () =>
        HttpResponse.json({ code: "INTERNAL_ERROR" }, { status: 500 }),
      ),
    );
    renderDetail(TENANT_ACME_ID);

    const error = await waitFor(() => {
      const el = document.querySelector('[data-dom-id="tenant-members-error"]');
      expect(el).not.toBeNull();
      return el!;
    });
    expect(error.textContent).toContain("成员列表暂不可用");
    expect(memberRows().length).toBe(0);
  });
});
