import { ChevronRight } from "lucide-react";
import { useState } from "react";
import { StatusPill, type StatusPillTone } from "@edp/shared";
import type { ToolCallItem } from "./api";

/** 工具调用 HTTP 状态 → pill tone（2xx success / 4xx warning / 5xx·null muted·error）。 */
function statusTone(statusCode: number | null): StatusPillTone {
  if (statusCode == null) return "muted";
  if (statusCode < 300) return "success";
  if (statusCode < 500) return "warning";
  return "error";
}

/** args 摘要：input JSON 截断为单行（≈60 字符），空输入回退 —。 */
function argsSummary(input: ToolCallItem["input"]): string {
  if (input == null) return "—";
  const text = JSON.stringify(input);
  return text.length > 60 ? `${text.slice(0, 57)}…` : text;
}

function latencyLabel(ms: number | null): string {
  return ms != null ? `${ms}ms` : "—";
}

/**
 * 工具调用树（EDP-503，13.7 缩进树模式）：契约 tool_calls 为 seq 升序扁平数组
 * （无 parent 字段），层级呈现 = 一级调用行（name → args 摘要 → duration → status）
 * + 二级展开明细（input/output/error 全量 JSON，缩进挂靠所属调用行）。
 */
export function ToolCallsTree({ calls }: { calls: ToolCallItem[] }) {
  const [expandedIds, setExpandedIds] = useState<Record<string, boolean>>({});
  if (calls.length === 0) {
    return (
      <div className="text-xs text-muted-foreground py-3 text-center" data-dom-id="toolcalls-empty">
        无工具调用记录
      </div>
    );
  }

  const toggle = (callId: string) => setExpandedIds((s) => ({ ...s, [callId]: !s[callId] }));

  return (
    <div role="tree" aria-label="工具调用链" data-dom-id="toolcalls-tree" className="space-y-1">
      {calls.map((call) => {
        const expanded = expandedIds[call.call_id] ?? false;
        return (
          <div key={call.call_id} role="treeitem" aria-level={1} aria-expanded={expanded}>
            <button
              type="button"
              data-dom-id={`toolcall-row-${call.seq}`}
              onClick={() => toggle(call.call_id)}
              className="w-full flex items-center gap-2 bg-muted border border-border rounded-lg px-2.5 py-2 text-left hover:bg-card"
            >
              <ChevronRight
                className={`w-3.5 h-3.5 text-muted-foreground shrink-0 transition-transform ${expanded ? "rotate-90" : ""}`}
                aria-hidden="true"
              />
              <span className="font-mono text-[11px] text-foreground shrink-0" title={call.tool_name}>
                {call.seq}. {call.tool_name}
              </span>
              <span className="font-mono text-[10px] text-muted-foreground truncate flex-1" title={JSON.stringify(call.input ?? {})}>
                {argsSummary(call.input)}
              </span>
              <span className="text-[10px] text-muted-foreground shrink-0" title={`latency ${call.latency_ms ?? "—"}ms`}>
                {latencyLabel(call.latency_ms)}
              </span>
              <span className="shrink-0">
                <StatusPill tone={statusTone(call.status_code)} label={call.status_code ?? "—"} size="sm" />
              </span>
            </button>
            {expanded && (
              <div
                role="treeitem"
                aria-level={2}
                data-dom-id={`toolcall-detail-${call.seq}`}
                className="ml-6 mt-1 border-l-2 border-border pl-3 space-y-2"
              >
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Input</div>
                  <pre className="bg-muted border border-border rounded-md p-2 max-h-40 overflow-auto font-mono text-[10px] whitespace-pre-wrap break-all">
                    {JSON.stringify(call.input ?? {}, null, 2)}
                  </pre>
                </div>
                {call.error != null && (
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-state-error mb-1">Error</div>
                    <pre className="bg-state-error-bg border border-state-error/40 rounded-md p-2 max-h-40 overflow-auto font-mono text-[10px] whitespace-pre-wrap break-all">
                      {JSON.stringify(call.error, null, 2)}
                    </pre>
                  </div>
                )}
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Output</div>
                  <pre className="bg-muted border border-border rounded-md p-2 max-h-40 overflow-auto font-mono text-[10px] whitespace-pre-wrap break-all">
                    {JSON.stringify(call.output ?? {}, null, 2)}
                  </pre>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
