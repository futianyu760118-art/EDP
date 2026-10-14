import { Skeleton } from "antd";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  CursorPagination,
  EmptyState,
  FilterChips,
  RISK_LEVEL_LABELS,
  StatusPill,
  type FilterChip,
} from "@edp/shared";
import { fmtDateTime } from "../../lib/labels";
import {
  CASES_PAGE_LIMIT,
  type CaseListItem,
  type CaseRiskLevel,
  type CaseStatus,
} from "./api";
import { useCasesList } from "./hooks";
import { caseStatusOf, riskLabelOf } from "./labels";

const STATUS_OPTIONS: { value: CaseStatus; label: string }[] = [
  { value: "OPEN", label: "待决" },
  { value: "DECIDED", label: "已决策" },
  { value: "CANCELLED", label: "已取消" },
];

const RISK_OPTIONS: { value: CaseRiskLevel; label: string }[] = (["P0", "P1", "P2", "P3"] as const).map(
  (value) => ({ value, label: RISK_LEVEL_LABELS[value].label }),
);

/**
 * 闭环案例列表页（EDP-403，设计 13.6.5：无高保真稿，复用 13.7 模式）：
 * 筛选（状态 OPEN/DECIDED/CANCELLED + 风险等级 P0~P3 chips 工具栏）+ 表格
 * （case_no mono/问题截断/风险 pill/状态 pill/创建时间/操作「查看」）+ 游标分页 + 空态三件套。
 */
export function CasesPage() {
  const [status, setStatus] = useState<"" | CaseStatus>("");
  const [risk, setRisk] = useState<"" | CaseRiskLevel>("");
  // 游标导航栈：栈顶为当前页 cursor（首页 null）；onNext push / onPrev pop。
  const [cursorStack, setCursorStack] = useState<(string | null)[]>([null]);
  const navigate = useNavigate();
  const pageIndex = cursorStack.length - 1;
  const cursor = cursorStack[pageIndex];

  const listQuery = useCasesList(
    { status: status || undefined, riskLevel: risk || undefined },
    cursor,
  );
  const items: CaseListItem[] = listQuery.data?.items ?? [];
  const total = listQuery.data?.total;
  const nextCursor = listQuery.data?.next_cursor ?? null;

  const resetCursor = () => setCursorStack([null]);
  const clearFilters = () => {
    setStatus("");
    setRisk("");
    resetCursor();
  };
  const removeChip = (key: string) => {
    if (key === "status") setStatus("");
    else if (key === "risk") setRisk("");
    resetCursor();
  };

  const chips: FilterChip[] = [];
  if (status) chips.push({ key: "status", label: `状态：${caseStatusOf(status).label}` });
  if (risk) chips.push({ key: "risk", label: `风险：${RISK_LEVEL_LABELS[risk].label}` });

  const offset = pageIndex * CASES_PAGE_LIMIT;
  const start = items.length === 0 ? 0 : offset + 1;
  const end = offset + items.length;
  // 翻页在途禁用导航（keepPreviousData 下旧页仍可见，防竞态双击重复 push 游标）。
  const navLocked = listQuery.isFetching;

  const navButtonClass =
    "h-8 px-2.5 border border-border rounded-lg text-muted-foreground hover:bg-muted disabled:opacity-50 disabled:pointer-events-none";

  return (
    <div className="flex flex-col gap-4 h-full" data-dom-id="cases-page">
      <section className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <h1 className="text-xl font-semibold text-foreground">闭环案例</h1>
      </section>

      {/* 工具栏（13.7 #2：筛选控件 + 已生效 chips） */}
      <section className="bg-card border border-border rounded-xl p-3">
        <div className="flex flex-col lg:flex-row lg:items-center gap-3">
          <select
            data-dom-id="cases-filter-status"
            aria-label="状态筛选"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as "" | CaseStatus);
              resetCursor();
            }}
            className="h-9 px-3 text-xs bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="">全部状态</option>
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <select
            data-dom-id="cases-filter-risk"
            aria-label="风险等级筛选"
            value={risk}
            onChange={(e) => {
              setRisk(e.target.value as "" | CaseRiskLevel);
              resetCursor();
            }}
            className="h-9 px-3 text-xs bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="">全部风险等级</option>
            {RISK_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        {chips.length > 0 && (
          <div className="mt-3">
            <FilterChips chips={chips} onRemove={removeChip} onClearAll={clearFilters} />
          </div>
        )}
      </section>

      {listQuery.isError && listQuery.data == null ? (
        <div
          className="bg-card border border-border rounded-xl text-xs text-muted-foreground py-10 text-center"
          data-dom-id="cases-error"
        >
          案例列表暂不可用
        </div>
      ) : listQuery.data == null ? (
        <div className="bg-card border border-border rounded-xl p-4">
          <Skeleton active paragraph={{ rows: 6 }} />
        </div>
      ) : items.length === 0 ? (
        <div data-dom-id="cases-empty">
          <EmptyState
            title="未找到案例"
            description="当前筛选条件没有匹配结果，请调整状态或风险等级筛选。"
            primaryAction={{ label: "清空筛选", onClick: clearFilters }}
          />
        </div>
      ) : (
        <section
          className="bg-card border border-border rounded-xl overflow-hidden flex-1 min-h-0 flex flex-col"
          data-dom-id="cases-content"
        >
            <div className="table-scroll flex-1 min-h-0" data-dom-id="cases-table">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wider text-muted-foreground border-b border-border">
                  <th className="px-4 py-2.5 font-medium">案例编号</th>
                  <th className="px-4 py-2.5 font-medium">问题</th>
                  <th className="px-4 py-2.5 font-medium">风险</th>
                  <th className="px-4 py-2.5 font-medium">状态</th>
                  <th className="px-4 py-2.5 font-medium">创建时间</th>
                  <th className="px-4 py-2.5 font-medium text-right">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {items.map((row) => {
                  const riskDisplay = riskLabelOf(row.risk_level);
                  const statusDisplay = caseStatusOf(row.status);
                  return (
                    <tr key={row.case_id} data-dom-id={`cases-row-${row.case_id}`} className="hover:bg-muted/50 transition-colors">
                      <td className="px-4 py-2.5 font-mono text-foreground whitespace-nowrap">
                        {row.case_no ?? "—"}
                      </td>
                      <td className="px-4 py-2.5 max-w-[320px]">
                        <div className="truncate text-foreground" title={row.question}>
                          {row.question}
                        </div>
                      </td>
                      <td className="px-4 py-2.5">
                        <StatusPill tone={riskDisplay.tone} label={riskDisplay.label} size="sm" />
                      </td>
                      <td className="px-4 py-2.5">
                        <StatusPill tone={statusDisplay.tone} label={statusDisplay.label} size="sm" />
                      </td>
                      <td className="px-4 py-2.5 text-muted-foreground whitespace-nowrap">
                        {fmtDateTime(row.created_at)}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <button
                          type="button"
                          data-dom-id={`cases-view-${row.case_id}`}
                          onClick={() => navigate(`/cases/${row.case_id}`)}
                          className="h-7 px-2.5 border border-border rounded-lg text-primary hover:bg-muted text-[11px] font-medium"
                        >
                          查看
                        </button>
                      </td>
                    </tr>
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
          ) : (
            /* total 缺失（真实契约 Page envelope 可选）降级：隐藏计数文案，保留游标导航 */
            <div
              className="px-4 py-3 border-t border-border flex items-center justify-end gap-1 shrink-0"
              data-dom-id="cases-pagination-fallback"
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
    </div>
  );
}
