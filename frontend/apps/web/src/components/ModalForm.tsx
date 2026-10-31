import { Button, Modal } from "antd";
import { Check } from "lucide-react";
import type { ReactNode } from "react";

/**
 * 模态表单（设计文档 13.7 #6）—— web 侧 antd Modal 封装。
 * 视觉基线：`原型设计/pages/新建业务对象 - 弹窗.html` 行 577~658 ——
 * 图标徽标块 + 标题 + 关闭 X；底栏 border-top + 右对齐（取消边框按钮 +
 * 主行动按钮带图标）；宽 480/520/640 三档。
 * getContainer={false} 使其原地渲染（RTL/jsdom 无 teleport 问题）。
 */
export interface ModalFormProps {
  open: boolean;
  title: string;
  /** 头部图标徽标（lucide 元素），如 <Plus /> */
  icon?: ReactNode;
  width?: 480 | 520 | 640;
  onCancel: () => void;
  /** 缺省时不渲染主按钮（只有取消/关闭） */
  onSubmit?: () => void;
  submitText?: string;
  children: ReactNode;
  confirmLoading?: boolean;
  /** W5：主按钮禁用（如必填项未满足；取消按钮不受影响） */
  submitDisabled?: boolean;
}

export function ModalForm({
  open,
  title,
  icon,
  width = 520,
  onCancel,
  onSubmit,
  submitText = "确定",
  children,
  confirmLoading = false,
  submitDisabled = false,
}: ModalFormProps) {
  const header = (
    <div className="flex items-center gap-2.5">
      {icon != null && (
        <div
          className="w-10 h-10 rounded-lg bg-primary-50 text-primary grid place-items-center"
          aria-hidden="true"
        >
          {icon}
        </div>
      )}
      <span className="text-base font-semibold text-foreground">{title}</span>
    </div>
  );

  const footer = (
    <div className="w-full border-t border-border pt-4 flex items-center justify-end gap-2">
      <Button data-dom-id="modal-form-cancel" autoInsertSpace={false} onClick={onCancel}>
        取消
      </Button>
      {onSubmit != null && (
        <Button
          type="primary"
          data-dom-id="modal-form-submit"
          autoInsertSpace={false}
          loading={confirmLoading}
          disabled={submitDisabled}
          onClick={onSubmit}
          icon={<Check className="w-4 h-4" aria-hidden="true" />}
        >
          {submitText}
        </Button>
      )}
    </div>
  );

  return (
    <Modal
      open={open}
      onCancel={onCancel}
      width={width}
      title={header}
      footer={footer}
      getContainer={false}
      destroyOnClose
    >
      {children}
    </Modal>
  );
}
