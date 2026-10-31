import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { findEvent } from "../../mocks/data/events";
import { EVT_ORDER_B_RISK, EVT_ORDER_H_RISK, SYNC_ID } from "../../mocks/data/ids";
import { errorOf } from "../../mocks/lib/http";
import { server } from "../../mocks/server";
import { ReplayWizard } from "./ReplayWizard";

const ORDER_B = findEvent(EVT_ORDER_B_RISK)!;
const ORDER_H = findEvent(EVT_ORDER_H_RISK)!;

const shortOf = (id: string) => `evt-${id.slice(-8)}`;

function renderWizard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <ReplayWizard open events={[ORDER_B, ORDER_H]} onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose };
}

const $ = (id: string) => document.querySelector(`[data-dom-id="${id}"]`) as HTMLElement;
const stepEl = (n: number) => $(`replay-step-${n}`);
const btn = (id: string) => $(id) as HTMLButtonElement;

/** 点击步骤 1 的事件 Radio（data-dom-id 落在 antd Radio 的原生 input 上，按 value 定位）。 */
function pickEvent(id: string) {
  const input = document.querySelector<HTMLInputElement>(
    `[data-dom-id="replay-event-option"][value="${id}"]`,
  );
  expect(input).not.toBeNull();
  fireEvent.click(input!);
}

/** antd Select 交互：mouseDown 打开下拉 → 点击 title 命中的 option。 */
async function chooseAdapter(name: string) {
  fireEvent.mouseDown(screen.getByRole("combobox"));
  const option = await waitFor(() => {
    const el = document.querySelector(`.ant-select-item-option[title="${name}"]`);
    expect(el).not.toBeNull();
    return el as HTMLElement;
  });
  fireEvent.click(option);
}

/** 选中事件 + 前进到步骤 2 + 选适配器（步骤 2「下一步」此时可用）。 */
async function goToStep2(id: string, adapter: string) {
  await waitFor(() => expect(stepEl(1)).not.toBeNull());
  pickEvent(id);
  await waitFor(() => expect(btn("replay-next").disabled).toBe(false));
  fireEvent.click(btn("replay-next"));
  await waitFor(() => expect(stepEl(2)).not.toBeNull());
  await chooseAdapter(adapter);
  await waitFor(() => expect(btn("replay-next").disabled).toBe(false));
}

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("ReplayWizard 回放三步向导（MSW 模式）", () => {
  it("未选事件 → 下一步禁用；选中回显；步骤 1↔2 前进/后退保持选中", async () => {
    renderWizard();

    expect(stepEl(1)).not.toBeNull();
    expect(btn("replay-next").disabled).toBe(true);

    pickEvent(EVT_ORDER_B_RISK);
    await waitFor(() => expect(btn("replay-next").disabled).toBe(false));
    expect($("replay-steps").textContent).toContain(shortOf(EVT_ORDER_B_RISK));

    fireEvent.click(btn("replay-next"));
    await waitFor(() => expect(stepEl(2)).not.toBeNull());
    expect(btn("replay-next").disabled).toBe(true); // 未选适配器 → 不可前进

    fireEvent.click(btn("replay-prev"));
    await waitFor(() => expect(stepEl(1)).not.toBeNull());
    expect(btn("replay-next").disabled).toBe(false); // 选中回显保留
  });

  it("步骤 2 摘要卡与选中事件一致（短 ID/类型/对象/描述/原始发生时间）", async () => {
    renderWizard();
    await waitFor(() => expect(stepEl(1)).not.toBeNull());
    pickEvent(EVT_ORDER_B_RISK);
    await waitFor(() => expect(btn("replay-next").disabled).toBe(false));
    fireEvent.click(btn("replay-next"));
    await waitFor(() => expect(stepEl(2)).not.toBeNull());

    const summary = $("replay-summary");
    expect(summary).not.toBeNull();
    expect(summary.textContent).toContain(shortOf(EVT_ORDER_B_RISK));
    expect(summary.textContent).toContain("订单风险");
    expect(summary.textContent).toContain("SO-2026-00123");
    expect(summary.textContent).toContain("物料X缺口1000");
    expect(summary.textContent).toContain("原始发生时间");
  });

  it("提交 → POST {mode:'replay', since}（202）→ 展示 sync_id/状态；完成关闭", async () => {
    const calls: { adapter: string; body: { mode?: string; since?: string } }[] = [];
    server.use(
      http.post("*/api/v1/admin/adapters/:adapterName/sync", async ({ params, request }) => {
        calls.push({
          adapter: String(params.adapterName),
          body: (await request.json()) as { mode?: string; since?: string },
        });
        return HttpResponse.json(
          { sync_id: SYNC_ID, status: "RUNNING", started_at: "2026-09-28T08:30:00.000Z" },
          { status: 202 },
        );
      }),
    );

    const { onClose } = renderWizard();
    await goToStep2(EVT_ORDER_B_RISK, "erp");

    fireEvent.change($("replay-since"), { target: { value: "2026-09-10T10:40" } });
    fireEvent.click(btn("replay-next"));
    await waitFor(() => expect(stepEl(3)).not.toBeNull());

    fireEvent.click(btn("replay-execute"));
    await waitFor(() => expect($("replay-sync-id").textContent).toBe(SYNC_ID));
    expect($("replay-status").textContent).toContain("RUNNING");
    // 成功面板标题与 toast（「回放任务已提交」）区分，限定在结果面板内断言
    expect(within($("replay-result")).getByText("回放已下发")).toBeInTheDocument();
    expect(calls).toEqual([
      {
        adapter: "erp",
        body: { mode: "replay", since: new Date("2026-09-10T10:40").toISOString() },
      },
    ]);

    fireEvent.click(btn("replay-done"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("失败分支：sync 503 → errorSpec 文案行内展示，步骤 3 保留可重试", async () => {
    server.use(
      http.post("*/api/v1/admin/adapters/:adapterName/sync", () =>
        errorOf("UPSTREAM_UNAVAILABLE", "源系统暂不可达，稍后重试", 503),
      ),
    );

    renderWizard();
    await goToStep2(EVT_ORDER_H_RISK, "plm");
    fireEvent.click(btn("replay-next"));
    await waitFor(() => expect(stepEl(3)).not.toBeNull());

    fireEvent.click(btn("replay-execute"));
    expect(await screen.findByText("源系统暂不可达，稍后重试")).toBeInTheDocument();
    expect($("replay-error")).not.toBeNull();
    expect($("replay-result")).toBeNull();
    expect(stepEl(3)).not.toBeNull();
  });

  it("W3-37：向导未打开不发适配器清单请求（计数 0），打开后拉取", async () => {
    let listCalls = 0;
    server.use(
      http.get("*/api/v1/admin/adapters", () => {
        listCalls += 1;
        return HttpResponse.json({ items: [], next_cursor: null, total: 0 });
      }),
    );
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const onClose = vi.fn();
    const tree = (open: boolean) => (
      <QueryClientProvider client={queryClient}>
        <ReplayWizard open={open} events={[ORDER_B]} onClose={onClose} />
      </QueryClientProvider>
    );
    const { rerender } = render(tree(false));

    // 未打开：窗口期内不发适配器清单请求
    await new Promise((resolve) => setTimeout(resolve, 150));
    expect(listCalls).toBe(0);

    rerender(tree(true));
    await waitFor(() => expect(listCalls).toBe(1));
  });
});
