import type { SemanticTone } from "./types";

/**
 * 垂直时间线（设计文档 13.7 #4）。
 * 视觉基线：`原型设计/pages/运营总览.html` 行 498~529 ——
 * border-l 容器 + 绝对定位语义色圆点（border-2 border-card），
 * 时间(10px muted) / 文本(12px) / 关联行(11px muted) 三行结构。
 */
export interface TimelineItem {
  time: string;
  text: string;
  /** 关联行，如 “ACT-7741 · Action” */
  meta?: string;
  tone: SemanticTone;
}

const dotClasses: Record<SemanticTone, string> = {
  primary: "bg-primary",
  success: "bg-state-success",
  warning: "bg-state-warning",
  error: "bg-state-error",
  info: "bg-state-info",
  muted: "bg-muted-foreground",
};

export interface VerticalTimelineProps {
  items: TimelineItem[];
}

export function VerticalTimeline({ items }: VerticalTimelineProps) {
  if (items.length === 0) return null;
  return (
    <div className="relative pl-4 border-l border-border space-y-4">
      {items.map((item, index) => (
        <div key={`${item.time}-${index}`} className="relative">
          <span
            className={`absolute -left-[21px] top-1 w-2.5 h-2.5 rounded-full border-2 border-card ${dotClasses[item.tone]}`}
            aria-hidden="true"
          />
          <div className="text-[10px] text-muted-foreground mb-0.5">{item.time}</div>
          <div className="text-xs text-foreground">{item.text}</div>
          {item.meta != null && <div className="text-[11px] text-muted-foreground">{item.meta}</div>}
        </div>
      ))}
    </div>
  );
}
