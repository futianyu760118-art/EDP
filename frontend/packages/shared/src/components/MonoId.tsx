import { Check, Copy } from "lucide-react";
import { useEffect, useRef, useState } from "react";

/**
 * Mono 短 ID（设计文档 13.7 #13）。
 * 展示 `{prefix}-{id 前 length 位}`（如 evt-8f32a1c4）；哈希变体显示
 * 首 4…尾 4（a4c1…9f3d）。title 属性携带全量；复制按钮点击后变 check 1.5s。
 */
export interface MonoIdProps {
  /** 类型前缀（如 evt / ev / dc） */
  prefix?: string;
  id: string;
  /** tooltip / 复制用的全量值；缺省用 id */
  full?: string;
  /** 短 ID 截取长度（默认 8） */
  length?: number;
  copyable?: boolean;
  /** 哈希缩写格式：a4c1…9f3d（首 4…尾 4） */
  hashFormat?: boolean;
}

export function MonoId({
  prefix,
  id,
  full,
  length = 8,
  copyable = true,
  hashFormat = false,
}: MonoIdProps) {
  const [copied, setCopied] = useState(false);
  const resetTimer = useRef<number | undefined>(undefined);
  const fullValue = full ?? id;
  const short = hashFormat
    ? `${id.slice(0, 4)}…${id.slice(-4)}`
    : `${prefix != null ? `${prefix}-` : ""}${id.slice(0, length)}`;

  useEffect(() => () => window.clearTimeout(resetTimer.current), []);

  async function handleCopy() {
    try {
      await navigator.clipboard?.writeText(fullValue);
      setCopied(true);
      window.clearTimeout(resetTimer.current);
      resetTimer.current = window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // 剪贴板不可用（非安全上下文等）时静默忽略
    }
  }

  return (
    <span className="inline-flex items-center gap-1 font-mono text-xs text-foreground" title={fullValue}>
      <span data-dom-id="mono-id-value">{short}</span>
      {copyable && (
        <button
          type="button"
          aria-label={`复制 ${fullValue}`}
          data-dom-id="mono-id-copy"
          onClick={handleCopy}
          className="w-4 h-4 rounded grid place-items-center text-muted-foreground hover:text-foreground"
        >
          {copied ? (
            <Check className="w-3 h-3 text-state-success" aria-hidden="true" />
          ) : (
            <Copy className="w-3 h-3" aria-hidden="true" />
          )}
        </button>
      )}
    </span>
  );
}
