import { User } from "lucide-react";
import { useState } from "react";
import { ModalForm } from "../../components/ModalForm";
import type { PendingDecisionItem } from "./api";

export interface DecisionFormModalProps {
  open: boolean;
  caseItem: PendingDecisionItem | null;
  submitting: boolean;
  onCancel: () => void;
  /** 提交（已通过行内校验）：{chosen_option, comment, decision_type: "HUMAN"}。 */
  onSubmit: (body: { chosen_option: string; comment?: string; decision_type: "HUMAN" }) => void;
}

/**
 * 决策表单弹窗（设计 13.6.5 决策页 / 13.7 #6 640 档）：
 * 选项 radio = case.options（key+label）+ 意见 textarea + Human-Only 人形图标
 * 与 tooltip「仅人工可执行」；底栏 取消/提交决策。
 */
export function DecisionFormModal({ open, caseItem, submitting, onCancel, onSubmit }: DecisionFormModalProps) {
  const [chosen, setChosen] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);

  const options = caseItem?.options ?? [];
  const reset = () => {
    setChosen(null);
    setComment("");
    setError(null);
  };

  const handleCancel = () => {
    reset();
    onCancel();
  };

  const handleSubmit = () => {
    if (chosen == null) {
      setError("请选择一个选项");
      return;
    }
    setError(null);
    onSubmit({
      chosen_option: chosen,
      comment: comment.trim() ? comment.trim() : undefined,
      decision_type: "HUMAN",
    });
  };

  return (
    <ModalForm
      open={open}
      title={caseItem?.case_no != null ? `审批 ${caseItem.case_no}` : "决策审批"}
      icon={<User className="w-5 h-5" aria-hidden="true" />}
      width={640}
      onCancel={handleCancel}
      onSubmit={handleSubmit}
      submitText="提交决策"
      confirmLoading={submitting}
    >
      <div data-dom-id="decision-form" className="space-y-4 pt-2">
        {caseItem != null && (
          <p className="text-sm font-medium text-foreground" data-dom-id="decision-form-question">
            {caseItem.question}
          </p>
        )}

        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">选项</div>
          <div className="space-y-2" data-dom-id="decision-form-options">
            {options.map((option) => {
              const key = typeof option.key === "string" ? option.key : String(option.key);
              const label = typeof option.label === "string" ? option.label : key;
              return (
                <label
                  key={key}
                  className={`flex items-center gap-2.5 border rounded-lg px-3 py-2 cursor-pointer transition-colors ${
                    chosen === key ? "border-primary bg-primary-50" : "border-border hover:bg-muted/50"
                  }`}
                >
                  <input
                    type="radio"
                    name="decision-option"
                    data-dom-id={`decision-option-${key}`}
                    aria-label={`${label}（${key}）`}
                    checked={chosen === key}
                    onChange={() => {
                      setChosen(key);
                      setError(null);
                    }}
                    className="accent-primary"
                  />
                  <span className="text-xs text-foreground">{label}</span>
                  <span className="ml-auto font-mono text-[10px] text-muted-foreground">{key}</span>
                </label>
              );
            })}
            {options.length === 0 && (
              <div className="text-xs text-muted-foreground py-2">该案例未配置选项</div>
            )}
          </div>
          {error != null && (
            <div className="mt-1.5 text-[11px] text-state-error" data-dom-id="decision-form-error" role="alert">
              {error}
            </div>
          )}
        </div>

        <div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">审批意见（可选）</div>
          <textarea
            data-dom-id="decision-form-comment"
            aria-label="审批意见"
            rows={3}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="补充决策理由、影响评估或执行要求…"
            className="w-full text-xs bg-card border border-border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-ring resize-none"
          />
        </div>

        <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <span title="仅人工可执行" data-dom-id="decision-human-only" className="inline-flex items-center gap-1">
            <User className="w-3.5 h-3.5 text-state-warning" aria-hidden="true" />
            Human-Only
          </span>
          <span>该决策提交仅限人工执行</span>
        </div>
      </div>
    </ModalForm>
  );
}
