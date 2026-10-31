import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Database } from "lucide-react";
import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  it("默认渲染 search-x 图标 + 标题 + 描述", () => {
    render(<EmptyState title="未找到匹配结果" description="请调整筛选条件" />);
    expect(screen.getByText("未找到匹配结果")).toBeInTheDocument();
    expect(screen.getByText("请调整筛选条件")).toBeInTheDocument();
    expect(document.querySelector(".lucide-search-x")).not.toBeNull();
    expect(document.querySelector(".w-14.h-14.rounded-full")).not.toBeNull();
  });

  it("自定义 icon 替换默认 search-x", () => {
    render(<EmptyState icon={<Database className="w-7 h-7" />} title="暂无对象" />);
    expect(document.querySelector(".lucide-search-x")).toBeNull();
    expect(document.querySelector(".lucide-database")).not.toBeNull();
  });

  it("双动作按钮分别触发回调", () => {
    const primary = vi.fn();
    const secondary = vi.fn();
    render(
      <EmptyState
        title="未找到匹配结果"
        primaryAction={{ label: "新建对象", onClick: primary }}
        secondaryAction={{ label: "清除筛选", onClick: secondary }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "新建对象" }));
    expect(primary).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "清除筛选" }));
    expect(secondary).toHaveBeenCalledTimes(1);
  });

  it("primary 为 bg-primary 实底、secondary 为边框按钮", () => {
    render(
      <EmptyState
        title="空"
        primaryAction={{ label: "新建", onClick: () => {} }}
        secondaryAction={{ label: "清除", onClick: () => {} }}
      />,
    );
    expect(screen.getByRole("button", { name: "新建" })).toHaveClass("bg-primary", "text-primary-foreground");
    expect(screen.getByRole("button", { name: "清除" })).toHaveClass("border", "border-border", "bg-card");
  });
});
