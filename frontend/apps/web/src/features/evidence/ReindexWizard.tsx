import { Modal, Steps, message } from "antd";
import { useState } from "react";
import { CheckCircle2, Database, Loader2, ShieldCheck, XCircle } from "lucide-react";
import { errorSpec } from "@edp/shared";
import { useReindexEvidence, useReindexTask } from "./hooks";

export interface ReindexWizardProps {
  open: boolean;
  onClose: () => void;
}

/**
 * 重建索引三步向导（设计 13.6.2；视觉基线 `证据重新索引 - 执行流程.html`，
 * T13 对齐冻结契约）：① 选择范围（全量——契约 scope=ALL 仅全量）→
 * ② 校验规则（canonical checksum 重算比对，失配仅计数不回写）→
 * ③ 执行确认 → `POST /admin/evidence/reindex` 202 → 轮询
 * GET /admin/quality/tasks/{id} 至终态（SUCCEEDED 展示 stats total/mismatched；
 * FAILED 失败态）。
 */
export function ReindexWizard({ open, onClose }: ReindexWizardProps) {
  const [step, setStep] = useState(0);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reindex = useReindexEvidence();
  const taskQuery = useReindexTask(taskId);
  const task = taskQuery.data;

  const reset = () => {
    setStep(0);
    setTaskId(null);
    setError(null);
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  const submit = () => {
    setError(null);
    reindex.mutate(undefined, {
      onSuccess: (accepted) => {
        setTaskId(accepted.task_id);
        void message.success("重索引任务已提交");
      },
      onError: (err) => {
        const code = (err as unknown as { code?: string }).code;
        setError(errorSpec(code).message);
      },
    });
  };

  const stats = task?.stats as { total?: number; rechecked?: number; mismatched?: number } | undefined;

  return (
    <Modal
      open={open}
      onCancel={handleClose}
      footer={null}
      width={720}
      destroyOnClose
      title="重建证据索引"
      data-dom-id="reindex-wizard"
    >
      <Steps
        current={step}
        size="small"
        className="my-4"
        items={[{ title: "选择范围" }, { title: "校验规则" }, { title: "执行确认" }]}
      />

      {step === 0 && (
        <div data-dom-id="reindex-step-1">
          <div className="flex items-start gap-3 rounded-lg border border-primary bg-primary-50 px-4 py-3">
            <Database className="w-4 h-4 text-primary mt-0.5 shrink-0" aria-hidden="true" />
            <div className="text-xs">
              <span className="font-medium text-foreground">全量范围（scope=ALL）</span>
              <span className="block text-[11px] text-muted-foreground mt-0.5">
                重建本租户全部证据索引（当前版本仅支持全量，对象集合与日期范围筛选暂未开放）。
              </span>
            </div>
          </div>
        </div>
      )}

      {step === 1 && (
        <div data-dom-id="reindex-step-2" className="space-y-2">
          <div className="flex items-start gap-3 rounded-lg border border-border px-4 py-3">
            <ShieldCheck className="w-4 h-4 text-state-success mt-0.5 shrink-0" aria-hidden="true" />
            <div className="text-xs">
              <span className="font-medium text-foreground">完整性：canonical checksum 重算</span>
              <span className="block text-[11px] text-muted-foreground mt-0.5">
                逐条重算 canonical checksum 并与原值比对；失配仅计数并落 quality.reindex_mismatch 事件，保留原值不回写。
              </span>
            </div>
          </div>
        </div>
      )}

      {step === 2 && (
        <div data-dom-id="reindex-step-3">
          {taskId == null ? (
            <div className="rounded-lg border border-border bg-muted px-4 py-3 text-xs text-muted-foreground">
              <div className="flex justify-between py-0.5">
                <span>范围</span>
                <span className="text-foreground">全量（scope=ALL）</span>
              </div>
              <div className="flex justify-between py-0.5">
                <span>校验规则</span>
                <span className="text-foreground">完整性（checksum 重算）</span>
              </div>
              <div className="flex justify-between py-0.5 border-t border-border mt-1 pt-1.5">
                <span>预估</span>
                <span className="text-foreground">全量证据重算（后台异步执行）</span>
              </div>
            </div>
          ) : task == null || task.status === "RUNNING" ? (
            <div
              className="flex items-center gap-2 rounded-lg border border-state-info/20 bg-state-info-bg px-4 py-3 text-xs text-state-info"
              data-dom-id="reindex-running"
            >
              <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
              重索引执行中（任务 {task?.task_id ?? taskId}），完成后自动展示结果。
            </div>
          ) : task.status === "SUCCEEDED" ? (
            <div
              className="rounded-lg border border-state-success-bg bg-state-success-bg px-4 py-3 text-xs text-state-success"
              data-dom-id="reindex-result"
            >
              <div className="flex items-center gap-1.5 font-medium">
                <CheckCircle2 className="w-4 h-4" aria-hidden="true" />
                重索引完成
              </div>
              <div className="mt-1.5 grid grid-cols-3 gap-2 text-center">
                <div className="border border-state-success/20 rounded-md px-2 py-1.5">
                  <div className="text-[10px] opacity-80">证据总数</div>
                  <div className="text-sm font-semibold font-mono" data-dom-id="reindex-stats-total">
                    {stats?.total ?? "—"}
                  </div>
                </div>
                <div className="border border-state-success/20 rounded-md px-2 py-1.5">
                  <div className="text-[10px] opacity-80">已重算</div>
                  <div className="text-sm font-semibold font-mono">{stats?.rechecked ?? "—"}</div>
                </div>
                <div className="border border-state-success/20 rounded-md px-2 py-1.5">
                  <div className="text-[10px] opacity-80">checksum 失配</div>
                  <div className="text-sm font-semibold font-mono" data-dom-id="reindex-stats-mismatched">
                    {stats?.mismatched ?? "—"}
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div
              className="flex items-start gap-2 rounded-lg border border-state-error/20 bg-state-error-bg px-4 py-3 text-xs text-state-error"
              data-dom-id="reindex-failed"
            >
              <XCircle className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" />
              <div>
                <span className="font-medium">重索引失败</span>
                <span className="block text-[11px] mt-0.5 opacity-90">
                  任务 {task.task_id} 未完成，请查看任务日志或稍后重试。
                </span>
              </div>
            </div>
          )}
          {error != null && (
            <p className="mt-2 text-xs text-state-error" data-dom-id="reindex-error">
              {error}
            </p>
          )}
        </div>
      )}

      <div className="flex items-center justify-end gap-2 mt-6">
        {step > 0 && (
          <button
            type="button"
            data-dom-id="reindex-prev"
            onClick={() => setStep((s) => s - 1)}
            className="h-9 px-4 border border-border rounded-lg text-xs text-muted-foreground hover:bg-muted"
          >
            上一步
          </button>
        )}
        {step < 2 ? (
          <button
            type="button"
            data-dom-id="reindex-next"
            onClick={() => setStep((s) => s + 1)}
            className="h-9 px-4 bg-primary text-primary-foreground rounded-lg text-xs font-medium hover:opacity-90 disabled:opacity-50 disabled:pointer-events-none"
          >
            下一步
          </button>
        ) : taskId == null ? (
          <button
            type="button"
            data-dom-id="reindex-submit"
            disabled={reindex.isPending}
            onClick={submit}
            className="h-9 px-4 bg-primary text-primary-foreground rounded-lg text-xs font-medium hover:opacity-90 disabled:opacity-50 disabled:pointer-events-none"
          >
            {reindex.isPending ? "提交中…" : "执行重建"}
          </button>
        ) : (
          <button
            type="button"
            data-dom-id="reindex-done"
            onClick={handleClose}
            className="h-9 px-4 bg-primary text-primary-foreground rounded-lg text-xs font-medium hover:opacity-90"
          >
            完成
          </button>
        )}
      </div>
    </Modal>
  );
}
