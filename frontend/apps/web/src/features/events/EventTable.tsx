import { MonoId, StatusPill, type StatusPillTone } from "@edp/shared";
import { eventTypeDisplay, fmtDateTime, sourceLabel } from "../../lib/labels";
import type { EventResponse } from "../../mocks/types";

/** 事件流表格 9 列（spec §7.1 / 设计 13.6.2）：视觉基线 `原型设计/pages/事件流.html` 行 420~528。 */
const COLUMNS = ["事件", "类型", "对象", "描述", "发生时间", "接入耗时", "来源", "状态", "操作"];

const DELIVERY_TONE: Record<string, StatusPillTone> = {
  DELIVERED: "success",
  PENDING: "info",
  DEAD_LETTER: "error",
};

/** 描述回退链：data.summary → data.reason → data.note → 「—」。 */
function describe(e: EventResponse): string {
  for (const key of ["summary", "reason", "note"] as const) {
    const value = e.data?.[key];
    if (typeof value === "string" && value.length > 0) return value;
  }
  return "—";
}

/** 接入耗时：ms；>1000 → 秒（保留一位小数）。 */
function latencyLabel(ms?: number | null): string {
  if (ms == null) return "—";
  return ms > 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

export function EventTable({
  events,
  onDetail,
}: {
  events: EventResponse[];
  onDetail?: (event: EventResponse) => void;
}) {
  return (
    <div className="table-scroll flex-1 min-h-0" data-dom-id="events-table">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-muted-foreground border-b border-border">
            {COLUMNS.map((h) => (
              <th key={h} className="px-4 py-3 font-medium whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {events.map((e) => {
            const type = eventTypeDisplay(e.event_type);
            const description = describe(e);
            return (
              <tr
                key={e.event_id}
                data-dom-id="event-row"
                className="border-b border-border last:border-b-0"
              >
                <td className="px-4 py-3">
                  <MonoId prefix="evt" id={e.event_id.slice(-8)} full={e.event_id} copyable={false} />
                </td>
                <td className="px-4 py-3">
                  <StatusPill tone={type.tone} label={type.label} size="sm" />
                </td>
                <td className="px-4 py-3">
                  {e.object_source_id != null ? (
                    <MonoId
                      id={e.object_source_id}
                      length={e.object_source_id.length}
                      copyable={false}
                    />
                  ) : (
                    <MonoId id={e.object_id} hashFormat copyable={false} />
                  )}
                </td>
                <td className="px-4 py-3 max-w-[240px] truncate" title={description}>
                  {description}
                </td>
                <td className="px-4 py-3 whitespace-nowrap">{fmtDateTime(e.occurred_at)}</td>
                <td className="px-4 py-3">{latencyLabel(e.ingest_latency_ms)}</td>
                <td className="px-4 py-3">{sourceLabel(e.source_system)}</td>
                <td className="px-4 py-3">
                  {e.delivery_status != null ? (
                    <StatusPill
                      tone={DELIVERY_TONE[e.delivery_status] ?? "muted"}
                      label={e.delivery_status}
                      size="sm"
                    />
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-4 py-3">
                  <button
                    type="button"
                    data-dom-id="event-row-detail"
                    onClick={() => onDetail?.(e)}
                    className="text-primary hover:underline"
                  >
                    详情
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
