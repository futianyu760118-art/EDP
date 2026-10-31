import { message, Skeleton } from "antd";
import { Check, ExternalLink, Package, Plus, ShieldCheck, X } from "lucide-react";
import { MonoId, StatusPill, VerticalTimeline } from "@edp/shared";
import { fmt, fmtDateTime } from "../../../lib/labels";
import type { ObjectResponse } from "../../../mocks/types";
import { useRiskEvent, useRiskObject, useRiskObjectEvents, useRiskObjectEvidence } from "./hooks";

const riskTone = (level: string) =>
  level === "P0" ? "error" : level === "P1" ? "warning" : "info";

function attrString(obj: ObjectResponse | undefined, key: string): string | undefined {
  const v = obj?.attributes?.[key];
  return typeof v === "string" ? v : undefined;
}

/**
 * 风险详情抽屉（设计 13.7 #8；视觉基线：`原型设计/pages/风险详情 - 抽屉.html` 行 643~771 ——
 * 右侧 420px fixed 面板：头部短 ID/等级/meta、受影响对象卡、事件时间线、关联证据、底部操作）。
 * W4 EDP-403 自 features/overview 泛化提升：eventId 必填——事件详情 → 受影响对象 →
 * 对象事件/证据按需联动取数（总览风险卡与闭环案例详情共用）；短 ID 统一尾 8（W3-31）。
 */
export interface RiskDrawerProps {
  /** 风险事件 id（ebms exceptions / case detail.event.event_id） */
  eventId: string | null | undefined;
  open: boolean;
  onClose: () => void;
}

export function RiskDrawer({ eventId, open, onClose }: RiskDrawerProps) {
  const enabled = open && eventId != null;
  const eventQuery = useRiskEvent(eventId, open);
  const event = eventQuery.data;
  const objectId = event?.object_id;
  const objectQuery = useRiskObject(objectId, enabled);
  const eventsQuery = useRiskObjectEvents(objectId, enabled);
  const evidenceQuery = useRiskObjectEvidence(objectId, enabled);
  if (!open || eventId == null) return null;

  const obj = objectQuery.data;
  const amount = typeof obj?.attributes?.amount === "number" ? fmt(obj.attributes.amount) : "—";
  const deliveryDate = attrString(obj, "delivery_date") ?? "—";
  const events = eventsQuery.data?.items ?? [];
  const evidence = evidenceQuery.data?.items ?? [];
  const sourceNo = obj?.source_id ?? "—";
  const bodyReady = eventQuery.isSuccess;

  return (
    <div
      className="fixed inset-y-0 left-[250px] right-0 z-30 flex justify-end bg-foreground/15 backdrop-blur-sm"
      data-dom-id="risk-drawer-overlay"
    >
      <div
        data-dom-id="risk-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="risk-drawer-title"
        className="w-[420px] h-full bg-card border-l border-border shadow-2 flex flex-col rounded-l-lg"
      >
        <div className="flex items-start justify-between gap-4 p-4 border-b border-border">
          <div className="min-w-0">
            <div className="flex items-center gap-2 mb-1.5">
              <h2 id="risk-drawer-title" className="text-lg font-semibold text-foreground truncate">
                风险事件 <MonoId prefix="RSK" id={eventId.slice(-8)} full={eventId} />
              </h2>
              {event?.risk_level != null && (
                <span className="shrink-0">
                  <StatusPill tone={riskTone(event.risk_level)} label={event.risk_level} size="sm" />
                </span>
              )}
            </div>
            <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
              <span className="inline-flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-state-warning" aria-hidden="true" />
                OPEN
              </span>
              <span>{event?.result_type ?? "—"}</span>
              <span>{event != null ? fmtDateTime(event.occurred_at) : "—"}</span>
            </div>
          </div>
          <button
            type="button"
            data-dom-id="risk-drawer-close"
            aria-label="关闭"
            onClick={onClose}
            className="shrink-0 w-8 h-8 rounded-lg border border-border bg-card text-muted-foreground hover:bg-muted grid place-items-center"
          >
            <X className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-5">
          {!bodyReady ? (
            eventQuery.isError ? (
              <div className="text-xs text-muted-foreground py-8 text-center" data-dom-id="risk-drawer-error">
                风险事件暂不可用
              </div>
            ) : (
              <Skeleton active paragraph={{ rows: 8 }} />
            )
          ) : (
            <>
              <div className="border border-border rounded-lg p-3" data-dom-id="risk-drawer-object">
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">受影响对象</div>
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-primary-50 text-primary grid place-items-center shrink-0">
                    <Package className="w-5 h-5" aria-hidden="true" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-foreground truncate">
                      {attrString(obj, "name") ?? sourceNo}
                    </div>
                    <div className="text-[11px] text-muted-foreground truncate">
                      {sourceNo} · {obj?.object_type ?? "—"}
                    </div>
                  </div>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
                  <div className="bg-muted rounded-md px-2.5 py-2">
                    <span className="text-muted-foreground block">金额</span>
                    <span className="font-medium text-foreground" data-dom-id="risk-drawer-amount">
                      {amount}
                    </span>
                  </div>
                  <div className="bg-muted rounded-md px-2.5 py-2">
                    <span className="text-muted-foreground block">交付日期</span>
                    <span className="font-medium text-foreground" data-dom-id="risk-drawer-delivery">
                      {deliveryDate}
                    </span>
                  </div>
                </div>
              </div>

              <div data-dom-id="risk-drawer-timeline">
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-3">事件时间线</div>
                <VerticalTimeline
                  items={events.map((e) => ({
                    time: fmtDateTime(e.occurred_at),
                    text: e.event_type,
                    meta: `${e.event_id.slice(-8)} · ${e.source_system}`,
                    tone: e.risk_level === "P0" ? "error" : e.risk_level === "P1" ? "warning" : "primary",
                  }))}
                />
                {!eventsQuery.isPending && events.length === 0 && (
                  <div className="text-xs text-muted-foreground">暂无关联事件</div>
                )}
              </div>

              <div data-dom-id="risk-drawer-evidence">
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-3">关联证据</div>
                <div className="space-y-2">
                  {evidence.map((ev) => (
                    <button
                      key={ev.evidence_id}
                      type="button"
                      data-dom-id="risk-evidence-row"
                      title="W3 证据库页跳转"
                      className="w-full text-left flex items-center gap-3 border border-border rounded-lg p-3 hover:bg-muted transition-colors group"
                    >
                      <div className="w-8 h-8 rounded-lg bg-primary-50 text-primary grid place-items-center shrink-0">
                        <ShieldCheck className="w-4 h-4" aria-hidden="true" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="text-xs font-medium text-foreground group-hover:text-primary truncate">
                          <MonoId prefix="ev" id={ev.evidence_id} copyable={false} />
                        </div>
                        <div className="text-[10px] text-muted-foreground">
                          {ev.source_system} · {fmtDateTime(ev.captured_at)}
                        </div>
                      </div>
                      <ExternalLink className="w-3.5 h-3.5 text-muted-foreground group-hover:text-primary" aria-hidden="true" />
                    </button>
                  ))}
                  {!evidenceQuery.isPending && evidence.length === 0 && (
                    <div className="text-xs text-muted-foreground py-4 text-center" data-dom-id="risk-evidence-empty">
                      暂无关联证据
                    </div>
                  )}
                </div>
              </div>
            </>
          )}
        </div>

        <div className="p-4 border-t border-border flex items-center justify-end gap-2">
          <button
            type="button"
            data-dom-id="risk-drawer-create-task"
            onClick={() => message.info("W3 能力接入后可用")}
            className="h-9 px-4 border border-border bg-card text-foreground rounded-lg text-xs font-medium hover:bg-muted flex items-center gap-1.5"
          >
            <Plus className="w-4 h-4" aria-hidden="true" />
            创建任务
          </button>
          {/* 本地乐观置灰延后：无真实状态变更端点，W3 收口（T5 评审 Minor） */}
          <button
            type="button"
            data-dom-id="risk-drawer-mark"
            onClick={() => message.info("W3 能力接入后可用")}
            className="h-9 px-4 bg-primary text-primary-foreground rounded-lg text-xs font-medium hover:opacity-90 flex items-center gap-1.5"
          >
            <Check className="w-4 h-4" aria-hidden="true" />
            标记处理
          </button>
        </div>
      </div>
    </div>
  );
}
