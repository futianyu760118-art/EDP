import type { Meta, StoryObj } from "@storybook/react";
import { StatusPill, type StatusPillTone } from "./StatusPill";

const meta: Meta<typeof StatusPill> = {
  title: "Components/StatusPill",
  component: StatusPill,
  args: { tone: "success", label: "运行中", dot: false, size: "md" },
  argTypes: {
    tone: { control: "radio", options: ["success", "warning", "error", "info", "muted"] },
    size: { control: "radio", options: ["sm", "md"] },
  },
};

export default meta;

export const Default: StoryObj<typeof meta> = {};

const toneLabels: Record<StatusPillTone, string> = {
  success: "PUBLISHED",
  warning: "WATCH",
  error: "L3",
  info: "PENDING",
  muted: "已失效",
};

export const ToneMatrix: StoryObj = {
  render: () => (
    <div className="flex flex-wrap items-center gap-3">
      {(Object.keys(toneLabels) as StatusPillTone[]).map((tone) => (
        <StatusPill key={tone} tone={tone} label={toneLabels[tone]} />
      ))}
    </div>
  ),
};

export const WithDot: StoryObj = {
  render: () => (
    <div className="flex flex-wrap items-center gap-3">
      <StatusPill tone="success" dot label="运行中 · 多租户工作空间" />
      <StatusPill tone="warning" dot label="L2 关注" />
      <StatusPill tone="error" dot label="适配器失联" />
      <StatusPill tone="info" dot label="重索引进行中" />
      <StatusPill tone="muted" dot label="已归档" />
    </div>
  ),
};

export const Sizes: StoryObj = {
  render: () => (
    <div className="flex flex-wrap items-center gap-3">
      <StatusPill tone="success" size="sm" label="表格内 sm" />
      <StatusPill tone="success" size="md" label="默认 md" />
      <StatusPill tone="info" size="sm" dot label="sm + 圆点" />
      <StatusPill tone="info" size="md" dot label="md + 圆点" />
    </div>
  ),
};
