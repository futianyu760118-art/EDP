import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { http, HttpResponse } from "msw";
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

function renderRegistry() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: ["/admin/registry"] });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

function cards(): NodeListOf<HTMLElement> {
  return document.querySelectorAll('[data-dom-id="object-card"]');
}

async function openCreateModal() {
  fireEvent.click(document.querySelector('[data-dom-id="obj-register"]')!);
  expect(await screen.findByText("注册业务对象")).toBeInTheDocument();
}

function fillForm({ name = "客户主数据（华东）", code = "CUST-MASTER-001" } = {}) {
  fireEvent.change(screen.getByPlaceholderText("例如：客户主数据"), { target: { value: name } });
  fireEvent.change(screen.getByPlaceholderText("例如：CUST-MASTER-001"), { target: { value: code } });
  fireEvent.change(document.querySelector('[data-dom-id="create-object-domain"]')!, {
    target: { value: "master" },
  });
  fireEvent.click(screen.getByLabelText("ERP-S4"));
}

function submit() {
  fireEvent.click(screen.getByRole("button", { name: /创建对象/ }));
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(() => {
  useSessionStore.getState().setSession(sessionOf("manager1", ["MANAGER"]));
});

describe("CreateObjectModal 行内校验与提交（MSW 模式渲染路由）", () => {
  it("空提交 → 三条行内错误逐字 + 所属域提示；取消关闭弹窗", async () => {
    renderRegistry();
    await waitFor(() => expect(cards().length).toBe(20));
    await openCreateModal();

    submit();
    expect(await screen.findByText("对象名称不能为空，且不能与已有对象重复")).toBeInTheDocument();
    expect(screen.getByText("对象编码不能为空")).toBeInTheDocument();
    expect(screen.getByText("请至少选择一个数据来源")).toBeInTheDocument();
    // 所属域提示（排除 select 的同名 placeholder option）
    expect(
      screen.getAllByText("请选择所属域").filter((el) => el.tagName !== "OPTION"),
    ).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    await waitFor(() => expect(screen.queryByText("注册业务对象")).toBeNull());
  });

  it("合法提交 → POST /objects 请求体关键字段（MASTER/join 来源）+ 成功 toast + 弹窗关闭", async () => {
    const bodies: Record<string, unknown>[] = [];
    server.use(
      http.post("*/api/v1/objects", async ({ request }) => {
        bodies.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(
          {
            object_id: "00000000-0000-4000-8000-00000000beef",
            revision: 1,
            status: "ACTIVE",
            created_at: "2026-09-16T00:00:00Z",
          },
          { status: 201 },
        );
      }),
    );
    renderRegistry();
    await waitFor(() => expect(cards().length).toBe(20));
    await openCreateModal();

    fillForm();
    fireEvent.click(screen.getByLabelText("MDM"));
    fireEvent.change(screen.getByPlaceholderText("例如：张三"), { target: { value: "张三" } });
    fireEvent.change(screen.getByPlaceholderText("补充对象的业务说明、使用场景或关联规则…"), {
      target: { value: "客户主数据登记" },
    });
    submit();

    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({
      object_type: "MASTER",
      owner_domain: "master",
      source_system: "ERP-S4,MDM",
      source_id: "CUST-MASTER-001",
      attributes: {
        name: "客户主数据（华东）",
        owner: "张三",
        description: "客户主数据登记",
        sources: ["ERP-S4", "MDM"],
      },
    });
    expect(await screen.findByText("对象已创建")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("注册业务对象")).toBeNull());
  });

  it("409 CONFLICT → 编码字段行内「对象编码已存在，请更换」", async () => {
    server.use(
      http.post("*/api/v1/objects", () =>
        HttpResponse.json(
          { error: { code: "CONFLICT", message: "版本冲突：对象已被修改", request_id: "mock" } },
          { status: 409 },
        ),
      ),
    );
    renderRegistry();
    await waitFor(() => expect(cards().length).toBe(20));
    await openCreateModal();

    fillForm();
    submit();

    expect(await screen.findByText("对象编码已存在，请更换")).toBeInTheDocument();
    expect(screen.getByText("注册业务对象")).toBeInTheDocument();
  });

  it("VALIDATION_ERROR → 通用行内展示后端 message", async () => {
    server.use(
      http.post("*/api/v1/objects", () =>
        HttpResponse.json(
          { error: { code: "VALIDATION_ERROR", message: "owner_domain 不合法", request_id: "mock" } },
          { status: 400 },
        ),
      ),
    );
    renderRegistry();
    await waitFor(() => expect(cards().length).toBe(20));
    await openCreateModal();

    fillForm();
    submit();

    expect(await screen.findByText("owner_domain 不合法")).toBeInTheDocument();
  });

  // 走真实 registry handler（会话内 store 落库）：放最后，避免污染前序用例计数
  it("真实 201 → invalidate objects → 新对象卡出现在列表首位", async () => {
    renderRegistry();
    await waitFor(() => expect(cards().length).toBe(20));
    await openCreateModal();

    fillForm({ name: "端到端客户主数据", code: "CUST-E2E-9001" });
    submit();

    expect(await screen.findByText("端到端客户主数据")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("注册业务对象")).toBeNull());
  });
});
