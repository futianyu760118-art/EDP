import type { Meta, StoryObj } from "@storybook/react";
import { Activity, Database, Layers, ShieldAlert, TriangleAlert, Zap } from "lucide-react";
import { KpiCard, type KpiCardProps } from "./KpiCard";

const meta: Meta<typeof KpiCard> = {
  title: "Components/KpiCard",
  component: KpiCard,
  args: {
    label: "业务对象",
    value: "1,247",
    hint: "+12 较昨日",
    icon: <Layers className="w-4 h-4" aria-hidden="true" />,
    tone: "primary",
  },
  argTypes: {
    tone: { control: "radio", options: ["primary", "success", "warning", "error", "info", "muted"] },
  },
};

export default meta;

export const Default: StoryObj<typeof meta> = {};

export const Minimal: StoryObj = {
  args: { label: "24H 事件", value: "18,421", hint: undefined, icon: undefined },
};

export const Tones: StoryObj<KpiCardProps> = {
  render: () => (
    <div className="kpi-grid">
      <KpiCard label="业务对象" value="1,247" hint="+12 较昨日" icon={<Layers className="w-4 h-4" />} />
      <KpiCard
        label="L3 风险"
        value="1"
        hint="需要立即处理"
        tone="error"
        icon={<TriangleAlert className="w-4 h-4" />}
      />
      <KpiCard
        label="L2 关注"
        value="2"
        hint="供应商交期"
        tone="warning"
        icon={<ShieldAlert className="w-4 h-4" />}
      />
      <KpiCard
        label="证据完整率"
        value="99.99%"
        hint="校验和有效"
        tone="success"
        icon={<Database className="w-4 h-4" />}
      />
      <KpiCard
        label="24H 事件"
        value="18,421"
        hint="峰值 2,104 / 小时"
        tone="info"
        icon={<Activity className="w-4 h-4" />}
      />
      <KpiCard label="适配器成功率" value="99.4%" tone="muted" icon={<Zap className="w-4 h-4" />} />
    </div>
  ),
};
