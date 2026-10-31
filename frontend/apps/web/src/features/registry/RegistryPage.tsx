import { Skeleton } from "antd";
import { LayoutGrid, Plus, Search, Table as TableIcon } from "lucide-react";
import { useState } from "react";
import {
  CursorPagination,
  EmptyState,
  FilterChips,
  MonoId,
  StatusPill,
  type FilterChip,
} from "@edp/shared";
import { relTime } from "../../lib/labels";
import type { ObjectResponse } from "../../mocks/types";
import { OBJECTS_PAGE_LIMIT } from "./api";
import {
  DERIVED_STATUSES,
  DERIVED_TONE,
  deriveStatus,
  DOMAIN_OPTIONS,
  domainLabel,
  lagHours,
} from "./derive";
import { useDqIndex, useObjects, useRiskIndex } from "./hooks";
import { ObjectCard } from "./ObjectCard";
import { CreateObjectModal } from "./CreateObjectModal";
import { DetailDrawer } from "./DetailDrawer";

const TABLE_COLUMNS = ["对象", "类型", "名称", "域", "来源", "状态", "Rev", "更新时间", "操作"];

/**
 * 业务对象页列表主体（EDP-203，视觉基线：`原型设计/pages/业务对象.html` 工具栏/卡片/
 * 表格 + `业务对象 - 空态.html` 空态）。筛选分工：域 → 后端 owner_domain 参数；
 * 状态/搜索 → 当前结果集内前端过滤（MVP：派生状态非落库字段、后端无名称搜索，
 * 全量服务端过滤待 T18 契约扩展）。
 */
export function RegistryPage() {
  const [search, setSearch] = useState("");
  const [domain, setDomain] = useState("");
  const [status, setStatus] = useState("");
  const [view, setView] = useState<"cards" | "table">("cards");
  const [createOpen, setCreateOpen] = useState(false);
  const [detailObj, setDetailObj] = useState<ObjectResponse | null>(null);
  // 游标导航栈：栈顶为当前页 cursor（首页 null）；onNext push / onPrev pop。
  const [cursorStack, setCursorStack] = useState<(string | null)[]>([null]);
  const pageIndex = cursorStack.length - 1;
  const cursor = cursorStack[pageIndex];

  const objectsQuery = useObjects({ ownerDomain: domain }, cursor);
  const riskIndex = useRiskIndex();
  const dqIndex = useDqIndex();
  const riskMap = riskIndex.data;
  const dqSet = dqIndex.data;

  const query = search.trim();
  const items = objectsQuery.data?.items ?? [];

  const statusOf = (o: ObjectResponse) =>
    deriveStatus({
      riskLevel: riskMap?.get(o.object_id) ?? null,
      hasDqException: dqSet?.has(o.object_id) ?? false,
      syncLagHours: lagHours(o.updated_at),
    });

  // 前端过滤当前结果集：搜索 = source_id 精确或 attributes.name 包含；状态 = 六派生态。
  const filtered = items.filter((o) => {
    if (status && statusOf(o) !== status) return false;
    if (query) {
      const name = typeof o.attributes?.name === "string" ? o.attributes.name : "";
      if (o.source_id !== query && !name.includes(query)) return false;
    }
    return true;
  });

  const chips: FilterChip[] = [];
  if (query) chips.push({ key: "search", label: `搜索：${query}` });
  if (domain) chips.push({ key: "domain", label: `域：${domainLabel(domain)}` });
  if (status) chips.push({ key: "status", label: `状态：${status}` });

  const resetCursor = () => setCursorStack([null]);
  const clearFilters = () => {
    setSearch("");
    setDomain("");
    setStatus("");
    resetCursor();
  };

  const nextCursor = objectsQuery.data?.next_cursor ?? null;
  // 分页区间取舍：无前端过滤时 total 用响应 total（mock 扩展）；前端过滤仅作用于
  // 当前页，区间/总数按过滤后条数展示（服务端无对应参数，见页头注释）。
  const localFilterActive = status !== "" || query !== "";
  const offset = pageIndex * OBJECTS_PAGE_LIMIT;
  const start = filtered.length === 0 ? 0 : offset + 1;
  const end = offset + filtered.length;
  const total = localFilterActive ? filtered.length : objectsQuery.data?.total ?? filtered.length;

  const segmentClass = (active: boolean) =>
    `h-9 px-3 text-xs font-medium flex items-center gap-1.5 ${
      active ? "bg-muted text-foreground" : "bg-card text-muted-foreground hover:bg-muted"
    }`;

  return (
    <div       className="flex flex-col gap-4 h-full"
      data-dom-id="objects-page">
      {/* 页头（原型`业务对象.html`行 331~346）：注册对象入口（T8 接新建弹窗） */}
      <section className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <h1 className="text-xl font-semibold text-foreground">业务对象</h1>
        <div className="flex items-center gap-2">
          <button
            type="button"
            data-dom-id="obj-register"
            onClick={() => setCreateOpen(true)}
            className="h-9 px-4 bg-primary text-primary-foreground rounded-lg text-xs font-medium hover:opacity-90 flex items-center gap-1.5"
          >
            <Plus className="w-4 h-4" aria-hidden="true" />
            注册对象
          </button>
        </div>
      </section>
      <section className="bg-card border border-border rounded-xl p-3">
        <div className="flex flex-col lg:flex-row lg:items-center gap-3">
          <div className="relative flex-1">
            <Search
              className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground"
              aria-hidden="true"
            />
            <input
              type="text"
              data-dom-id="objects-search"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                resetCursor();
              }}
              placeholder="搜索对象 ID、名称、来源…"
              className="h-9 w-full pl-9 pr-3 text-xs bg-muted border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
            />
          </div>
          <div className="flex items-center gap-2">
            <select
              data-dom-id="objects-domain"
              aria-label="域筛选"
              value={domain}
              onChange={(e) => {
                setDomain(e.target.value);
                resetCursor();
              }}
              className="h-9 px-3 text-xs bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
            >
              <option value="">全部域</option>
              {DOMAIN_OPTIONS.map((d) => (
                <option key={d.value} value={d.value}>
                  {d.label}
                </option>
              ))}
            </select>
            <select
              data-dom-id="objects-status"
              aria-label="状态筛选"
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                resetCursor();
              }}
              className="h-9 px-3 text-xs bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
            >
              <option value="">全部状态</option>
              {DERIVED_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <div className="flex items-center border border-border rounded-lg overflow-hidden">
              <button
                type="button"
                data-dom-id="view-cards"
                aria-pressed={view === "cards"}
                onClick={() => setView("cards")}
                className={segmentClass(view === "cards")}
              >
                <LayoutGrid className="w-4 h-4" aria-hidden="true" />
                卡片
              </button>
              <button
                type="button"
                data-dom-id="view-table"
                aria-pressed={view === "table"}
                onClick={() => setView("table")}
                className={segmentClass(view === "table")}
              >
                <TableIcon className="w-4 h-4" aria-hidden="true" />
                表格
              </button>
            </div>
          </div>
        </div>
        {chips.length > 0 && (
          <div className="mt-3">
            <FilterChips
              chips={chips}
              onRemove={(key) => {
                if (key === "search") setSearch("");
                if (key === "domain") {
                  setDomain("");
                  resetCursor();
                }
                if (key === "status") setStatus("");
              }}
              onClearAll={clearFilters}
            />
          </div>
        )}
      </section>

      {objectsQuery.isError && objectsQuery.data == null ? (
        <div
          className="bg-card border border-border rounded-xl text-xs text-muted-foreground py-10 text-center"
          data-dom-id="objects-error"
        >
          业务对象列表暂不可用
        </div>
      ) : objectsQuery.data == null ? (
        <div className="bg-card border border-border rounded-xl p-4">
          <Skeleton active paragraph={{ rows: 6 }} />
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          title="未找到业务对象"
          description="当前搜索条件没有匹配结果，请调整筛选条件或新建对象。"
          primaryAction={{ label: "新建对象", onClick: () => setCreateOpen(true) }}
          secondaryAction={{ label: "清空筛选", onClick: clearFilters }}
        />
      ) : (
        <section
          className="bg-card border border-border rounded-xl overflow-hidden flex-1 min-h-0 flex flex-col"
          data-dom-id="objects-content"
        >
          {view === "cards" ? (
            <div
              className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 p-4 flex-1 min-h-0 overflow-auto"
              data-dom-id="objects-grid"
            >
              {filtered.map((o) => (
                <ObjectCard
                  key={o.object_id}
                  obj={o}
                  riskLevel={riskMap?.get(o.object_id)}
                  hasDq={dqSet?.has(o.object_id)}
                  onOpenDetail={() => setDetailObj(o)}
                />
              ))}
            </div>
          ) : (
            <div className="table-scroll flex-1 min-h-0" data-dom-id="objects-table">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-muted-foreground border-b border-border">
                    {TABLE_COLUMNS.map((h) => (
                      <th key={h} className="px-4 py-3 font-medium whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((o) => {
                    const s = statusOf(o);
                    return (
                      <tr
                        key={o.object_id}
                        data-dom-id="object-row"
                        className="border-b border-border last:border-b-0"
                      >
                        <td className="px-4 py-3">
                          <MonoId id={o.source_id} copyable={false} length={o.source_id.length} />
                        </td>
                        <td className="px-4 py-3">{o.object_type}</td>
                        <td className="px-4 py-3">
                          {typeof o.attributes?.name === "string" ? o.attributes.name : "—"}
                        </td>
                        <td className="px-4 py-3">{domainLabel(o.owner_domain)}</td>
                        <td className="px-4 py-3">{o.source_system.toUpperCase()}</td>
                        <td className="px-4 py-3">
                          <StatusPill tone={DERIVED_TONE[s]} label={s} size="sm" />
                        </td>
                        <td className="px-4 py-3">{o.revision}</td>
                        <td className="px-4 py-3">{relTime(o.updated_at)}</td>
                        <td className="px-4 py-3">
                          <button
                            type="button"
                            data-dom-id="object-row-detail"
                            onClick={() => setDetailObj(o)}
                            className="text-primary hover:underline"
                          >
                            查看详情
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <CursorPagination
            start={start}
            end={end}
            total={total}
            page={pageIndex + 1}
            hasPrev={pageIndex > 0}
            hasNext={nextCursor != null}
            onPrev={() => setCursorStack((s) => (s.length > 1 ? s.slice(0, -1) : s))}
            onNext={() => {
              if (nextCursor) setCursorStack((s) => [...s, nextCursor]);
            }}
          />
        </section>
      )}

      <CreateObjectModal open={createOpen} onClose={() => setCreateOpen(false)} />
      {detailObj != null && (
        <DetailDrawer obj={detailObj} status={statusOf(detailObj)} onClose={() => setDetailObj(null)} />
      )}
    </div>
  );
}
