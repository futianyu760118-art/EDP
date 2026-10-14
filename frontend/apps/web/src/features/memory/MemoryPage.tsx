import { Skeleton } from "antd";
import { Brain, ChevronDown, ChevronRight } from "lucide-react";
import { Fragment, useState } from "react";
import { CursorPagination, EmptyState, MonoId, StatusPill, type StatusPillTone } from "@edp/shared";
import { fmtDateTime } from "../../lib/labels";
import { MEMORY_PAGE_LIMIT, type MemoryListItem, type MemoryStatus } from "./api";
import { useCapabilities } from "../capabilities/hooks";
import { useMemoriesList } from "./hooks";

/** 评审状态 → pill tone（CANDIDATE info / APPROVED success / REJECTED error）。 */
function memoryStatusTone(status: string): StatusPillTone {
  const map: Record<string, StatusPillTone> = {
    CANDIDATE: "info",
    APPROVED: "success",
    REJECTED: "error",
  };
  return map[status] ?? "muted";
}

const STATUS_CHIPS: { value: "" | MemoryStatus; label: string }[] = [
  { value: "", label: "全部" },
  { value: "CANDIDATE", label: "候选 CANDIDATE" },
  { value: "APPROVED", label: "已采纳 APPROVED" },
  { value: "REJECTED", label: "已驳回 REJECTED" },
];

/** 内容摘要：content.summary 截断（无 summary 回退 JSON 首行）。 */
function contentSummary(content: Record<string, unknown>): string {
  const summary = typeof content.summary === "string" ? content.summary : JSON.stringify(content);
  return summary.length > 48 ? `${summary.slice(0, 45)}…` : summary;
}

/** 行展开只读详情：content 全文 JSON + 来源（source_type/source_id）+ 评审信息。 */
function ExpandedDetail({ memory }: { memory: MemoryListItem }) {
  const cells: { label: string; value: string }[] = [
    { label: "来源类型", value: memory.source_type },
    { label: "来源 ID", value: memory.source_id },
    { label: "评审人", value: memory.reviewed_by ?? "—" },
    { label: "评审时间", value: memory.reviewed_at ? fmtDateTime(memory.reviewed_at) : "—" },
    { label: "创建时间", value: fmtDateTime(memory.created_at) },
  ];
  return (
    <div className="px-4 py-3 bg-muted/50 space-y-3" data-dom-id={`memory-detail-${memory.memory_id}`}>
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-2 text-[11px]">
        {cells.map((c) => (
          <div key={c.label} className="bg-muted rounded-md px-2.5 py-2">
            <span className="text-muted-foreground block">{c.label}</span>
            <span className="font-medium text-foreground break-all">{c.value}</span>
          </div>
        ))}
      </div>
      <div>
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">内容全文（content）</div>
        <pre className="bg-muted border border-border rounded-lg p-3 max-h-56 overflow-auto font-mono text-[11px] text-foreground whitespace-pre-wrap break-all">
          {JSON.stringify(memory.content, null, 2)}
        </pre>
      </div>
    </div>
  );
}

/**
 * 候选记忆页（EDP-503，无设计稿——13.7 表格模式）：capability 筛选 chips + status
 * chips + 表格（memory_id 短 ID/capability/内容摘要/status pill/created_at）+ 游标
 * 分页 + 空态；行展开只读详情（content 全文/来源/评审信息）。本页只读——评审操作
 * 由 Agent 中枢接管（W6），无任何操作按钮。
 */
export function MemoryPage() {
  const [capability, setCapability] = useState("");
  const [status, setStatus] = useState<"" | MemoryStatus>("");
  const [cursorStack, setCursorStack] = useState<(string | null)[]>([null]);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const { options: capabilityOptions, isFallback: capabilityFallback } = useCapabilities();
  const capabilityChips: { value: string; label: string }[] = [
    { value: "", label: "全部能力" },
    ...capabilityOptions,
  ];

  const pageIndex = cursorStack.length - 1;
  const cursor = cursorStack[pageIndex];
  const listQuery = useMemoriesList(
    { status: status || undefined, capabilityId: capability || undefined },
    cursor,
  );

  const items = listQuery.data?.items ?? [];
  const total = listQuery.data?.total;
  const nextCursor = listQuery.data?.next_cursor ?? null;

  const resetCursor = () => setCursorStack([null]);
  const clearFilters = () => {
    setCapability("");
    setStatus("");
    resetCursor();
  };

  const offset = pageIndex * MEMORY_PAGE_LIMIT;
  const start = items.length === 0 ? 0 : offset + 1;
  const end = offset + items.length;
  const navLocked = listQuery.isFetching;
  const hasFilter = capability !== "" || status !== "";

  return (
    <div className="flex flex-col gap-4 h-full" data-dom-id="memory-page">
      <section className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold text-foreground">候选记忆</h1>
        <p className="text-xs text-muted-foreground">
          Agent 执行沉淀的记忆候选检索（只读）：评审操作由 Agent 中枢接管（W6），本页不提供审批入口。
        </p>
      </section>

      <section className="bg-card border border-border rounded-xl p-3 space-y-3" data-dom-id="memory-toolbar">
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="能力筛选">
          <span className="text-[11px] text-muted-foreground">能力</span>
          {capabilityChips.map((chip) => (
            <button
              key={chip.value || "all"}
              type="button"
              data-dom-id={`memory-capability-${chip.value || "all"}`}
              aria-pressed={capability === chip.value}
              onClick={() => {
                setCapability(chip.value);
                resetCursor();
              }}
              className={`h-7 px-2.5 rounded-full text-[11px] font-medium border ${
                capability === chip.value
                  ? "bg-primary text-primary-foreground border-primary"
                  : "bg-card text-muted-foreground border-border hover:bg-muted"
              }`}
            >
              {chip.label}
            </button>
          ))}
          {capabilityFallback && (
            <span
              data-dom-id="memory-capability-fallback"
              title="能力清单接口不可用或为空，筛选已回退内置清单"
              className="text-[10px] text-muted-foreground"
            >
              能力清单：内置
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="状态筛选">
          <span className="text-[11px] text-muted-foreground">状态</span>
          {STATUS_CHIPS.map((chip) => (
            <button
              key={chip.value || "all"}
              type="button"
              data-dom-id={`memory-status-${chip.value || "all"}`}
              aria-pressed={status === chip.value}
              onClick={() => {
                setStatus(chip.value);
                resetCursor();
              }}
              className={`h-7 px-2.5 rounded-full text-[11px] font-medium border ${
                status === chip.value
                  ? "bg-muted text-foreground border-foreground/30"
                  : "bg-card text-muted-foreground border-border hover:bg-muted"
              }`}
            >
              {chip.label}
            </button>
          ))}
        </div>
      </section>

      {listQuery.isError && listQuery.data == null ? (
        <div
          className="bg-card border border-border rounded-xl text-xs text-muted-foreground py-10 text-center"
          data-dom-id="memory-error"
        >
          记忆列表暂不可用
        </div>
      ) : listQuery.data == null ? (
        <div className="bg-card border border-border rounded-xl p-4">
          <Skeleton active paragraph={{ rows: 6 }} />
        </div>
      ) : items.length === 0 ? (
        <div data-dom-id="memory-empty">
          <EmptyState
            icon={<Brain className="w-7 h-7" />}
            title="暂无候选记忆"
            description={
              hasFilter
                ? "当前筛选条件没有匹配结果，请调整筛选条件。"
                : "Agent 执行尚未沉淀记忆候选；评审操作由 Agent 中枢接管（W6）。"
            }
            primaryAction={hasFilter ? { label: "清空筛选", onClick: clearFilters } : undefined}
          />
        </div>
      ) : (
        <section
          className="bg-card border border-border rounded-xl overflow-hidden flex-1 min-h-0 flex flex-col"
          data-dom-id="memory-content"
        >
          <div className="table-scroll flex-1 min-h-0">
          <table className="w-full text-xs" data-dom-id="memory-table">
            <thead>
              <tr className="text-left text-muted-foreground border-b border-border">
                <th className="w-8 px-2 py-2.5" aria-label="展开" />
                <th className="px-4 py-2.5 font-medium">Memory ID</th>
                <th className="px-4 py-2.5 font-medium">Capability</th>
                <th className="px-4 py-2.5 font-medium">内容摘要</th>
                <th className="px-4 py-2.5 font-medium">状态</th>
                <th className="px-4 py-2.5 font-medium">创建时间</th>
              </tr>
            </thead>
            <tbody>
              {items.map((memory) => {
                const expanded = expandedId === memory.memory_id;
                return (
                  <Fragment key={memory.memory_id}>
                    <tr
                      data-dom-id={`memory-row-${memory.memory_id}`}
                      onClick={() => setExpandedId(expanded ? null : memory.memory_id)}
                      className="border-b border-border last:border-b-0 hover:bg-muted cursor-pointer"
                      aria-expanded={expanded}
                    >
                      <td className="px-2 py-2.5 text-muted-foreground">
                        {expanded ? (
                          <ChevronDown className="w-3.5 h-3.5" aria-hidden="true" />
                        ) : (
                          <ChevronRight className="w-3.5 h-3.5" aria-hidden="true" />
                        )}
                      </td>
                      <td className="px-4 py-2.5">
                        <MonoId prefix="mem" id={memory.memory_id.slice(-8)} full={memory.memory_id} />
                      </td>
                      <td className="px-4 py-2.5">
                        {memory.capability_id != null ? (
                          <MonoId
                            prefix="cap"
                            id={memory.capability_id.slice(-8)}
                            full={memory.capability_id}
                            copyable={false}
                          />
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-foreground/90 max-w-xs truncate" title={contentSummary(memory.content)}>
                        {contentSummary(memory.content)}
                      </td>
                      <td className="px-4 py-2.5">
                        <StatusPill tone={memoryStatusTone(memory.status)} label={memory.status} size="sm" />
                      </td>
                      <td className="px-4 py-2.5 text-muted-foreground">{fmtDateTime(memory.created_at)}</td>
                    </tr>
                    {expanded && (
                      <tr className="border-b border-border last:border-b-0">
                        <td colSpan={6} className="p-0">
                          <ExpandedDetail memory={memory} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
          </div>
          {total != null ? (
            <CursorPagination
              start={start}
              end={end}
              total={total}
              page={pageIndex + 1}
              hasPrev={pageIndex > 0 && !navLocked}
              hasNext={nextCursor != null && !navLocked}
              onPrev={() => setCursorStack((s) => (s.length > 1 ? s.slice(0, -1) : s))}
              onNext={() => {
                if (nextCursor) setCursorStack((s) => [...s, nextCursor]);
              }}
            />
          ) : null}
        </section>
      )}
    </div>
  );
}
