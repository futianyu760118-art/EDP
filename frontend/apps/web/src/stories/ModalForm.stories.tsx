import type { Meta, StoryObj } from "@storybook/react";
import { useState, type ComponentProps } from "react";
import { Plus } from "lucide-react";
import { ModalForm } from "../components/ModalForm";

const meta: Meta<typeof ModalForm> = {
  title: "Components/ModalForm",
  component: ModalForm,
};

export default meta;

function FormDemo(props: Partial<ComponentProps<typeof ModalForm>>) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="h-9 px-4 bg-primary text-primary-foreground rounded-lg text-xs font-medium hover:opacity-90"
      >
        打开弹窗
      </button>
      <ModalForm
        open={open}
        title="注册业务对象"
        icon={<Plus className="w-5 h-5" aria-hidden="true" />}
        onCancel={() => setOpen(false)}
        onSubmit={() => setOpen(false)}
        submitText="创建对象"
        {...props}
      >
        <div className="flex flex-col gap-4 pt-2">
          <label className="flex flex-col gap-1.5 text-xs font-medium text-foreground">
            对象名称
            <input
              placeholder="例如：客户主数据"
              className="h-9 px-3 text-xs font-normal bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
            />
          </label>
          <label className="flex flex-col gap-1.5 text-xs font-medium text-foreground">
            对象编码
            <input
              placeholder="例如：CUST-MASTER-001"
              className="h-9 px-3 text-xs font-normal bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
            />
          </label>
        </div>
      </ModalForm>
    </>
  );
}

/** 基线：新建业务对象 - 弹窗.html 行 577~658（520 宽 + 图标徽标 + 底栏双按钮） */
export const Default: StoryObj = {
  render: () => <FormDemo />,
};

/** 无 onSubmit：底栏只有取消（信息展示型弹窗） */
export const Footerless: StoryObj = {
  render: () => <FormDemo title="适配器详情" onSubmit={undefined} submitText={undefined} />,
};

export const Loading: StoryObj = {
  render: () => <FormDemo confirmLoading submitText="创建中…" />,
};

export const Wide640: StoryObj = {
  render: () => <FormDemo width={640} title="新增适配器（640 宽）" />,
};
