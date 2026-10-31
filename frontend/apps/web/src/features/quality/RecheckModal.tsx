import { useQueryClient } from "@tanstack/react-query";
import { Modal, message } from "antd";
import { useState } from "react";
import { errorSpec } from "@edp/shared";
import type { RecheckScope } from "./api";
import { useRecheck } from "./hooks";

/** 校验范围（对齐契约 RecheckRequest.scope 值域；coverage 段仅 ALL 覆盖——
 * 后端 _SCOPE_SEGMENTS：单段 scope = RECONCILE/ORPHAN/CHECKSUM，ALL = 四段）。 */
const SCOPES: { key: RecheckScope; label: string; description: string }[] = [
  { key: "ALL", label: "全部四段", description: "对账 / 覆盖率 / 孤儿 / 校验和抽检" },
  { key: "RECONCILE", label: "对账", description: "按 (来源系统, 对象类型) 分组比对期望基数" },
  { key: "ORPHAN", label: "孤儿", description: "事件与证据悬挂（object_id 无注册对象）" },
  { key: "CHECKSUM", label: "校验和抽检", description: "P0/P1 证据抽样重算 canonical checksum" },
];

export interface RecheckModalProps {
  open: boolean;
  onClose: () => void;
  /** 提交成功回调（携带 task_id → 打开任务日志抽屉）。 */
  onSubmitted: (taskId: string) => void;
}

/**
 * 重新校验弹窗（视觉基线 `重新校验 - 弹窗.html`，范围对齐 T4 契约）：
 * 校验范围 2×2 单选卡（默认全部四段）+ info 提示条；提交 POST rechecks
 * （scope）→ 202 → 任务日志抽屉轮询，完成事件经消息中心（Bell）通知。
 */
export function RecheckModal({ open, onClose, onSubmitted }: RecheckModalProps) {
  const [scope, setScope] = useState<RecheckScope>("ALL");
  const [error, setError] = useState<string | null>(null);
  const recheck = useRecheck();
  const queryClient = useQueryClient();

  const submit = () => {
    setError(null);
    recheck.mutate(scope, {
      onSuccess: (task) => {
        void message.success("校验任务已提交，完成后将通知");
        void queryClient.invalidateQueries({ queryKey: ["quality", "report"] });
        void queryClient.invalidateQueries({ queryKey: ["quality", "exceptions"] });
        onSubmitted(task.task_id);
        onClose();
      },
      onError: (err) => {
        const code = (err as unknown as { code?: string }).code;
        setError(errorSpec(code).message);
      },
    });
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={520}
      destroyOnClose
      title="重新校验数据质量"
      data-dom-id="recheck-modal"
    >
      <div data-dom-id="recheck-body">
        <p className="text-xs font-medium text-foreground mt-2 mb-2">校验范围</p>
        <div className="grid grid-cols-2 gap-2">
          {SCOPES.map((option) => {
            const active = scope === option.key;
            return (
              <button
                key={option.key}
                type="button"
                data-dom-id={`recheck-scope-${option.key}`}
                aria-pressed={active}
                onClick={() => setScope(option.key)}
                className={`h-12 px-3 rounded-lg border text-left ${
                  active
                    ? "border-primary bg-primary-50 text-primary"
                    : "border-border text-muted-foreground hover:bg-muted"
                }`}
              >
                <span className="text-xs font-medium block">{option.label}</span>
                <span className="text-[10px] block mt-0.5 opacity-80">{option.description}</span>
              </button>
            );
          })}
        </div>

        <p className="mt-4 text-[11px] text-state-info bg-state-info-bg rounded-lg px-3 py-2">
          校验完成后，系统将通过消息中心通知你结果，并自动更新质量评分与异常列表。
        </p>
        {error != null && (
          <p className="mt-2 text-xs text-state-error" data-dom-id="recheck-error">
            {error}
          </p>
        )}
      </div>

      <div className="flex items-center justify-end gap-2 mt-6">
        <button
          type="button"
          data-dom-id="recheck-cancel"
          onClick={onClose}
          className="h-9 px-4 border border-border rounded-lg text-xs text-muted-foreground hover:bg-muted"
        >
          取消
        </button>
        <button
          type="button"
          data-dom-id="recheck-submit"
          disabled={recheck.isPending}
          onClick={submit}
          className="h-9 px-4 bg-primary text-primary-foreground rounded-lg text-xs font-medium hover:opacity-90 disabled:opacity-50 disabled:pointer-events-none"
        >
          {recheck.isPending ? "提交中…" : "开始校验"}
        </button>
      </div>
    </Modal>
  );
}
