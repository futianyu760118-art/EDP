import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { ThemeProvider } from "../../app/providers/ThemeProvider";
import { server } from "../../mocks/server";
import { SESSION_STORAGE_KEY, useSessionStore } from "./session-store";
import { LoginPage } from "./LoginPage";

function renderLogin() {
  const router = createMemoryRouter(
    [
      { path: "/login", element: <LoginPage /> },
      { path: "/admin/overview", element: <div>OVERVIEW_OK</div> },
    ],
    { initialEntries: ["/login"] },
  );
  render(
    <ThemeProvider>
      <RouterProvider router={router} />
    </ThemeProvider>,
  );
  return router;
}

function fillAndSubmit(username: string, password: string) {
  fireEvent.change(document.querySelector('[data-dom-id="login-username"]')!, {
    target: { value: username },
  });
  fireEvent.change(document.querySelector('[data-dom-id="login-password"]')!, {
    target: { value: password },
  });
  fireEvent.click(document.querySelector('[data-dom-id="login-submit"]')!);
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(() => {
  useSessionStore.getState().clearSession();
  localStorage.removeItem(SESSION_STORAGE_KEY);
});

describe("LoginPage 登录流程（MSW 拦截 /api/v1/auth/login）", () => {
  it("manager1 登录成功：session 入 store + persist，跳转 /admin/overview", async () => {
    const router = renderLogin();
    fillAndSubmit("manager1", "whatever");

    expect(await screen.findByText("OVERVIEW_OK")).toBeInTheDocument();
    expect(useSessionStore.getState().accessToken).toBe("mock-access-manager1");
    expect(useSessionStore.getState().user?.username).toBe("manager1");
    expect(router.state.location.pathname).toBe("/admin/overview");

    const persisted = JSON.parse(localStorage.getItem(SESSION_STORAGE_KEY) ?? "{}");
    expect(persisted.state?.user?.username).toBe("manager1");
    expect(persisted.state?.tenant?.slug).toBe("default");
  });

  it("admin 密码错误（专用错误分支）：401 错误横幅文案，停留登录页", async () => {
    renderLogin();
    fillAndSubmit("admin", "wrong-password");

    await waitFor(() => {
      expect(document.querySelector('[data-dom-id="login-error"]')).not.toBeNull();
    });
    expect(screen.getByText("用户名或密码错误")).toBeInTheDocument();
    expect(document.querySelector('[data-dom-id="login-username"]')).not.toBeNull();
    expect(useSessionStore.getState().accessToken).toBeNull();
  });
});
