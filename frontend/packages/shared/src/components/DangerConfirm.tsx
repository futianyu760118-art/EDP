import { AlertTriangle, Loader2, Trash2, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

/**
 * 危险确认弹窗（设计文档 13.7 #10）。
 * 视觉基线：`原型设计/pages/删除确认.html` 行 577~604 ——
 * 红色图标块 + code 高亮对象 + “无法恢复”/级联影响文案（调用方传 description）
 * + 红底确认按钮；强确认 = 输入 confirmPhrase 匹配后才解锁按钮。
 * 自绘遮罩+卡片（不依赖任何组件库），role="dialog" aria-modal，Esc 关闭。
 */
export interface DangerConfirmProps {
  open: boolean;
  title: string;
  /** 后果文案；“无法恢复”与级联影响声明由调用方组织 */
  description: ReactNode;
  confirmText: string;
  /** 以 code 样式高亮的对象名（如 order_event_v2） */
  objectName?: string;
  /** 强确认短语：输入匹配后才 enable 确认按钮 */
  confirmPhrase?: string;
  onConfirm: () => void;
  onCancel: () => void;
  loading?: boolean;
}

export function DangerConfirm({
  open,
  title,
  description,
  confirmText,
  objectName,
  confirmPhrase,
  onConfirm,
  onCancel,
  loading = false,
}: DangerConfirmProps) {
  const [phraseInput, setPhraseInput] = useState("");
  const phraseSatisfied = confirmPhrase == null || phraseInput === confirmPhrase;

  useEffect(() => {
    if (open) setPhraseInput("");
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function handleKeydown(event: KeyboardEvent) {
      if (event.key === "Escape") onCancel();
    }
    window.addEventListener("keydown", handleKeydown);
    return () => window.removeEventListener("keydown", handleKeydown);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true" aria-label={title}>
      <div
        className="absolute inset-0 bg-black/45"
        data-dom-id="danger-backdrop"
        onClick={onCancel}
      />
      <div className="relative bg-card border border-border rounded-xl shadow-[var(--edp-shadow-3)] w-full max-w-[420px] mx-4 overflow-hidden">
        <div className="px-5 py-4 border-b border-border flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div
              className="w-8 h-8 rounded-lg bg-state-error-bg text-state-error grid place-items-center"
              aria-hidden="true"
            >
              <AlertTriangle className="w-4 h-4" />
            </div>
            <h2 className="text-sm font-semibold text-foreground">{title}</h2>
          </div>
          <button
            type="button"
            aria-label="关闭"
            data-dom-id="danger-close"
            onClick={onCancel}
            disabled={loading}
            className="w-7 h-7 rounded-lg border border-border bg-card grid place-items-center text-muted-foreground hover:bg-muted disabled:opacity-50"
          >
            <X className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>
        <div className="px-5 py-5">
          <p className="text-sm text-foreground leading-relaxed">
            {description}
            {objectName != null && (
              <code className="ml-1 font-mono text-xs bg-muted px-1.5 py-0.5 rounded text-foreground">
                {objectName}
              </code>
            )}
          </p>
          {confirmPhrase != null && (
            <input
              type="text"
              value={phraseInput}
              onChange={(event) => setPhraseInput(event.target.value)}
              placeholder={`输入 ${confirmPhrase} 以确认`}
              data-dom-id="danger-phrase-input"
              disabled={loading}
              className="mt-4 h-9 w-full px-3 text-xs bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent disabled:opacity-50"
            />
          )}
        </div>
        <div className="px-5 py-4 border-t border-border flex items-center justify-end gap-2">
          <button
            type="button"
            data-dom-id="danger-cancel"
            onClick={onCancel}
            disabled={loading}
            className="h-9 px-4 border border-border bg-card rounded-lg text-xs text-muted-foreground hover:bg-muted disabled:opacity-50"
          >
            取消
          </button>
          <button
            type="button"
            data-dom-id="danger-confirm"
            onClick={onConfirm}
            disabled={!phraseSatisfied || loading}
            className="h-9 px-4 bg-state-error text-white rounded-lg text-xs font-medium hover:opacity-90 flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <Trash2 className="w-3.5 h-3.5" aria-hidden="true" />
            )}
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}
