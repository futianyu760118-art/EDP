import type { ReactNode } from "react";
import type { SemanticTone } from "./types";

/**
 * KPI 指标卡（设计文档 13.7 #3）。
 * 视觉基线：`原型设计/pages/运营总览.html` 行 377~384 ——
 * 标签 10px 大写 tracking-wider / text-xl 数值 / 11px 辅助 / 右上 w-8 图标块（语义色底）。
 */
const iconToneClasses: Record<SemanticTone, string> = {
  primary: "bg-primary-50 text-primary",
  success: "bg-state-success-bg text-state-success",
  warning: "bg-state-warning-bg text-state-warning",
  error: "bg-state-error-bg text-state-error",
  info: "bg-state-info-bg text-state-info",
  muted: "bg-muted text-muted-foreground",
};

export interface KpiCardProps {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  icon?: ReactNode;
  /** 图标块语义色（默认 primary-50/primary） */
  tone?: SemanticTone;
}

export function KpiCard({ label, value, hint, icon, tone = "primary" }: KpiCardProps) {
  return (
    <div className="bg-card border border-border rounded-xl p-4 flex items-start justify-between">
      <div className="min-w-0">
        <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">
          {label}
        </div>
        <div className="text-xl font-semibold text-foreground">{value}</div>
        {hint != null && <div className="text-[11px] text-muted-foreground mt-0.5">{hint}</div>}
      </div>
      {icon != null && (
        <div
          className={`w-8 h-8 rounded-lg grid place-items-center shrink-0 ${iconToneClasses[tone]}`}
          aria-hidden="true"
        >
          {icon}
        </div>
      )}
    </div>
  );
}
