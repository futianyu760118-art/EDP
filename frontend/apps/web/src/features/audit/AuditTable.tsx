import { Skeleton } from "antd";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { CursorPagination, EmptyState, FilterChips, StatusPill, type FilterChip } from "@edp/shared";
import { fmtDateTime } from "../../lib/labels";
import { AUDIT_PAGE_LIMIT, type AuditLogFilters, type AuditLogItem } from "./api";
import { useAuditLogs } from "./hooks";
import {
  ACTOR_TYPE_LABELS,
  ACTOR_TYPE_TONES,
  SEVERITY_LABELS,
  deriveActionLabel,
  resolveResourceType,
  severityOfAction,
  shortActorId,
} from "./vocab";

/** 资源类型下拉（接口 fullname 口径；裸名入参由后端精确匹配，选项只给全名）。 */
const RESOURCE_OPTIONS = [
  "event.events",
  "evidence.records",
  "decision.records",
  "decision.cases",
  "action.actions",
  "master.business_objects",
  "memory.memories",
  "ratelimit",
];

/** date 输入 → 接口时刻口径（since 当日零点 / until 当日末尾，闭区间含尾）。 */
export const sinceOfDate = (date: string): string => `${date}T00:00:00Z`;
export const untilOfDate = (date: string): string => `${date}T23:59:59Z`;

/** detail 结果摘要：reason 优先（GUARD_DENIED 拒绝理由），否则 k=v 紧凑串截断。 */
export function summarizeDetail(detail: Record<string, unknown> | undefined): string {
  if (detail == null || Object.keys(detail).length === 0) return "—";
  const reason = detail["reason"];
  if (typeof reason === "string" && reason) return reason;
  const text = Object.entries(detail)
    .map(([key, value]) => `${key}=${typeof value === "string" ? value : JSON.stringify(value)}`)
    .join(" ");
  return text.length > 60 ? `${text.slice(0, 60)}…` : text;
}

/** 长 ID mono 缩写（UUID 尾 8；title 携全量）。 */
function shortId(id: string): string {
  return id.length > 12 ? `…${id.slice(-8)}` : id;
}

export interface AuditTableProps {
  filters: AuditLogFilters;
  onFiltersChange: (filters: AuditLogFilters) => void;
}

/**
 * 日志 tab（视觉基线 `原型设计/pages/审计日志.html` 表格区 + 设计 13.6.3）：
 * 筛选工具栏（actor/resource_type/action/since/until，与接口参数一一对应）+
 * 已生效 chips（onRemove 按 key 单独清除——W3R 修复同款语义）+ 7 列表格 +
 * 游标分页（total 可选降级）；GUARD_DENIED 等拒绝行 -error 语义色整行高亮。
 */
export function AuditTable({ filters, onFiltersChange }: AuditTableProps) {
  // 游标导航栈：栈顶为当前页 cursor（首页 null）；onNext push / onPrev pop。
  const [cursorStack, setCursorStack] = useState<(string | null)[]>([null]);
  const pageIndex = cursorStack.length - 1;
  const cursor = cursorStack[pageIndex];
  const listQuery = useAuditLogs(filters, cursor);
  const items = listQuery.data?.items ?? [];
  const total = listQuery.data?.total;
  const nextCursor = listQuery.data?.next_cursor ?? null;

  const resetCursor = () => setCursorStack([null]);
  const patchFilters = (patch: Partial<AuditLogFilters>) => {
    onFiltersChange({ ...filters, ...patch });
    resetCursor();
  };
  const clearFilters = () => {
    onFiltersChange({});
    resetCursor();
  };
  /** W3R 语义：按 key 单独清除一个筛选，其余保留。 */
  const removeChip = (key: string) => {
    const next = { ...filters };
    delete next[key as keyof AuditLogFilters];
    onFiltersChange(next);
    resetCursor();
  };

  const chips: FilterChip[] = [];
  if (filters.actor_id) chips.push({ key: "actor_id", label: `操作人：${filters.actor_id}` });
  if (filters.resource_type)
    chips.push({ key: "resource_type", label: `资源：${filters.resource_type}` });
  if (filters.action) chips.push({ key: "action", label: `动作：${filters.action}` });
  if (filters.since)
    chips.push({ key: "since", label: `开始：${filters.since.split("T")[0]}` });
  if (filters.until)
    chips.push({ key: "until", label: `结束：${filters.until.split("T")[0]}` });

  const offset = pageIndex * AUDIT_PAGE_LIMIT;
  const start = items.length === 0 ? 0 : offset + 1;
  const end = offset + items.length;
  const navLocked = listQuery.isFetching;
  const navButtonClass =
    "h-8 px-2.5 border border-border rounded-lg text-muted-foreground hover:bg-muted disabled:opacity-50 disabled:pointer-events-none";

  return (
    <section className="flex flex-col gap-4 flex-1 min-h-0" data-dom-id="audit-logs-tab">
      {/* 筛选工具栏（13.7 #2）：五参数与接口一一对应 */}
      <div className="bg-card border border-border rounded-xl p-3">
        <div className="flex flex-wrap items-center gap-3" data-dom-id="audit-filter-bar">
          <input
            type="text"
            data-dom-id="audit-filter-actor"
            aria-label="操作人筛选"
            placeholder="按操作人筛选（如 adapter:erp）"
            value={filters.actor_id ?? ""}
            onChange={(e) => patchFilters({ actor_id: e.target.value.trim() || undefined })}
            className="h-9 px-3 text-xs bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring w-56"
          />
          <select
            data-dom-id="audit-filter-resource"
            aria-label="资源类型筛选"
            value={filters.resource_type ?? ""}
            onChange={(e) => patchFilters({ resource_type: e.target.value || undefined })}
            className="h-9 px-3 text-xs bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="">全部资源类型</option>
            {RESOURCE_OPTIONS.map((resource) => (
              <option key={resource} value={resource}>
                {resource}
              </option>
            ))}
          </select>
          <input
            type="text"
            data-dom-id="audit-filter-action"
            aria-label="动作筛选"
            placeholder="按动作筛选（如 GUARD_DENIED）"
            value={filters.action ?? ""}
            onChange={(e) => patchFilters({ action: e.target.value.trim().toUpperCase() || undefined })}
            className="h-9 px-3 text-xs bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring w-56"
          />
          <input
            type="date"
            data-dom-id="audit-filter-since"
            aria-label="开始日期筛选"
            value={filters.since ? filters.since.split("T")[0] : ""}
            onChange={(e) =>
              patchFilters({ since: e.target.value ? sinceOfDate(e.target.value) : undefined })
            }
            className="h-9 px-3 text-xs bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <input
            type="date"
            data-dom-id="audit-filter-until"
            aria-label="结束日期筛选"
            value={filters.until ? filters.until.split("T")[0] : ""}
            onChange={(e) =>
              patchFilters({ until: e.target.value ? untilOfDate(e.target.value) : undefined })
            }
            className="h-9 px-3 text-xs bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>
        {chips.length > 0 && (
          <div className="mt-3">
            <FilterChips chips={chips} onRemove={removeChip} onClearAll={clearFilters} />
          </div>
        )}
      </div>

      {listQuery.isError && listQuery.data == null ? (
        <div
          className="bg-card border border-border rounded-xl text-xs text-muted-foreground py-10 text-center"
          data-dom-id="audit-error"
        >
          审计日志暂不可用
        </div>
      ) : listQuery.data == null ? (
        <div className="bg-card border border-border rounded-xl p-4">
          <Skeleton active paragraph={{ rows: 6 }} />
        </div>
      ) : items.length === 0 ? (
        <div data-dom-id="audit-empty">
          <EmptyState
            title="未找到审计日志"
            description="当前筛选条件没有匹配结果，请调整筛选条件。"
            primaryAction={{ label: "清空筛选", onClick: clearFilters }}
          />
        </div>
      ) : (
        <section
          className="bg-card border border-border rounded-xl overflow-hidden flex-1 min-h-0 flex flex-col"
          data-dom-id="audit-content"
        >
          <div className="table-scroll flex-1 min-h-0" data-dom-id="audit-table">
            <table className="w-full text-xs min-w-[900px]">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wider text-muted-foreground border-b border-border bg-muted/50">
                  <th className="px-4 py-2.5 font-medium">时间</th>
                  <th className="px-4 py-2.5 font-medium">ID</th>
                  <th className="px-4 py-2.5 font-medium">操作者</th>
                  <th className="px-4 py-2.5 font-medium">操作</th>
                  <th className="px-4 py-2.5 font-medium">资源</th>
                  <th className="px-4 py-2.5 font-medium">结果摘要</th>
                  <th className="px-4 py-2.5 font-medium">级别</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {items.map((row) => (
                  <AuditRow key={row.audit_id} row={row} />
                ))}
              </tbody>
            </table>
          </div>
          {/* 游标分页 + 总数千分位（total 可选降级仅导航） */}
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
          ) : (
            <div
              className="px-4 py-3 border-t border-border flex items-center justify-end gap-1 shrink-0"
              data-dom-id="audit-pagination-fallback"
            >
              <button
                type="button"
                aria-label="上一页"
                data-dom-id="pagination-prev"
                onClick={() => setCursorStack((s) => (s.length > 1 ? s.slice(0, -1) : s))}
                disabled={pageIndex === 0 || navLocked}
                className={navButtonClass}
              >
                <ChevronLeft className="w-4 h-4" aria-hidden="true" />
              </button>
              <button
                type="button"
                aria-label="下一页"
                data-dom-id="pagination-next"
                onClick={() => {
                  if (nextCursor) setCursorStack((s) => [...s, nextCursor]);
                }}
                disabled={nextCursor == null || navLocked}
                className={navButtonClass}
              >
                <ChevronRight className="w-4 h-4" aria-hidden="true" />
              </button>
            </div>
          )}
        </section>
      )}
    </section>
  );
}

function AuditRow({ row }: { row: AuditLogItem }) {
  const severity = severityOfAction(row.action);
  const actorTone = ACTOR_TYPE_TONES[row.actor_type] ?? "muted";
  return (
    <tr
      data-dom-id={`audit-row-${row.audit_id}`}
      title={row.action === "GUARD_DENIED" ? "GUARD_DENIED：越权操作已被拦截" : undefined}
      className={
        severity === "error"
          ? "audit-row-error bg-state-error-bg/60 hover:bg-state-error-bg transition-colors"
          : "hover:bg-muted/50 transition-colors"
      }
    >
      <td className="px-4 py-2.5 font-mono text-muted-foreground whitespace-nowrap">
        {fmtDateTime(row.occurred_at)}
      </td>
      <td className="px-4 py-2.5 font-mono text-muted-foreground">{row.audit_id}</td>
      <td className="px-4 py-2.5 whitespace-nowrap">
        <div className="flex items-center gap-1.5">
          <StatusPill tone={actorTone} label={ACTOR_TYPE_LABELS[row.actor_type] ?? row.actor_type} size="sm" />
          <span className="font-mono text-[11px] text-muted-foreground" title={row.actor_id}>
            {shortActorId(row.actor_id)}
          </span>
        </div>
      </td>
      <td className="px-4 py-2.5">
        <div className="font-mono text-[11px] text-foreground">{row.action}</div>
        <div className="text-[11px] text-muted-foreground">{deriveActionLabel(row.action)}</div>
      </td>
      <td className="px-4 py-2.5">
        <div className="text-foreground whitespace-nowrap">
          {resolveResourceType(row.resource_type, row.action)}
        </div>
        <div className="font-mono text-[11px] text-muted-foreground" title={row.resource_id ?? undefined}>
          {row.resource_id ? shortId(row.resource_id) : "—"}
        </div>
      </td>
      <td className="px-4 py-2.5 max-w-[260px]">
        <div className="truncate text-muted-foreground" title={summarizeDetail(row.detail)}>
          {summarizeDetail(row.detail)}
        </div>
      </td>
      <td className="px-4 py-2.5 whitespace-nowrap">
        <StatusPill tone={severity} label={SEVERITY_LABELS[severity]} size="sm" />
      </td>
    </tr>
  );
}
