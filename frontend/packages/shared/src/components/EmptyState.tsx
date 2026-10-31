import { SearchX } from "lucide-react";
import type { ReactNode } from "react";

/**
 * 空态三件套（设计文档 13.7 #9）。
 * 视觉基线：`原型设计/pages/搜索无结果 - 空态.html` 行 392~408 与
 * `业务对象 - 空态.html` 行 395~406 —— 圆形 muted 底大图标（默认 search-x）
 * + 标题 + 引导文案 + 双动作（primary 实底 / secondary 边框）。
 */
export interface EmptyStateAction {
  label: string;
  onClick: () => void;
}

export interface EmptyStateProps {
  /** 自定义图标（lucide 元素）；缺省 search-x */
  icon?: ReactNode;
  title: string;
  description?: string;
  primaryAction?: EmptyStateAction;
  secondaryAction?: EmptyStateAction;
}

export function EmptyState({
  icon,
  title,
  description,
  primaryAction,
  secondaryAction,
}: EmptyStateProps) {
  return (
    <div className="bg-card border border-border rounded-xl p-12 flex flex-col items-center justify-center text-center">
      <div
        className="w-14 h-14 rounded-full bg-muted text-muted-foreground grid place-items-center mb-5"
        aria-hidden="true"
      >
        {icon ?? <SearchX className="w-7 h-7" />}
      </div>
      <h3 className="text-lg font-semibold text-foreground">{title}</h3>
      {description != null && (
        <p className="text-sm text-muted-foreground mt-2 mb-4 max-w-sm">{description}</p>
      )}
      {(primaryAction != null || secondaryAction != null) && (
        <div className="flex items-center gap-3 mt-6">
          {primaryAction != null && (
            <button
              type="button"
              data-dom-id="empty-primary-action"
              onClick={primaryAction.onClick}
              className="h-9 px-4 bg-primary text-primary-foreground rounded-lg text-xs font-medium hover:opacity-90"
            >
              {primaryAction.label}
            </button>
          )}
          {secondaryAction != null && (
            <button
              type="button"
              data-dom-id="empty-secondary-action"
              onClick={secondaryAction.onClick}
              className="h-9 px-4 border border-border bg-card text-foreground rounded-lg text-xs font-medium hover:bg-muted"
            >
              {secondaryAction.label}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
