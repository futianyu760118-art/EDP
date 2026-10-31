import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Layers } from "lucide-react";
import { KpiCard } from "./KpiCard";

describe("KpiCard", () => {
  it("渲染标签、数值与辅助说明", () => {
    render(<KpiCard label="业务对象" value="1,247" hint="+12 较昨日" />);
    expect(screen.getByText("业务对象")).toHaveClass("uppercase", "tracking-wider");
    expect(screen.getByText("1,247")).toHaveClass("text-xl", "font-semibold");
    expect(screen.getByText("+12 较昨日")).toBeInTheDocument();
  });

  it("hint 缺省时不渲染辅助行", () => {
    render(<KpiCard label="24H 事件" value="18,421" />);
    expect(screen.queryByText("+12 较昨日")).not.toBeInTheDocument();
    expect(screen.getByText("24H 事件").nextElementSibling).toBe(screen.getByText("18,421"));
  });

  it("icon 渲染在 tone 图标块内（默认 primary-50/primary）", () => {
    render(<KpiCard label="业务对象" value="1" icon={<Layers className="w-4 h-4" />} />);
    const block = document.querySelector(".bg-primary-50");
    expect(block).not.toBeNull();
    expect(block).toHaveClass("text-primary", "w-8", "h-8", "rounded-lg");
    expect(block!.querySelector(".lucide-layers")).not.toBeNull();
  });

  it("warning tone 图标块使用 state-warning 底/字色", () => {
    render(<KpiCard label="L2" value="2" icon={<Layers />} tone="warning" />);
    const block = document.querySelector(".bg-state-warning-bg");
    expect(block).toHaveClass("text-state-warning");
  });
});
