import type { Meta, StoryObj } from "@storybook/react";
import { useState } from "react";
import { DangerConfirm, type DangerConfirmProps } from "./DangerConfirm";

const meta: Meta<typeof DangerConfirm> = {
  title: "Components/DangerConfirm",
  component: DangerConfirm,
};

export default meta;

function DangerDemo(props: Omit<DangerConfirmProps, "open" | "onConfirm" | "onCancel">) {
  const [open, setOpen] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  return (
    <div className="flex flex-col items-start gap-3">
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="h-9 px-4 border border-border bg-card text-foreground rounded-lg text-xs font-medium hover:bg-muted"
      >
        打开弹窗
      </button>
      {confirmed && <span className="text-xs text-state-success">已确认删除（演示）</span>}
      <DangerConfirm
        open={open}
        onConfirm={() => {
          setConfirmed(true);
          setOpen(false);
        }}
        onCancel={() => setOpen(false)}
        {...props}
      />
    </div>
  );
}

/** 基线：删除确认 - 弹窗.html 行 577~604（一般删除） */
export const Default: StoryObj = {
  render: () => (
    <DangerDemo
      title="删除业务对象"
      description="确定要删除业务对象吗？删除后将无法恢复，关联的证据链与事件流将置为失效状态。"
      objectName="order_event_v2"
      confirmText="确认删除"
    />
  ),
};

/** 强确认：输入 slug 匹配后解锁确认按钮（租户注销等不可逆操作） */
export const StrongConfirmation: StoryObj = {
  render: () => (
    <DangerDemo
      title="注销租户"
      description="此操作不可逆：租户下全部对象、事件、证据与审计记录将被永久删除，且无法恢复。"
      objectName="acme-east"
      confirmPhrase="acme-east"
      confirmText="确认注销"
    />
  ),
};

export const Loading: StoryObj = {
  render: () => (
    <DangerDemo
      title="删除业务对象"
      description="确定要删除业务对象吗？删除后将无法恢复。"
      objectName="order_event_v2"
      confirmText="删除中…"
      loading
    />
  ),
};
