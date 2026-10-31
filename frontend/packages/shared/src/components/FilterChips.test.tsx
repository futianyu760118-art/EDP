import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FilterChips } from "./FilterChips";

const CHIPS = [
  { key: "keyword", label: "关键词：x" },
  { key: "source", label: "来源：ERP-S4" },
];

describe("FilterChips", () => {
  it("渲染全部 chip 标签", () => {
    render(<FilterChips chips={CHIPS} onRemove={() => {}} />);
    expect(screen.getByText("关键词：x")).toBeInTheDocument();
    expect(screen.getByText("来源：ERP-S4")).toBeInTheDocument();
  });

  it("点击 chip 的 x 触发 onRemove(key)", () => {
    const onRemove = vi.fn();
    render(<FilterChips chips={CHIPS} onRemove={onRemove} />);
    fireEvent.click(document.querySelector('[data-dom-id="chip-remove-source"]')!);
    expect(onRemove).toHaveBeenCalledWith("source");
    expect(onRemove).toHaveBeenCalledTimes(1);
  });

  it("提供 onClearAll 时渲染“清除全部”并触发回调", () => {
    const onClearAll = vi.fn();
    render(<FilterChips chips={CHIPS} onRemove={() => {}} onClearAll={onClearAll} />);
    fireEvent.click(screen.getByRole("button", { name: "清除全部" }));
    expect(onClearAll).toHaveBeenCalledTimes(1);
  });

  it("未提供 onClearAll 时不渲染清除全部；chips 为空时不渲染任何内容", () => {
    const { container, rerender } = render(
      <FilterChips chips={CHIPS} onRemove={() => {}} />,
    );
    expect(screen.queryByText("清除全部")).not.toBeInTheDocument();
    rerender(<FilterChips chips={[]} onRemove={() => {}} onClearAll={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });
});
