import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
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
      username: "manager1",
      roles: ["MANAGER"],
      is_platform_admin: false,
    },
  };
}

function renderProfile() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(routes, { initialEntries: ["/profile"] });
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

const $ = (id: string) => document.querySelector(`[data-dom-id="${id}"]`) as HTMLElement;
const input = (id: string) => $(id) as HTMLInputElement;
const btn = (id: string) => $(id) as HTMLButtonElement;

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(() => {
  useSessionStore.getState().setSession(sessionOf());
});

describe("ProfilePage 个人设置（MSW 模式渲染路由）", () => {
  it("展示当前用户资料与会话信息（/me）", async () => {
    renderProfile();
    await waitFor(() => expect(input("profile-username").value).toBe("manager1"));
    expect(input("profile-display-name").value).toBe("演示经理");
    expect(input("profile-email").value).toBe("manager1@edp.local");
    expect($("profile-roles").textContent).toContain("MANAGER");
    expect($("profile-permissions").textContent).toContain("events:read");
  });

  it("保存个人资料：PUT /auth/profile → 成功提示", async () => {
    renderProfile();
    await waitFor(() => expect(input("profile-username").value).toBe("manager1"));
    fireEvent.change(input("profile-display-name"), { target: { value: "新名字" } });
    fireEvent.click(btn("profile-save"));
    await waitFor(() => {
      expect(document.body.textContent).toContain("个人资料已保存");
    });
  });

  it("修改密码：确认不一致行内报错；旧密错误回显 401 文案", async () => {
    renderProfile();
    await waitFor(() => expect(input("profile-username").value).toBe("manager1"));

    // 两次新密码不一致 → 行内错误
    fireEvent.change(input("profile-old-password"), { target: { value: "Admin@123!" } });
    fireEvent.change(input("profile-new-password"), { target: { value: "NewPass@2026!" } });
    fireEvent.change(input("profile-confirm-password"), { target: { value: "Different@1!" } });
    fireEvent.click(btn("profile-password-submit"));
    await waitFor(() =>
      expect($("profile-password-error")?.textContent ?? "").toContain("不一致"),
    );

    // 旧密错误 → 后端 401 文案
    fireEvent.change(input("profile-old-password"), { target: { value: "Wrong@123!" } });
    fireEvent.change(input("profile-confirm-password"), { target: { value: "NewPass@2026!" } });
    fireEvent.click(btn("profile-password-submit"));
    await waitFor(() =>
      expect($("profile-password-error")?.textContent ?? "").toContain("旧密码不正确"),
    );
  });

  it("修改密码成功：提示 + 清空表单", async () => {
    renderProfile();
    await waitFor(() => expect(input("profile-username").value).toBe("manager1"));
    fireEvent.change(input("profile-old-password"), { target: { value: "Admin@123!" } });
    fireEvent.change(input("profile-new-password"), { target: { value: "NewPass@2026!" } });
    fireEvent.change(input("profile-confirm-password"), { target: { value: "NewPass@2026!" } });
    fireEvent.click(btn("profile-password-submit"));
    await waitFor(() => {
      expect(document.body.textContent).toContain("密码已更新");
    });
    expect(input("profile-old-password").value).toBe("");
    expect(input("profile-new-password").value).toBe("");
  });

  it("主题切换：深色/浅色切换应用 documentElement class", async () => {
    renderProfile();
    await waitFor(() => expect(btn("profile-theme-dark")).toBeTruthy());
    fireEvent.click(btn("profile-theme-dark"));
    await waitFor(() => {
      expect(document.documentElement.classList.contains("dark")).toBe(true);
    });
    fireEvent.click(btn("profile-theme-light"));
    await waitFor(() => {
      expect(document.documentElement.classList.contains("dark")).toBe(false);
    });
  });
});
