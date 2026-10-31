import { Button, Card, Input, Tag } from "antd";
import type { Meta, StoryObj } from "@storybook/react";

function ThemeShowcase() {
  return (
    <div style={{ display: "grid", gap: 16, maxWidth: 560 }}>
      <Card title="ConfigProvider 双套令牌（Button / Input / Tag）">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
          <Button type="primary">主按钮</Button>
          <Button>次按钮</Button>
          <Button type="text">文字按钮</Button>
          <Button danger>危险</Button>
        </div>
        <Input placeholder="占位符（暗色应为 #6b7280 三级文本覆写）" />
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 12 }}>
          <Tag>默认</Tag>
          <Tag color="blue">info</Tag>
          <Tag color="green">success</Tag>
          <Tag color="orange">warning</Tag>
          <Tag color="red">error</Tag>
          <Tag color="geekblue">geekblue</Tag>
        </div>
      </Card>
      <Card title="主色底派生（colorPrimaryBg 覆写）">
        <div
          style={{
            background: "var(--edp-primary-50)",
            color: "var(--edp-foreground)",
            padding: 12,
            borderRadius: "var(--edp-radius-medium)",
          }}
        >
          --edp-primary-50 底（暗色应为 #1e1f3a，非 antd 默认亮色 #f0f3ff）
        </div>
      </Card>
    </div>
  );
}

const meta: Meta = {
  title: "Foundation/ThemeToggle",
  parameters: {
    docs: {
      description: {
        component:
          "同一组件组合在亮/暗两个 story 下渲染，验证 ConfigProvider 双套 token 切换（无 algorithm，token 原值直出）在 Storybook 内生效；暗色 story 下 html.dark 生效、CSS 变量与 antd token 同步翻转。",
      },
    },
  },
};

export default meta;
type Story = StoryObj<typeof meta>;

export const Light: Story = {
  parameters: { theme: "light", backgrounds: { default: "light" } },
  render: () => <ThemeShowcase />,
};

export const Dark: Story = {
  parameters: { theme: "dark", backgrounds: { default: "dark" } },
  render: () => <ThemeShowcase />,
};
