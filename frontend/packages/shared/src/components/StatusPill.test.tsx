import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusPill } from "./StatusPill";

describe("StatusPill", () => {
  it("渲染语义色 pill：error tone 使用 bg-state-error-bg/text-state-error", () => {
    render(<StatusPill tone="error" label="L3" />);
    const pill = screen.getByText("L3");
    expect(pill).toHaveClass("bg-state-error-bg", "text-state-error", "font-medium");
  });

  it("muted tone 使用中性类 bg-muted/text-muted-foreground", () => {
    render(<StatusPill tone="muted" label="已失效" />);
    expect(screen.getByText("已失效")).toHaveClass("bg-muted", "text-muted-foreground");
  });

  it("dot 变体：rounded-full + 语义色圆点", () => {
    render(<StatusPill tone="success" label="运行中" dot />);
    const pill = screen.getByText("运行中");
    expect(pill).toHaveClass("rounded-full", "bg-state-success-bg");
    const dot = pill.querySelector("span");
    expect(dot).not.toBeNull();
    expect(dot).toHaveClass("bg-state-success", "rounded-full", "w-1.5");
  });

  it("尺寸：默认 md=11px，sm=10px", () => {
    const { rerender } = render(<StatusPill tone="info" label="A" />);
    expect(screen.getByText("A")).toHaveClass("text-[11px]");
    rerender(<StatusPill tone="info" label="A" size="sm" />);
    expect(screen.getByText("A")).toHaveClass("text-[10px]");
  });
});
