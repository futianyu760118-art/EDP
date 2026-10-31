import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CursorPagination } from "./CursorPagination";

const PROPS = { start: 1, end: 8, total: 18421, page: 1, hasPrev: false, hasNext: true };

describe("CursorPagination", () => {
  it("渲染范围文案与当前页码", () => {
    render(
      <CursorPagination {...PROPS} onPrev={() => {}} onNext={() => {}} />,
    );
    expect(screen.getByText("显示 1–8 条，共 18421 条")).toBeInTheDocument();
    expect(screen.getByText("1")).toHaveAttribute("aria-current", "page");
  });

  it("首页：上一页禁用、下一页可用并触发 onNext", () => {
    const onPrev = vi.fn();
    const onNext = vi.fn();
    render(<CursorPagination {...PROPS} onPrev={onPrev} onNext={onNext} />);
    const prev = screen.getByRole("button", { name: "上一页" }) as HTMLButtonElement;
    const next = screen.getByRole("button", { name: "下一页" }) as HTMLButtonElement;
    expect(prev).toBeDisabled();
    expect(next).toBeEnabled();
    fireEvent.click(prev);
    expect(onPrev).not.toHaveBeenCalled();
    fireEvent.click(next);
    expect(onNext).toHaveBeenCalledTimes(1);
  });

  it("末页：下一页禁用、上一页可用并触发 onPrev", () => {
    const onPrev = vi.fn();
    const onNext = vi.fn();
    render(
      <CursorPagination
        start={18417}
        end={18421}
        total={18421}
        page={2303}
        hasPrev
        hasNext={false}
        onPrev={onPrev}
        onNext={onNext}
      />,
    );
    const prev = screen.getByRole("button", { name: "上一页" }) as HTMLButtonElement;
    const next = screen.getByRole("button", { name: "下一页" }) as HTMLButtonElement;
    expect(next).toBeDisabled();
    expect(prev).toBeEnabled();
    fireEvent.click(next);
    expect(onNext).not.toHaveBeenCalled();
    fireEvent.click(prev);
    expect(onPrev).toHaveBeenCalledTimes(1);
  });

  it("单页：两侧均禁用", () => {
    render(
      <CursorPagination
        start={1}
        end={3}
        total={3}
        page={1}
        hasPrev={false}
        hasNext={false}
        onPrev={() => {}}
        onNext={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "上一页" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
  });
});
