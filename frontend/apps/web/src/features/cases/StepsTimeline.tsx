import { ListOrdered, User } from "lucide-react";
import { EmptyState, type SemanticTone } from "@edp/shared";
import { fmtDateTime } from "../../lib/labels";
import type { CaseStepItem } from "./api";

/** 步骤类型 → 语义色圆点（对齐 shared VerticalTimeline 视觉，13.7 #4）。 */
const STEP_TONES: Record<CaseStepItem["step_type"], SemanticTone> = {
  EVENT: "info",
  CASE_CREATED: "primary",
  DECISION: "warning",
  ACTION: "success",
};

const STEP_TYPE_LABELS: Record<CaseStepItem["step_type"], string> = {
  EVENT: "风险事件",
  CASE_CREATED: "案例创建",
  DECISION: "决策审批",
  ACTION: "行动推进",
};

const dotClasses: Record<SemanticTone, string> = {
  primary: "bg-primary",
  success: "bg-state-success",
  warning: "bg-state-warning",
  error: "bg-state-error",
  info: "bg-state-info",
  muted: "bg-muted-foreground",
};

export interface StepsTimelineProps {
  steps: CaseStepItem[];
}

/**
 * Steps 垂直时间线（设计 13.6.5 ③）：事件→案例→审批记录→Action 状态推进，
 * 时间升序；human_only 节点人形图标 + tooltip「仅人工可执行」（13.8 呈现约定）。
 */
export function StepsTimeline({ steps }: StepsTimelineProps) {
  if (steps.length === 0) {
    return (
      <div data-dom-id="case-steps-empty">
        <EmptyState
          icon={<ListOrdered className="w-7 h-7" />}
          title="暂无闭环步骤"
          description="案例推进记录（事件 → 决策 → 行动）将按时间升序在此沉淀。"
        />
      </div>
    );
  }
  return (
    <div className="relative pl-5 border-l border-border space-y-4" data-dom-id="case-steps-list">
      {steps.map((step, index) => (
        <div key={`${step.occurred_at}-${index}`} className="relative" data-dom-id="case-step-item">
          <span
            className={`absolute -left-[25px] top-1 w-2.5 h-2.5 rounded-full border-2 border-card ${dotClasses[STEP_TONES[step.step_type]]}`}
            aria-hidden="true"
          />
          <div className="text-[10px] text-muted-foreground mb-0.5 flex items-center gap-1.5 flex-wrap">
            <span>{fmtDateTime(step.occurred_at)}</span>
            <span className="px-1.5 py-px rounded bg-muted font-medium">{STEP_TYPE_LABELS[step.step_type]}</span>
            {step.human_only === true && (
              <span
                className="inline-flex items-center gap-0.5 text-state-warning"
                title="仅人工可执行"
                data-dom-id="case-step-human-only"
              >
                <User className="w-3 h-3" aria-hidden="true" />
              </span>
            )}
          </div>
          <div className="text-xs text-foreground">{step.title}</div>
          <div className="text-[11px] text-muted-foreground">
            {step.actor}
            {step.detail != null && step.detail !== "" ? ` · ${step.detail}` : ""}
          </div>
        </div>
      ))}
    </div>
  );
}
