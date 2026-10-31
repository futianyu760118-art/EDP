import { DatabaseZap } from "lucide-react";
import { TOOL_DEFS } from "./api";
import { TryQueryForm } from "./TryQueryForm";

/**
 * Agent 工具页（EDP-503，无设计稿——13.7 卡片模式）：六只读数据工具（Read-Only）
 * 清单 chips + 在线试查表单；无任何写操作，对象不存在/越权按 13.9.2 呈现。
 */
export function ToolsPage() {
  return (
    <div className="space-y-4" data-dom-id="tools-page">
      <section className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold text-foreground">Agent 工具</h1>
        <p className="text-xs text-muted-foreground">
          只读数据工具（Read-Only）：Agent 执行取数的六接口在线试查，响应携带 evidence_hint 可回溯证据链。
        </p>
      </section>

      <section
        className="flex flex-wrap items-center gap-2"
        role="list"
        aria-label="六只读工具清单"
        data-dom-id="tools-chips"
      >
        <DatabaseZap className="w-4 h-4 text-muted-foreground" aria-hidden="true" />
        {TOOL_DEFS.map((tool) => (
          <span
            key={tool.value}
            role="listitem"
            data-dom-id={`tools-chip-${tool.value}`}
            title={tool.description}
            className="px-2.5 py-1 rounded-full bg-muted text-muted-foreground text-[11px] font-medium"
          >
            {tool.label}
          </span>
        ))}
      </section>

      <TryQueryForm />
    </div>
  );
}
