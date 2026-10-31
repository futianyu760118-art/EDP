import { useQuery } from "@tanstack/react-query";
import { ShieldCheck, X } from "lucide-react";
import type { ReactNode } from "react";
import { MonoId, StatusPill, type StatusPillTone } from "@edp/shared";
import { eventTypeDisplay, fmtDateTime, sourceLabel } from "../../lib/labels";
import type { EventResponse } from "../../mocks/types";
import { eventsApi } from "./api";

/** delivery_status → pill tone（同 EventTable）。 */
const DELIVERY_TONE: Record<string, StatusPillTone> = {
  DELIVERED: "success",
  PENDING: "info",
  DEAD_LETTER: "error",
};

/** 接入耗时：ms；>1000 → 秒（同 EventTable）。 */
function latencyLabel(ms?: number | null): string {
  if (ms == null) return "—";
  return ms > 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

const riskTone = (level: string): StatusPillTone =>
  level === "P0" ? "error" : level === "P1" ? "warning" : "info";

/**
 * 事件详情抽屉（spec §7.1）：右侧 420px（同 RiskDrawer 尺寸约定）——
 * 头部短 ID + 类型 pill + 状态 pill；字段区（对象/来源/发生时间/接入耗时/actor/score/
 * risk/result_type）；data JSON 原文（max-height 滚动）；关联证据经
 * `GET /evidence?ref_type=RESULT&ref_id=` 逆向追溯，无则「无关联证据」空态。
 */
export function EventDetailDrawer({
  event,
  open,
  onClose,
}: {
  event: EventResponse | null;
  open: boolean;
  onClose: () => void;
}) {
  const eventId = event?.event_id ?? "";
  const evidenceQuery = useQuery({
    queryKey: ["events", "evidence", eventId],
    queryFn: () => eventsApi.resultEvidence(eventId),
    enabled: open && event != null,
  });
  if (!open || !event) return null;

  const type = eventTypeDisplay(event.event_type);
  const objectLabel = event.object_source_id ?? event.object_id;
  const evidence = evidenceQuery.data?.items ?? [];

  const cells: { label: string; value: ReactNode }[] = [
    {
      label: "对象",
      value: <MonoId id={objectLabel} length={objectLabel.length} copyable={false} />,
    },
    { label: "来源", value: sourceLabel(event.source_system) },
    { label: "发生时间", value: fmtDateTime(event.occurred_at) },
    { label: "接入耗时", value: latencyLabel(event.ingest_latency_ms) },
    { label: "Actor", value: event.actor_id ?? "—" },
    { label: "Score", value: event.score != null ? event.score.toFixed(2) : "—" },
    {
      label: "Risk",
      value:
        event.risk_level != null ? (
          <StatusPill tone={riskTone(event.risk_level)} label={event.risk_level} size="sm" />
        ) : (
          "—"
        ),
    },
    { label: "Result Type", value: event.result_type ?? "—" },
  ];

  return (
    <div
      className="fixed inset-y-0 left-[250px] right-0 z-30 flex justify-end bg-foreground/15 backdrop-blur-sm"
      data-dom-id="event-drawer-overlay"
    >
      <div
        data-dom-id="event-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="event-drawer-title"
        className="w-[420px] h-full bg-card border-l border-border shadow-2 flex flex-col rounded-l-lg"
      >
        <div className="flex items-start justify-between gap-4 p-4 border-b border-border">
          <div className="min-w-0">
            <div className="flex items-center gap-2 mb-1.5 flex-wrap">
              <h2 id="event-drawer-title" className="text-lg font-semibold text-foreground">
                事件{" "}
                <MonoId
                  prefix="evt"
                  id={event.event_id.slice(-8)}
                  full={event.event_id}
                  copyable={false}
                />
              </h2>
              <span className="shrink-0">
                <StatusPill tone={type.tone} label={type.label} size="sm" />
              </span>
              {event.delivery_status != null && (
                <span className="shrink-0">
                  <StatusPill
                    tone={DELIVERY_TONE[event.delivery_status] ?? "muted"}
                    label={event.delivery_status}
                    size="sm"
                  />
                </span>
              )}
            </div>
            <div className="text-[11px] text-muted-foreground">
              {sourceLabel(event.source_system)} · {fmtDateTime(event.occurred_at)}
            </div>
          </div>
          <button
            type="button"
            data-dom-id="event-drawer-close"
            aria-label="关闭"
            onClick={onClose}
            className="shrink-0 w-8 h-8 rounded-lg border border-border bg-card text-muted-foreground hover:bg-muted grid place-items-center"
          >
            <X className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-5">
          <div data-dom-id="event-drawer-info">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-3">
              事件字段
            </div>
            <div className="grid grid-cols-2 gap-2 text-[11px]">
              {cells.map((c) => (
                <div key={c.label} className="bg-muted rounded-md px-2.5 py-2">
                  <span className="text-muted-foreground block">{c.label}</span>
                  <span className="font-medium text-foreground break-all">{c.value}</span>
                </div>
              ))}
            </div>
          </div>

          <div data-dom-id="event-drawer-data">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-3">
              事件数据
            </div>
            <pre className="bg-muted border border-border rounded-lg p-3 max-h-[280px] overflow-auto font-mono text-[11px] text-foreground whitespace-pre-wrap break-all">
              {JSON.stringify(event.data ?? {}, null, 2)}
            </pre>
          </div>

          <div data-dom-id="event-drawer-evidence">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-3">
              关联证据
            </div>
            <div className="space-y-2">
              {evidence.map((ev) => (
                <div
                  key={ev.evidence_id}
                  data-dom-id="event-drawer-evidence-row"
                  className="flex items-center gap-3 border border-border rounded-lg p-3"
                >
                  <div className="w-8 h-8 rounded-lg bg-primary-50 text-primary grid place-items-center shrink-0">
                    <ShieldCheck className="w-4 h-4" aria-hidden="true" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-xs font-medium text-foreground truncate">
                      <MonoId
                        prefix="ev"
                        id={ev.evidence_id.slice(-8)}
                        full={ev.evidence_id}
                        copyable={false}
                      />
                    </div>
                    <div className="text-[10px] text-muted-foreground">
                      {ev.source_system} · {fmtDateTime(ev.captured_at)}
                    </div>
                  </div>
                </div>
              ))}
              {!evidenceQuery.isPending && evidence.length === 0 && (
                <div
                  className="text-xs text-muted-foreground py-4 text-center"
                  data-dom-id="event-drawer-evidence-empty"
                >
                  无关联证据
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
