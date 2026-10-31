import type { ReactNode } from "react";

/**
 * 状态 Pill（设计文档 13.7 #1）。
 * 视觉基线：`原型设计/pages/运营总览.html` 行 457（紧凑变体）
 * 与行 339（圆点变体）。语义色由 --edp-state-* 令牌驱动。
 */
export type StatusPillTone = "success" | "warning" | "error" | "info" | "muted";

const toneClasses: Record<StatusPillTone, { pill: string; dot: string }> = {
  success: { pill: "bg-state-success-bg text-state-success", dot: "bg-state-success" },
  warning: { pill: "bg-state-warning-bg text-state-warning", dot: "bg-state-warning" },
  error: { pill: "bg-state-error-bg text-state-error", dot: "bg-state-error" },
  info: { pill: "bg-state-info-bg text-state-info", dot: "bg-state-info" },
  muted: { pill: "bg-muted text-muted-foreground", dot: "bg-muted-foreground" },
};

export interface StatusPillProps {
  tone: StatusPillTone;
  label: ReactNode;
  /** 圆点变体（rounded-full + 语义色圆点，基线行 339） */
  dot?: boolean;
  /** sm=10px（表格内），md=11px（默认） */
  size?: "sm" | "md";
}

export function StatusPill({ tone, label, dot = false, size = "md" }: StatusPillProps) {
  const t = toneClasses[tone];
  const sizeClass = size === "sm" ? "text-[10px]" : "text-[11px]";
  if (!dot) {
    return (
      <span className={`px-1.5 py-0.5 rounded font-medium ${sizeClass} ${t.pill}`}>
        {label}
      </span>
    );
  }
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-full font-medium ${sizeClass} ${t.pill}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${t.dot}`} aria-hidden="true" />
      {label}
    </span>
  );
}
