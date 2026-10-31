import { Skeleton } from "antd";
import { Coins, Hash, Timer, X } from "lucide-react";
import { MonoId, StatusPill, type StatusPillTone } from "@edp/shared";
import { fmt, fmtDateTime } from "../../lib/labels";
import { useTraceDetail } from "./hooks";
import { ToolCallsTree } from "./ToolCallsTree";

/** Trace 状态 → pill tone（SUCCEEDED success / RUNNING info / FAILED error / TIMEOUT warning / ABORTED muted）。 */
export function traceStatusTone(status: string): StatusPillTone {
  const map: Record<string, StatusPillTone> = {
    SUCCEEDED: "success",
    RUNNING: "info",
    FAILED: "error",
    TIMEOUT: "warning",
    ABORTED: "muted",
  };
  return map[status] ?? "muted";
}

/** 耗时：started_at → finished_at 差值（ms）；RUNNING（无 finished_at）回退 —。 */
export function traceLatencyLabel(startedAt: string, finishedAt: string | null): string {
  if (!finishedAt) return "—";
  const ms = new Date(finishedAt).getTime() - new Date(startedAt).getTime();
  if (Number.isNaN(ms) || ms < 0) return "—";
  return ms > 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

/** token_usage 三数卡（B.10：{prompt, completion, total}；契约为自由 JSONB，按三键取数）。 */
function TokenUsageCards({ usage }: { usage: Record<string, unknown> | null }) {
  const prompt = typeof usage?.prompt === "number" ? usage.prompt : null;
  const completion = typeof usage?.completion === "number" ? usage.completion : null;
  const total = typeof usage?.total === "number" ? usage.total : null;
  const cards: { key: string; label: string; value: number | null }[] = [
    { key: "prompt", label: "Prompt", value: prompt },
    { key: "completion", label: "Completion", value: completion },
    { key: "total", label: "Total", value: total },
  ];
  return (
    <div className="grid grid-cols-3 gap-2" data-dom-id="trace-token-usage">
      {cards.map((card) => (
        <div key={card.key} className="bg-muted rounded-lg px-2.5 py-2 text-center" data-dom-id={`trace-token-${card.key}`}>
          <div className="text-[10px] text-muted-foreground flex items-center justify-center gap-1">
            <Coins className="w-3 h-3" aria-hidden="true" />
            {card.label}
          </div>
          <div className="text-sm font-semibold text-foreground font-mono mt-0.5">
            {card.value != null ? fmt(card.value) : "—"}
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * Trace 详情抽屉（EDP-503，同 420px 抽屉模式）：trace 元信息卡（capability/agent/
 * latency/status pill/started·created_at）+ token_usage 三数字卡 + ToolCallsTree
 * 缩进树（name → args 摘要 → duration → status，展开二级明细）。
 */
export function TraceDetailDrawer({
  traceId,
  open,
  onClose,
}: {
  traceId: string | null;
  open: boolean;
  onClose: () => void;
}) {
  const detailQuery = useTraceDetail(open ? traceId : null);
  if (!open || traceId == null) return null;
  const detail = detailQuery.data;

  return (
    <div
      className="fixed inset-y-0 left-[250px] right-0 z-30 flex justify-end bg-foreground/15 backdrop-blur-sm"
      data-dom-id="trace-drawer-overlay"
    >
      <div
        data-dom-id="trace-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="trace-drawer-title"
        className="w-[420px] h-full bg-card border-l border-border shadow-2 flex flex-col rounded-l-lg"
      >
        <div className="flex items-start justify-between gap-4 p-4 border-b border-border">
          <div className="min-w-0">
            <div className="flex items-center gap-2 mb-1.5 flex-wrap">
              <h2 id="trace-drawer-title" className="text-lg font-semibold text-foreground">
                Trace{" "}
                <MonoId prefix="trc" id={traceId.slice(-8)} full={traceId} copyable={false} />
              </h2>
              {detail != null && (
                <span className="shrink-0">
                  <StatusPill tone={traceStatusTone(detail.status)} label={detail.status} size="sm" />
                </span>
              )}
            </div>
            {detail != null && (
              <div className="text-[11px] text-muted-foreground flex items-center gap-1.5 flex-wrap">
                <span className="font-mono">{detail.agent_id}</span>
                {detail.task_id != null && (
                  <span className="inline-flex items-center gap-0.5">
                    <Hash className="w-3 h-3" aria-hidden="true" />
                    <span className="font-mono">{detail.task_id}</span>
                  </span>
                )}
              </div>
            )}
          </div>
          <button
            type="button"
            data-dom-id="trace-drawer-close"
            aria-label="关闭"
            onClick={onClose}
            className="shrink-0 w-8 h-8 rounded-lg border border-border bg-card text-muted-foreground hover:bg-muted grid place-items-center"
          >
            <X className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-5">
          {detail == null ? (
            <Skeleton active paragraph={{ rows: 10 }} />
          ) : (
            <>
              <div data-dom-id="trace-drawer-meta">
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-3">轨迹信息</div>
                <div className="grid grid-cols-2 gap-2 text-[11px]">
                  <div className="bg-muted rounded-md px-2.5 py-2">
                    <span className="text-muted-foreground block">Capability</span>
                    <MonoId
                      prefix="cap"
                      id={(detail.capability_id ?? "").slice(-8)}
                      full={detail.capability_id ?? "—"}
                      copyable={false}
                    />
                  </div>
                  <div className="bg-muted rounded-md px-2.5 py-2">
                    <span className="text-muted-foreground block">耗时</span>
                    <span className="font-medium text-foreground inline-flex items-center gap-1">
                      <Timer className="w-3 h-3" aria-hidden="true" />
                      {traceLatencyLabel(detail.started_at, detail.finished_at)}
                    </span>
                  </div>
                  <div className="bg-muted rounded-md px-2.5 py-2">
                    <span className="text-muted-foreground block">开始时间</span>
                    <span className="font-medium text-foreground">{fmtDateTime(detail.started_at)}</span>
                  </div>
                  <div className="bg-muted rounded-md px-2.5 py-2">
                    <span className="text-muted-foreground block">创建时间</span>
                    <span className="font-medium text-foreground">{fmtDateTime(detail.created_at)}</span>
                  </div>
                </div>
              </div>

              <div data-dom-id="trace-drawer-token">
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-3">Token 用量</div>
                <TokenUsageCards usage={detail.token_usage} />
              </div>

              <div data-dom-id="trace-drawer-toolcalls">
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-3">
                  工具调用链（{detail.tool_calls?.length ?? 0} 次）
                </div>
                <ToolCallsTree calls={detail.tool_calls ?? []} />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
