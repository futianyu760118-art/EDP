import type { Meta, StoryObj } from "@storybook/react";
import { Database, FileSearch } from "lucide-react";
import { EmptyState } from "./EmptyState";

const meta: Meta<typeof EmptyState> = {
  title: "Components/EmptyState",
  component: EmptyState,
};

export default meta;

/** 基线：搜索无结果 - 空态.html 行 392~408 */
export const Default: StoryObj = {
  args: {
    title: "未找到匹配结果",
    description: "尝试更换关键词 “evidence_id” 或清除筛选条件后重试。",
    primaryAction: { label: "新建证据", onClick: () => {} },
    secondaryAction: { label: "清除筛选", onClick: () => {} },
  },
};

export const TitleOnly: StoryObj = {
  args: { title: "暂无数据", description: undefined },
};

export const CustomIcon: StoryObj = {
  render: () => (
    <EmptyState
      icon={<Database className="w-7 h-7" aria-hidden="true" />}
      title="还没有业务对象"
      description="注册第一个业务对象后，事件与证据将围绕它构建证据链。"
      primaryAction={{ label: "注册对象", onClick: () => {} }}
      secondaryAction={{ label: "导入模板", onClick: () => {} }}
    />
  ),
};

export const WithFileSearchIcon: StoryObj = {
  render: () => (
    <EmptyState
      icon={<FileSearch className="w-7 h-7" aria-hidden="true" />}
      title="证据库为空"
      description="接入适配器后，证据将自动归集到此处。"
      primaryAction={{ label: "新增适配器", onClick: () => {} }}
    />
  ),
};
