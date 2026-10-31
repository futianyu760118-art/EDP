import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PanelCard } from "./PanelCard";

describe("PanelCard 面板级降级四态", () => {
  it("loading：渲染 antd Skeleton，不渲染 children", () => {
    render(
      <PanelCard domId="panel-x" title="面板X" loading error={null}>
        <div>CONTENT</div>
      </PanelCard>,
    );
    expect(document.querySelector(".ant-skeleton")).not.toBeNull();
    expect(screen.queryByText("CONTENT")).toBeNull();
  });

  it("error：渲染「该面板暂不可用」，data-dom-id 以 -error 结尾", () => {
    render(
      <PanelCard domId="panel-x" title="面板X" loading={false} error={new Error("boom")}>
        <div>CONTENT</div>
      </PanelCard>,
    );
    expect(screen.getByText("该面板暂不可用")).toBeInTheDocument();
    expect(document.querySelector('[data-dom-id="panel-x-error"]')).not.toBeNull();
    expect(screen.queryByText("CONTENT")).toBeNull();
  });

  it("empty：渲染「暂无数据」，data-dom-id 以 -empty 结尾", () => {
    render(
      <PanelCard domId="panel-x" title="面板X" loading={false} error={null} empty>
        <div>CONTENT</div>
      </PanelCard>,
    );
    expect(screen.getByText("暂无数据")).toBeInTheDocument();
    expect(document.querySelector('[data-dom-id="panel-x-empty"]')).not.toBeNull();
    expect(screen.queryByText("CONTENT")).toBeNull();
  });

  it("正常态：渲染标题、action 插槽与 children", () => {
    render(
      <PanelCard
        domId="panel-x"
        title="面板X"
        loading={false}
        error={null}
        action={<button type="button">查看全部</button>}
      >
        <div>CONTENT</div>
      </PanelCard>,
    );
    expect(screen.getByText("面板X")).toBeInTheDocument();
    expect(screen.getByText("查看全部")).toBeInTheDocument();
    expect(screen.getByText("CONTENT")).toBeInTheDocument();
    expect(document.querySelector('[data-dom-id="panel-x"]')).not.toBeNull();
  });

  it("error 优先于 empty", () => {
    render(
      <PanelCard domId="panel-x" title="面板X" loading={false} error={new Error("boom")} empty>
        <div>CONTENT</div>
      </PanelCard>,
    );
    expect(screen.getByText("该面板暂不可用")).toBeInTheDocument();
    expect(screen.queryByText("暂无数据")).toBeNull();
  });
});
