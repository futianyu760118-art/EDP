import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { EventsTimeline } from "./EventsTimeline";
import { server } from "../../mocks/server";

function renderTimeline() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <EventsTimeline />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("EventsTimeline 事件与闭环", () => {
  it("面板标题「事件与闭环」与「进入事件流 →」链接指向 /admin/events", async () => {
    renderTimeline();

    expect(await screen.findByText("事件与闭环")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "进入事件流 →" });
    expect(link).toHaveAttribute("href", "/admin/events");
  });

  it("fixtures 最近 5 条事件渲染 5 节点，最新一条为 adapter.sync.failed（18 分钟前）", async () => {
    renderTimeline();

    await waitFor(() => {
      expect(document.querySelectorAll('[data-dom-id="overview-events-list"] span.absolute')).toHaveLength(5);
    });
    expect(screen.getByText("adapter.sync.failed")).toBeInTheDocument();
    expect(screen.getByText(/ · edp-adapter$/)).toBeInTheDocument();
  });
});
