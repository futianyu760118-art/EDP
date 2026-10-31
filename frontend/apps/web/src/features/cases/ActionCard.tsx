import { ArrowRight, User } from "lucide-react";
import { Link } from "react-router-dom";
import { StatusPill } from "@edp/shared";
import { fmtDateTime } from "../../lib/labels";
import type { CaseActionItem } from "./api";
import { actionStatusOf } from "./labels";

export interface ActionCardProps {
  action: CaseActionItem;
  caseId: string;
}

/**
 * 关联行动卡（设计 13.6.5 ④）：status pill + owner/due + allowed_to 只读 chips
 * （human_only 转移人形图标）+「前往行动页」链接（/actions?case_id=）。
 */
export function ActionCard({ action, caseId }: ActionCardProps) {
  const status = actionStatusOf(action.status);
  return (
    <div className="border border-border rounded-lg p-3 bg-card" data-dom-id={`case-action-${action.action_id}`}>
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium text-foreground truncate" title={action.title}>
          {action.title}
        </span>
        <span className="ml-auto shrink-0">
          <StatusPill tone={status.tone} label={status.label} size="sm" />
        </span>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 text-[11px]">
        <div className="bg-muted rounded-md px-2.5 py-1.5">
          <span className="text-muted-foreground block">负责人</span>
          <span className="font-medium text-foreground truncate block" title={action.owner ?? undefined}>
            {action.owner ?? "—"}
          </span>
        </div>
        <div className="bg-muted rounded-md px-2.5 py-1.5">
          <span className="text-muted-foreground block">截止日期</span>
          <span className="font-medium text-foreground">
            {action.due_date != null ? fmtDateTime(action.due_date) : "—"}
          </span>
        </div>
      </div>
      <div className="mt-2 flex items-center gap-1.5 flex-wrap" data-dom-id={`case-action-transitions-${action.action_id}`}>
        <span className="text-[10px] text-muted-foreground">可流转：</span>
        {(action.allowed_to ?? []).map((transition) => (
          <span
            key={transition.to_status}
            data-dom-id="case-action-transition"
            title={transition.human_only ? "仅人工可执行" : undefined}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-muted text-muted-foreground"
          >
            {transition.to_status}
            {transition.human_only && <User className="w-3 h-3 text-state-warning" aria-hidden="true" />}
          </span>
        ))}
        {(action.allowed_to ?? []).length === 0 && (
          <span className="text-[10px] text-muted-foreground">终态</span>
        )}
      </div>
      <div className="mt-3 pt-2 border-t border-border">
        <Link
          to={`/actions?case_id=${caseId}`}
          data-dom-id={`case-action-goto-${action.action_id}`}
          className="text-[11px] text-primary hover:underline inline-flex items-center gap-1"
        >
          前往行动页
          <ArrowRight className="w-3 h-3" aria-hidden="true" />
        </Link>
      </div>
    </div>
  );
}
