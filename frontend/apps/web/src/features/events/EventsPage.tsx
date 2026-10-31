import { message, Skeleton } from "antd";
import { ChevronLeft, ChevronRight, Plus, RotateCcw } from "lucide-react";
import { useMemo, useState } from "react";
import { CursorPagination, EmptyState, FilterChips, type FilterChip } from "@edp/shared";
import { EVENT_TYPE_LABELS, eventTypeDisplay } from "../../lib/labels";
import type { EventResponse } from "../../mocks/types";
import { EVENTS_PAGE_LIMIT } from "./api";
import { EventDetailDrawer } from "./EventDetailDrawer";
import { EventTable } from "./EventTable";
import { useEventHealth, useEvents } from "./hooks";
import { KpiBand } from "./KpiBand";
import { ReplayWizard } from "./ReplayWizard";

const TIME_RANGES = [
  { value: "24h", label: "24H", hours: 24 },
  { value: "7d", label: "7D", hours: 24 * 7 },
  { value: "30d", label: "30D", hours: 24 * 30 },
] as const;

type TimeRange = (typeof TIME_RANGES)[number]["value"];

function sinceOf(range: TimeRange): string {
  const hours = TIME_RANGES.find((r) => r.value === range)!.hours;
  return new Date(Date.now() - hours * 3_600_000).toISOString();
}

/**
 * 事件流页（EDP-301，视觉基线：`原型设计/pages/事件流.html` + 设计 13.6.2）：
 * 页头（新建订阅占位 / 回放事件入口）+ KPI 带 + 工具栏（类型下拉/时间范围/筛选 chips）
 * + 9 列表格 + 游标分页 + 空态；行「详情」打开事件详情抽屉，页头/空态入口打开回放三步向导。
 */
export function EventsPage() {
  const [eventType, setEventType] = useState("");
  const [range, setRange] = useState<TimeRange>("24h");
  // 游标导航栈：栈顶为当前页 cursor（首页 null）；onNext push / onPrev pop。
  const [cursorStack, setCursorStack] = useState<(string | null)[]>([null]);
  const [detailEvent, setDetailEvent] = useState<EventResponse | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [wizardOpen, setWizardOpen] = useState(false);
  const pageIndex = cursorStack.length - 1;
  const cursor = cursorStack[pageIndex];

  const since = useMemo(() => sinceOf(range), [range]);
  const eventsQuery = useEvents({ eventType: eventType || undefined, since }, cursor);
  const healthQuery = useEventHealth();

  const items = eventsQuery.data?.items ?? [];
  const total = eventsQuery.data?.total;
  const nextCursor = eventsQuery.data?.next_cursor ?? null;

  const resetCursor = () => setCursorStack([null]);
  const clearFilters = () => {
    setEventType("");
    resetCursor();
  };

  const chips: FilterChip[] = [];
  if (eventType) chips.push({ key: "type", label: `类型：${eventTypeDisplay(eventType).label}` });

  const offset = pageIndex * EVENTS_PAGE_LIMIT;
  const start = items.length === 0 ? 0 : offset + 1;
  const end = offset + items.length;
  // 翻页在途禁用导航（keepPreviousData 下旧页仍可见，防竞态双击重复 push 游标）。
  const navLocked = eventsQuery.isFetching;

  const segmentClass = (active: boolean) =>
    `h-9 px-3 text-xs font-medium ${
      active ? "bg-muted text-foreground" : "bg-card text-muted-foreground hover:bg-muted"
    }`;

  const navButtonClass =
    "h-8 px-2.5 border border-border rounded-lg text-muted-foreground hover:bg-muted disabled:opacity-50 disabled:pointer-events-none";

  return (
    <div className="flex flex-col gap-4 h-full" data-dom-id="events-page">
      {/* 页头（原型行 336~350）：新建订阅占位；回放事件主按钮打开三步向导 */}
      <section className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <h1 className="text-xl font-semibold text-foreground">事件流</h1>
        <div className="flex items-center gap-2">
          <button
            type="button"
            data-dom-id="events-subscribe-btn"
            onClick={() => message.info("订阅功能后续交付")}
            className="h-9 px-3 border border-border bg-card text-foreground rounded-lg text-xs font-medium hover:bg-muted flex items-center gap-1.5"
          >
            <Plus className="w-4 h-4" aria-hidden="true" />
            新建订阅
          </button>
          <button
            type="button"
            data-dom-id="events-replay-btn"
            onClick={() => setWizardOpen(true)}
            className="h-9 px-4 bg-primary text-primary-foreground rounded-lg text-xs font-medium hover:opacity-90 flex items-center gap-1.5"
          >
            <RotateCcw className="w-4 h-4" aria-hidden="true" />
            回放事件
          </button>
        </div>
      </section>

      <KpiBand ops={healthQuery.data} />

      {/* 工具栏（原型行 389~418；搜索框待 q 契约参数，本轮不设） */}
      <section className="bg-card border border-border rounded-xl p-3">
        <div className="flex flex-col lg:flex-row lg:items-center gap-3">
          <select
            data-dom-id="events-type"
            aria-label="事件类型筛选"
            value={eventType}
            onChange={(e) => {
              setEventType(e.target.value);
              resetCursor();
            }}
            className="h-9 px-3 text-xs bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="">全部事件类型</option>
            {Object.entries(EVENT_TYPE_LABELS).map(([value, display]) => (
              <option key={value} value={value}>
                {display.label}
              </option>
            ))}
          </select>
          <div
            className="flex items-center border border-border rounded-lg overflow-hidden"
            role="group"
            aria-label="时间范围"
            data-dom-id="events-range"
          >
            {TIME_RANGES.map((r) => (
              <button
                key={r.value}
                type="button"
                data-dom-id={`events-range-${r.value}`}
                aria-pressed={range === r.value}
                onClick={() => {
                  setRange(r.value);
                  resetCursor();
                }}
                className={segmentClass(range === r.value)}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>
        {chips.length > 0 && (
          <div className="mt-3">
            <FilterChips chips={chips} onRemove={() => clearFilters()} onClearAll={clearFilters} />
          </div>
        )}
      </section>

      {eventsQuery.isError && eventsQuery.data == null ? (
        <div
          className="bg-card border border-border rounded-xl text-xs text-muted-foreground py-10 text-center"
          data-dom-id="events-error"
        >
          事件列表暂不可用
        </div>
      ) : eventsQuery.data == null ? (
        <div className="bg-card border border-border rounded-xl p-4">
          <Skeleton active paragraph={{ rows: 6 }} />
        </div>
      ) : items.length === 0 ? (
        <div data-dom-id="events-empty">
          <EmptyState
            title="未找到事件"
            description="当前筛选条件没有匹配结果，请调整筛选条件或回放历史事件。"
            primaryAction={{ label: "清空筛选", onClick: clearFilters }}
            secondaryAction={{
              label: "回放事件",
              onClick: () => setWizardOpen(true),
            }}
          />
        </div>
      ) : (
        <section
          className="bg-card border border-border rounded-xl overflow-hidden flex-1 min-h-0 flex flex-col"
          data-dom-id="events-content"
        >
          <EventTable
            events={items}
            onDetail={(event) => {
              setDetailEvent(event);
              setDrawerOpen(true);
            }}
          />
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
            /* total 缺失（真实契约未填充）降级：隐藏计数文案，保留游标导航 */
            <div
              className="px-4 py-3 border-t border-border flex items-center justify-end gap-1 shrink-0"
              data-dom-id="events-pagination-fallback"
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

      <EventDetailDrawer
        event={detailEvent}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />
      <ReplayWizard open={wizardOpen} events={items} onClose={() => setWizardOpen(false)} />
    </div>
  );
}
