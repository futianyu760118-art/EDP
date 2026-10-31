import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { VerticalTimeline, type TimelineItem } from "./VerticalTimeline";

const ITEMS: TimelineItem[] = [
  { time: "09-10 12:20", text: "任务完成", meta: "ACT-7741 · Action", tone: "primary" },
  { time: "09-10 11:08", text: "审批通过", meta: "DC-1048 · Human", tone: "success" },
  { time: "09-10 10:31", text: "冲突映射", tone: "error" },
];

describe("VerticalTimeline", () => {
  it("按顺序渲染全部 items 的 time/text/meta", () => {
    render(<VerticalTimeline items={ITEMS} />);
    expect(screen.getByText("09-10 12:20")).toBeInTheDocument();
    expect(screen.getByText("任务完成")).toBeInTheDocument();
    expect(screen.getByText("ACT-7741 · Action")).toBeInTheDocument();
    expect(screen.getByText("冲突映射")).toBeInTheDocument();
  });

  it("meta 缺省的条目不渲染第三行", () => {
    render(<VerticalTimeline items={ITEMS} />);
    expect(screen.getByText("冲突映射").nextElementSibling).toBeNull();
  });

  it("渲染语义色圆点（border-2 border-card + tone 底色）", () => {
    render(<VerticalTimeline items={ITEMS} />);
    const dots = document.querySelectorAll("span.absolute.rounded-full");
    expect(dots.length).toBe(3);
    expect(dots[0]).toHaveClass("bg-primary", "border-card", "border-2");
    expect(dots[1]).toHaveClass("bg-state-success");
    expect(dots[2]).toHaveClass("bg-state-error");
  });

  it("items 为空时不渲染容器", () => {
    const { container } = render(<VerticalTimeline items={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
