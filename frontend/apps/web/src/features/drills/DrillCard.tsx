import { ExternalLink } from "lucide-react";
import { StatusPill, type StatusPillTone } from "@edp/shared";
import { fmt, fmtDateTime } from "../../lib/labels";
import type { DrillRecord } from "./api";

/** 演练中文名（drill_type 下划线值 → 13.7 卡头主标题；未命中回退原值）。 */
export const DRILL_TYPE_LABELS: Record<string, string> = {
  switchover: "主备切换",
  pitr: "整库 PITR 恢复",
  tenant_restore: "租户级恢复",
};

/** 结果 pill 映射：SUCCEEDED 绿 / FAILED 红 / PLANNED 灰；未命中回退 muted 原值。 */
export const DRILL_RESULT_LABELS: Record<string, { label: string; tone: StatusPillTone }> = {
  SUCCEEDED: { label: "成功", tone: "success" },
  FAILED: { label: "失败", tone: "error" },
  PLANNED: { label: "计划中", tone: "muted" },
};

function drillTypeLabel(drillType: string): string {
  return DRILL_TYPE_LABELS[drillType] ?? drillType;
}

function resultDisplay(result: string): { label: string; tone: StatusPillTone } {
  return DRILL_RESULT_LABELS[result] ?? { label: result, tone: "muted" };
}

/** RTO 整秒千分位（1234 → `1,234 秒`；null → 「—」，PLANNED 态）。 */
function fmtRto(seconds: number | null | undefined): string {
  return seconds == null ? "—" : `${fmt(seconds)} 秒`;
}

/** RPO 折毫秒千分位（读数归档口径 sub-second；null → 「—」）。 */
function fmtRpo(seconds: number | null | undefined): string {
  return seconds == null ? "—" : `${fmt(seconds * 1000)} ms`;
}

function readingValue(value: unknown): string {
  if (value == null) return "—";
  return typeof value === "string" ? value : String(value);
}

/**
 * 演练记录卡（EDP-502，无设计稿——沿 13.7 卡片/键值表交互模式）：
 * 卡头（中文名 + drill_type mono 小字 + 结果 pill）+ RTO/RPO KPI + 拓扑/执行时间
 * + readings 自由键值表（空对象隐藏）+ 手册路径（仅文本 + 外链图标，不破窗）。
 * PLANNED 态整体降饱和（数字「—」+「未执行」+ 灰 pill）。
 */
export function DrillCard({ drill }: { drill: DrillRecord }) {
  const domId = `drills-card-${drill.drill_type}`;
  const planned = drill.result === "PLANNED";
  const result = resultDisplay(drill.result);
  const readings = Object.entries(drill.readings ?? {});

  return (
    <section
      className={`bg-card border border-border rounded-xl p-4 ${planned ? "opacity-60" : ""}`}
      data-dom-id={domId}
    >
      <header className="flex items-start justify-between gap-4 mb-3">
        <div className="flex flex-col gap-0.5">
          <h2 className="text-sm font-semibold text-foreground">{drillTypeLabel(drill.drill_type)}</h2>
          <span className="font-mono text-[10px] text-muted-foreground" data-dom-id={`${domId}-type`}>
            {drill.drill_type}
          </span>
        </div>
        <span data-dom-id={`${domId}-pill`}>
          <StatusPill tone={result.tone} label={result.label} />
        </span>
      </header>

      <div className="grid grid-cols-2 gap-3 mb-3">
        <div
          className="rounded-lg bg-muted/50 px-3 py-2"
          data-dom-id={`${domId}-rto`}
        >
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground">RTO</p>
          <p className="text-lg font-semibold text-foreground tabular-nums">
            {fmtRto(planned ? null : drill.rto_seconds)}
          </p>
          {!planned && drill.drill_type === "switchover" && drill.rto_seconds === 0 && (
            <p className="text-[10px] text-muted-foreground" data-dom-id={`${domId}-rto-note`}>
              healthz 零中断口径，DB 写面见 readings
            </p>
          )}
        </div>
        <div
          className="rounded-lg bg-muted/50 px-3 py-2"
          data-dom-id={`${domId}-rpo`}
        >
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground">RPO</p>
          <p className="text-lg font-semibold text-foreground tabular-nums">
            {fmtRpo(planned ? null : drill.rpo_seconds)}
          </p>
        </div>
      </div>

      <div className="flex flex-col gap-1 text-[11px] mb-3">
        <p className="text-muted-foreground">
          拓扑：<span className="text-foreground">{drill.topology}</span>
        </p>
        <p className="text-muted-foreground" data-dom-id={`${domId}-executed`}>
          执行时间：
          <span className="text-foreground">
            {planned || drill.executed_at == null ? "未执行" : fmtDateTime(drill.executed_at)}
          </span>
        </p>
      </div>

      {readings.length > 0 && (
        <div
          className="border border-border rounded-lg overflow-hidden mb-3"
          data-dom-id={`${domId}-readings`}
        >
          <table className="w-full text-[11px]">
            <tbody className="divide-y divide-border">
              {readings.map(([key, value]) => (
                <tr key={key}>
                  <td className="px-3 py-1.5 text-muted-foreground align-top whitespace-nowrap w-1/3">
                    {key}
                  </td>
                  <td className="px-3 py-1.5 font-mono text-foreground break-all">
                    {readingValue(value)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-[11px] text-muted-foreground flex items-center gap-1" data-dom-id={`${domId}-manual`}>
        手册：<span className="font-mono">{drill.manual_url}</span>
        <ExternalLink className="w-3 h-3" aria-hidden="true" />
      </p>
    </section>
  );
}
