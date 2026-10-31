import type { Meta, StoryObj } from "@storybook/react";
import { VerticalTimeline, type TimelineItem } from "./VerticalTimeline";

const meta: Meta<typeof VerticalTimeline> = {
  title: "Components/VerticalTimeline",
  component: VerticalTimeline,
};

export default meta;

/** 基线：运营总览.html 行 498~529「事件与闭环」 */
const CLOSURE_ITEMS: TimelineItem[] = [
  {
    time: "09-10 12:20",
    text: "采购加急任务完成，等待业务结果验证",
    meta: "ACT-7741 · Action",
    tone: "primary",
  },
  {
    time: "09-10 11:08",
    text: "审批通过：加急采购 + 替代料评估",
    meta: "DC-1048 · Human",
    tone: "success",
  },
  {
    time: "09-10 10:42",
    text: "Delivery.OrderRisk 评分 92 / L3",
    meta: "ORD-202609-001 · DQ Engine",
    tone: "info",
  },
  {
    time: "09-10 10:41",
    text: "供应商 S-118 预计交期延迟 14 天",
    meta: "ORD-202609-001 · ERP-S4",
    tone: "warning",
  },
  {
    time: "09-10 10:31",
    text: "客户 ID 在 ERP / MDM 中存在冲突映射",
    meta: "CUST-771 · DQ Engine",
    tone: "error",
  },
];

export const Default: StoryObj = {
  args: { items: CLOSURE_ITEMS },
};

export const SingleItem: StoryObj = {
  args: { items: [{ time: "09-10 10:42", text: "单条事件（无 meta 行）", tone: "primary" }] },
};

export const Empty: StoryObj = {
  args: { items: [] },
  render: () => (
    <div className="bg-card border border-border rounded-xl p-4">
      <VerticalTimeline items={[]} />
      <p className="text-xs text-muted-foreground">（items 为空时不渲染时间线容器）</p>
    </div>
  ),
};
