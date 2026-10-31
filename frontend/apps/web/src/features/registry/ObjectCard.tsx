import { ArrowRight } from "lucide-react";
import { MonoId, StatusPill, type StatusPillTone } from "@edp/shared";
import { relTime } from "../../lib/labels";
import type { ObjectResponse } from "../../mocks/types";
import { DERIVED_TONE, deriveStatus, domainLabel, lagHours, riskScore } from "./derive";

const TONE_BAR: Record<StatusPillTone, string> = {
  success: "bg-state-success",
  warning: "bg-state-warning",
  error: "bg-state-error",
  info: "bg-state-info",
  muted: "bg-muted-foreground",
};

function attrString(obj: ObjectResponse, key: string): string | undefined {
  const v = obj.attributes?.[key];
  return typeof v === "string" ? v : undefined;
}

/**
 * 对象卡（视觉基线：`原型设计/pages/业务对象.html` 行 394~422 ——
 * 派生 pill + 类型标签 / mono source_id / 名称 / 域·来源 / 风险评分进度条 /
 * 标签 chips / Rev · 相对时间 / 查看详情）。
 */
export function ObjectCard({
  obj,
  riskLevel,
  hasDq,
  onOpenDetail,
}: {
  obj: ObjectResponse;
  riskLevel?: string | null;
  hasDq?: boolean;
  onOpenDetail: () => void;
}) {
  const status = deriveStatus({
    riskLevel,
    hasDqException: hasDq,
    syncLagHours: lagHours(obj.updated_at),
  });
  const score = riskScore(riskLevel);
  const tags = [attrString(obj, "condition"), attrString(obj, "risk_note")].filter(
    (t): t is string => Boolean(t),
  );

  return (
    <div className="bg-card border border-border rounded-xl p-4 flex flex-col" data-dom-id="object-card">
      <div className="flex items-start justify-between gap-2 mb-3">
        <div className="flex items-center gap-2 min-w-0">
          <StatusPill tone={DERIVED_TONE[status]} label={status} size="sm" />
          <span className="text-[10px] text-muted-foreground">{obj.object_type}</span>
        </div>
        <MonoId id={obj.source_id} copyable={false} length={obj.source_id.length} />
      </div>
      <h3 className="text-sm font-semibold text-foreground mb-1 truncate">
        {attrString(obj, "name") ?? obj.source_id}
      </h3>
      <div className="text-xs text-muted-foreground mb-3">
        {domainLabel(obj.owner_domain)} · 来源 {obj.source_system.toUpperCase()}
      </div>
      <div className="mb-3" data-dom-id="object-card-score">
        <div className="flex items-center justify-between text-[10px] text-muted-foreground mb-1">
          <span>风险评分</span>
          <span className="font-medium text-foreground">{score}</span>
        </div>
        <div className="h-1.5 bg-muted rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full ${TONE_BAR[DERIVED_TONE[status]]}`}
            style={{ width: `${score}%` }}
          />
        </div>
      </div>
      {tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-4">
          {tags.map((t) => (
            <span key={t} className="px-1.5 py-0.5 rounded text-[10px] bg-muted text-muted-foreground">
              {t}
            </span>
          ))}
        </div>
      )}
      <div className="mt-auto pt-3 border-t border-border flex items-center justify-between">
        <div className="text-[10px] text-muted-foreground">
          Rev {obj.revision} · {relTime(obj.updated_at)}
        </div>
        <button
          type="button"
          data-dom-id="object-card-detail"
          onClick={onOpenDetail}
          className="text-xs text-primary hover:underline flex items-center gap-1"
        >
          查看详情 <ArrowRight className="w-3 h-3" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
