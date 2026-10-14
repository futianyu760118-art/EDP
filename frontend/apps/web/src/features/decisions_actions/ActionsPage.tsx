import { Skeleton } from "antd";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { EmptyState, StatusPill } from "@edp/shared";
import { fmt, fmtDateTime } from "../../lib/labels";
import { ACTION_STATUS_LABELS, actionStatusOf } from "../cases/labels";
import { ACTIONS_PAGE_LIMIT, type ActionStatus } from "./api";
import { ActionDetailDrawer } from "./ActionDetailDrawer";
import { useActionsList } from "./hooks";

/** 9 态下拉序：主线 + 分支（展示名对齐 ACTION_STATUS_LABELS）。 */
const STATUS_OPTIONS: { value: ActionStatus; label: string }[] = (
  [
    "PROPOSED",
    "ASSIGNED",
    "ACCEPTED",
    "APPROVED",
    "EXECUTING",
    "COMPLETED",
    "VERIFIED",
    "REJECTED",
    "CANCELLED",
  ] as ActionStatus[]
).map((value) => ({ value, label: ACTION_STATUS_LABELS[value].label }));

/**
 * 行动页（EDP-404，设计 13.6.5）：列表（status 下拉 + owner 输入筛选 + 游标分页 +
 * 总数千分位——W3-32 顺带，用既有 fmt 工具）+ 行点击 → 420px 详情抽屉（9 态状态轴 +
 * allowed_to 驱动按钮，见 ActionDetailDrawer）；`/actions?case_id=` 支持初始筛选
 * （T9 案例详情行动卡跳转落地）。
 */
export function ActionsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialCaseId = searchParams.get("case_id") ?? "";
  const [status, setStatus] = useState<"" | ActionStatus>("");
  const [owner, setOwner] = useState("");
  const [caseId, setCaseId] = useState(initialCaseId);
  // 游标导航栈：栈顶为当前页 cursor（首页 null）；onNext push / onPrev pop。
  const [cursorStack, setCursorStack] = useState<(string | null)[]>([null]);
  const [drawerId, setDrawerId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const pageIndex = cursorStack.length - 1;
  const cursor = cursorStack[pageIndex];
  const listQuery = useActionsList(
    { status: status || undefined, owner: owner.trim() || undefined, caseId: caseId || undefined },
    cursor,
  );
  const items = listQuery.data?.items ?? [];
  const total = listQuery.data?.total;
  const nextCursor = listQuery.data?.next_cursor ?? null;

  const resetCursor = () => setCursorStack([null]);
  const clearFilters = () => {
    setStatus("");
    setOwner("");
    setCaseId("");
    resetCursor();
    if (searchParams.get("case_id") != null) setSearchParams({}, { replace: true });
  };

  const openDrawer = (actionId: string) => {
    setDrawerId(actionId);
    setDrawerOpen(true);
  };

  const offset = pageIndex * ACTIONS_PAGE_LIMIT;
  const start = items.length === 0 ? 0 : offset + 1;
  const end = offset + items.length;
  const navLocked = listQuery.isFetching;
  const navButtonClass =
    "h-8 px-2.5 border border-border rounded-lg text-muted-foreground hover:bg-muted disabled:opacity-50 disabled:pointer-events-none";

  const hasFilter = status !== "" || owner.trim() !== "" || caseId !== "";

  return (
    <div className="flex flex-col gap-4 h-full" data-dom-id="actions-page">
      <section className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <h1 className="text-xl font-semibold text-foreground">行动</h1>
      </section>

      {/* 工具栏（13.7 #2）：status 下拉 + owner 输入 + case_id 只读清除 */}
      <section className="bg-card border border-border rounded-xl p-3">
        <div className="flex flex-col lg:flex-row lg:items-center gap-3">
          <select
            data-dom-id="actions-filter-status"
            aria-label="状态筛选"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as "" | ActionStatus);
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
          <input
            data-dom-id="actions-filter-owner"
            aria-label="负责人筛选"
            type="text"
            value={owner}
            onChange={(e) => {
              setOwner(e.target.value);
              resetCursor();
            }}
            placeholder="按负责人筛选（如 user:purchasing_li）"
            className="h-9 px-3 text-xs bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring w-64"
          />
          {caseId !== "" && (
            <span className="inline-flex items-center gap-1.5 h-9 px-3 rounded-lg bg-muted text-[11px] text-muted-foreground">
              案例：<span className="font-mono">{caseId.slice(-8)}</span>
              <button
                type="button"
                aria-label="移除案例筛选"
                data-dom-id="actions-filter-case-remove"
                onClick={() => {
                  setCaseId("");
                  resetCursor();
                  setSearchParams({}, { replace: true });
                }}
                className="text-foreground hover:text-primary"
              >
                ×
              </button>
            </span>
          )}
          {hasFilter && (
            <button
              type="button"
              data-dom-id="actions-filter-clear"
              onClick={clearFilters}
              className="h-9 px-3 text-xs text-muted-foreground hover:text-primary"
            >
              清空筛选
            </button>
          )}
        </div>
      </section>

      {listQuery.isError && listQuery.data == null ? (
        <div
          className="bg-card border border-border rounded-xl text-xs text-muted-foreground py-10 text-center"
          data-dom-id="actions-error"
        >
          行动列表暂不可用
        </div>
      ) : listQuery.data == null ? (
        <div className="bg-card border border-border rounded-xl p-4">
          <Skeleton active paragraph={{ rows: 6 }} />
        </div>
      ) : items.length === 0 ? (
        <div data-dom-id="actions-empty">
          <EmptyState
            title="未找到行动"
            description="当前筛选条件没有匹配结果，请调整状态或负责人筛选。"
            primaryAction={{ label: "清空筛选", onClick: clearFilters }}
          />
        </div>
      ) : (
        <section
          className="bg-card border border-border rounded-xl overflow-hidden flex-1 min-h-0 flex flex-col"
          data-dom-id="actions-content"
        >
            <div className="table-scroll flex-1 min-h-0" data-dom-id="actions-table">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wider text-muted-foreground border-b border-border">
                  <th className="px-4 py-2.5 font-medium">标题</th>
                  <th className="px-4 py-2.5 font-medium">状态</th>
                  <th className="px-4 py-2.5 font-medium">负责人</th>
                  <th className="px-4 py-2.5 font-medium">截止日期</th>
                  <th className="px-4 py-2.5 font-medium text-right">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {items.map((row) => {
                  const statusDisplay = actionStatusOf(row.status);
                  return (
                    <tr
                      key={row.action_id}
                      data-dom-id={`actions-row-${row.action_id}`}
                      onClick={() => openDrawer(row.action_id)}
                      className="hover:bg-muted/50 transition-colors cursor-pointer"
                    >
                      <td className="px-4 py-2.5 max-w-[320px]">
                        <div className="truncate text-foreground" title={row.title}>
                          {row.title}
                        </div>
                      </td>
                      <td className="px-4 py-2.5">
                        <StatusPill tone={statusDisplay.tone} label={statusDisplay.label} size="sm" />
                      </td>
                      <td className="px-4 py-2.5 text-muted-foreground whitespace-nowrap">{row.owner ?? "—"}</td>
                      <td className="px-4 py-2.5 text-muted-foreground whitespace-nowrap">
                        {row.due_date != null ? fmtDateTime(row.due_date) : "—"}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <button
                          type="button"
                          data-dom-id={`actions-detail-${row.action_id}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            openDrawer(row.action_id);
                          }}
                          className="h-7 px-2.5 border border-border rounded-lg text-primary hover:bg-muted text-[11px] font-medium"
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
          {/* 游标分页 + 总数千分位（W3-32：既有 fmt 工具；total 缺省降级仅导航） */}
          <div
            className="px-4 py-3 border-t border-border flex items-center justify-between"
            data-dom-id="actions-pagination"
          >
            {total != null ? (
              <div className="text-xs text-muted-foreground" data-dom-id="pagination-range">
                显示 {fmt(start)}–{fmt(end)} 条，共 {fmt(total)} 条
              </div>
            ) : (
              <div className="text-xs text-muted-foreground">第 {pageIndex + 1} 页</div>
            )}
            <div className="flex items-center gap-1">
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
              <span
                className="h-8 px-3 bg-primary text-primary-foreground rounded-lg text-xs font-medium grid place-items-center"
                aria-current="page"
                data-dom-id="pagination-page"
              >
                {pageIndex + 1}
              </span>
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
          </div>
        </section>
      )}

      <ActionDetailDrawer
        actionId={drawerId}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  );
}
