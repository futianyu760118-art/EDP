import type { Meta, StoryObj } from "@storybook/react";
import { useState } from "react";
import { CursorPagination, type CursorPaginationProps } from "./CursorPagination";

const meta: Meta<typeof CursorPagination> = {
  title: "Components/CursorPagination",
  component: CursorPagination,
};

export default meta;

function PagedDemo(props: Omit<CursorPaginationProps, "onPrev" | "onNext">) {
  const [page, setPage] = useState(props.page);
  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      <div className="px-4 py-8 text-xs text-muted-foreground">表格内容（示意）</div>
      <CursorPagination
        {...props}
        page={page}
        onPrev={() => setPage((p) => Math.max(1, p - 1))}
        onNext={() => setPage((p) => p + 1)}
      />
    </div>
  );
}

/** 基线：事件流.html 行 529~538（首页：上一页禁用） */
export const FirstPage: StoryObj = {
  render: () => (
    <PagedDemo start={1} end={8} total={18421} page={1} hasPrev={false} hasNext={true} />
  ),
};

export const MiddlePage: StoryObj = {
  render: () => (
    <PagedDemo start={9} end={16} total={18421} page={2} hasPrev={true} hasNext={true} />
  ),
};

export const LastPage: StoryObj = {
  render: () => (
    <PagedDemo start={18417} end={18421} total={18421} page={2303} hasPrev={true} hasNext={false} />
  ),
};

export const SinglePage: StoryObj = {
  render: () => <PagedDemo start={1} end={3} total={3} page={1} hasPrev={false} hasNext={false} />,
};
