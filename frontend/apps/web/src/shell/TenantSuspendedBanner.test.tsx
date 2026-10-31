import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useSessionStore } from "../features/auth/session-store";
import { notifyTenantSuspended, TenantSuspendedBanner } from "./TenantSuspendedBanner";

function renderBanner() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <TenantSuspendedBanner />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  useSessionStore.getState().clearSession();
});

describe("TenantSuspendedBanner 常驻横幅", () => {
  it("初始不渲染；notifyTenantSuspended() 后出现且带 data-dom-id；点知道了后消失", async () => {
    renderBanner();
    expect(document.querySelector('[data-dom-id="tenant-suspended-banner"]')).toBeNull();

    act(() => {
      notifyTenantSuspended();
    });

    expect(await screen.findByText("当前租户已暂停，请联系平台管理员")).toBeInTheDocument();
    expect(document.querySelector('[data-dom-id="tenant-suspended-banner"]')).not.toBeNull();

    fireEvent.click(screen.getByText("知道了"));

    expect(screen.queryByText("当前租户已暂停，请联系平台管理员")).toBeNull();
    expect(document.querySelector('[data-dom-id="tenant-suspended-banner"]')).toBeNull();
  });

  it("关闭后再次 notify 可重新点亮", async () => {
    renderBanner();
    act(() => {
      notifyTenantSuspended();
    });
    expect(await screen.findByText("当前租户已暂停，请联系平台管理员")).toBeInTheDocument();
    fireEvent.click(screen.getByText("知道了"));
    expect(screen.queryByText("当前租户已暂停，请联系平台管理员")).toBeNull();

    act(() => {
      notifyTenantSuspended();
    });

    expect(await screen.findByText("当前租户已暂停，请联系平台管理员")).toBeInTheDocument();
  });
});
