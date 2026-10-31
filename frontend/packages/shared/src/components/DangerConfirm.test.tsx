import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DangerConfirm } from "./DangerConfirm";

const BASE_PROPS = {
  title: "删除业务对象",
  description: "确定要删除业务对象吗？删除后将无法恢复。",
  confirmText: "确认删除",
};

function confirmButton() {
  return screen.getByRole("button", { name: /确认删除/ }) as HTMLButtonElement;
}

describe("DangerConfirm", () => {
  it("open=false 不渲染；open=true 渲染 dialog 语义", () => {
    const { container, rerender } = render(
      <DangerConfirm {...BASE_PROPS} open={false} onConfirm={() => {}} onCancel={() => {}} />,
    );
    expect(container).toBeEmptyDOMElement();
    rerender(<DangerConfirm {...BASE_PROPS} open onConfirm={() => {}} onCancel={() => {}} />);
    expect(screen.getByRole("dialog")).toHaveAttribute("aria-modal", "true");
    expect(screen.getByText("删除业务对象")).toBeInTheDocument();
  });

  it("objectName 以 code 高亮渲染", () => {
    render(
      <DangerConfirm
        {...BASE_PROPS}
        open
        objectName="order_event_v2"
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );
    const code = screen.getByText("order_event_v2");
    expect(code.tagName).toBe("CODE");
    expect(code).toHaveClass("font-mono", "bg-muted");
  });

  it("取消按钮/遮罩/Esc 均触发 onCancel；确认按钮触发 onConfirm", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    const { unmount } = render(
      <DangerConfirm {...BASE_PROPS} open onConfirm={onConfirm} onCancel={onCancel} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    fireEvent.click(document.querySelector('[data-dom-id="danger-backdrop"]')!);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(3);
    fireEvent.click(confirmButton());
    expect(onConfirm).toHaveBeenCalledTimes(1);
    unmount();
  });

  it("强确认：短语不匹配禁用，匹配后解锁", () => {
    const onConfirm = vi.fn();
    render(
      <DangerConfirm
        {...BASE_PROPS}
        open
        confirmPhrase="acme-east"
        onConfirm={onConfirm}
        onCancel={() => {}}
      />,
    );
    const input = screen.getByPlaceholderText("输入 acme-east 以确认");
    expect(confirmButton()).toBeDisabled();
    fireEvent.change(input, { target: { value: "wrong" } });
    expect(confirmButton()).toBeDisabled();
    fireEvent.click(confirmButton());
    expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "acme-east" } });
    expect(confirmButton()).toBeEnabled();
    fireEvent.click(confirmButton());
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("loading：确认与取消均禁用且不响应 Esc 外的点击", () => {
    const onConfirm = vi.fn();
    render(
      <DangerConfirm {...BASE_PROPS} open loading onConfirm={onConfirm} onCancel={() => {}} />,
    );
    expect(confirmButton()).toBeDisabled();
    expect(screen.getByRole("button", { name: "取消" })).toBeDisabled();
    fireEvent.click(confirmButton());
    expect(onConfirm).not.toHaveBeenCalled();
    expect(document.querySelector(".animate-spin")).not.toBeNull();
  });
});
