import { Skeleton } from "antd";
import { ArrowRight, Plus } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  CursorPagination,
  EmptyState,
  FilterChips,
  StatusPill,
  canSeeGroup,
  PLAN_LABELS,
  TENANT_STATUS_LABELS,
  type FilterChip,
} from "@edp/shared";
import { useSessionStore } from "../auth/session-store";
import { fmt, fmtCompact, fmtDateTime, planLabel } from "../../lib/labels";
import { TenantSwitchModal } from "../../shell/TenantSwitchModal";
import type { TenantListItem, TenantPlan, TenantStatus } from "./api";
import { CreateTenantModal } from "./CreateTenantModal";
import { TENANTS_PAGE_LIMIT, useTenantsList } from "./hooks";

const STATUS_OPTIONS = (Object.keys(TENANT_STATUS_LABELS) as (keyof typeof TENANT_STATUS_LABELS)[]).filter(
  (s) => s !== "PROVISIONING",
) as TenantStatus[];
const PLAN_OPTIONS = Object.keys(PLAN_LABELS) as TenantPlan[];

/**
 * 租户管理列表页（EDP-501，视觉基线 `租户管理.html` 头部 + 13.7 表格模式）：
 * status/plan 筛选 + 表格（slug/name/plan/status pill/用量摘要/创建时间/操作「查看」）
 * + 游标分页 + 空态三件套 + 「新建租户」（平台配置组可见性门控）+ 「切换租户」。
 */
export function TenantsPage() {
  const [status, setStatus] = useState<"" | TenantStatus>("");
  const [plan, setPlan] = useState<"" | TenantPlan>("");
  const [cursorStack, setCursorStack] = useState<(string | null)[]>([null]);
  const [createOpen, setCreateOpen] = useState(false);
  const [switchOpen, setSwitchOpen] = useState(false);
  const navigate = useNavigate();
  const user = useSessionStore((s) => s.user);
  const canCreate = canSeeGroup("platform_config", user?.roles ?? [], Boolean(user?.is_platform_admin));

  const pageIndex = cursorStack.length - 1;
  const cursor = cursorStack[pageIndex];
  const listQuery = useTenantsList(
    { status: status || undefined, plan: plan || undefined },
    cursor,
  );
  const items: TenantListItem[] = listQuery.data?.items ?? [];
  const total = listQuery.data?.total ?? 0;
  const nextCursor = listQuery.data?.next_cursor ?? null;

  const resetCursor = () => setCursorStack([null]);
  const clearFilters = () => {
    setStatus("");
    setPlan("");
    resetCursor();
  };
  const removeChip = (key: string) => {
    if (key === "status") setStatus("");
    else if (key === "plan") setPlan("");
    resetCursor();
  };

  const chips: FilterChip[] = [];
  if (status) chips.push({ key: "status", label: `状态：${TENANT_STATUS_LABELS[status].label}` });
  if (plan) chips.push({ key: "plan", label: `套餐：${PLAN_LABELS[plan]}` });

  const offset = pageIndex * TENANTS_PAGE_LIMIT;
  const start = items.length === 0 ? 0 : offset + 1;
  const end = offset + items.length;
  const navLocked = listQuery.isFetching;

  return (
    <div className="flex flex-col gap-4 h-full" data-dom-id="tenants-page">
      <section className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <h1 className="text-xl font-semibold text-foreground">租户管理</h1>
        <div className="flex items-center gap-2">
          <button
            type="button"
            data-dom-id="tenants-switch"
            onClick={() => setSwitchOpen(true)}
            className="h-9 px-3 border border-border bg-card rounded-lg text-xs text-muted-foreground hover:bg-muted flex items-center gap-1.5"
          >
            <ArrowRight className="w-4 h-4" aria-hidden="true" />
            切换租户
          </button>
          {canCreate && (
            <button
              type="button"
              data-dom-id="tenant-create"
              onClick={() => setCreateOpen(true)}
              className="h-9 px-3 bg-primary text-primary-foreground rounded-lg text-xs hover:opacity-90 flex items-center gap-1.5"
            >
              <Plus className="w-4 h-4" aria-hidden="true" />
              新建租户
            </button>
          )}
        </div>
      </section>

      {/* 工具栏：筛选控件 + 已生效 chips */}
      <section className="bg-card border border-border rounded-xl p-3">
        <div className="flex flex-col lg:flex-row lg:items-center gap-3">
          <select
            data-dom-id="tenants-filter-status"
            aria-label="状态筛选"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as "" | TenantStatus);
              resetCursor();
            }}
            className="h-9 px-3 text-xs bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="">全部状态</option>
            {STATUS_OPTIONS.map((value) => (
              <option key={value} value={value}>
                {TENANT_STATUS_LABELS[value].label}
              </option>
            ))}
          </select>
          <select
            data-dom-id="tenants-filter-plan"
            aria-label="套餐筛选"
            value={plan}
            onChange={(e) => {
              setPlan(e.target.value as "" | TenantPlan);
              resetCursor();
            }}
            className="h-9 px-3 text-xs bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="">全部套餐</option>
            {PLAN_OPTIONS.map((value) => (
              <option key={value} value={value}>
                {PLAN_LABELS[value]}
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
          data-dom-id="tenants-error"
        >
          租户列表暂不可用
        </div>
      ) : listQuery.data == null ? (
        <div className="bg-card border border-border rounded-xl p-4">
          <Skeleton active paragraph={{ rows: 6 }} />
        </div>
      ) : items.length === 0 ? (
        <div data-dom-id="tenants-empty">
          <EmptyState
            title="未找到租户"
            description="当前筛选条件没有匹配结果，请调整状态或套餐筛选。"
            primaryAction={{ label: "清空筛选", onClick: clearFilters }}
          />
        </div>
      ) : (
        <section
          className="bg-card border border-border rounded-xl overflow-hidden flex-1 min-h-0 flex flex-col"
          data-dom-id="tenants-content"
        >
          <div className="table-scroll flex-1 min-h-0" data-dom-id="tenants-table">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wider text-muted-foreground border-b border-border">
                  <th className="px-4 py-2.5 font-medium">租户编码</th>
                  <th className="px-4 py-2.5 font-medium">名称</th>
                  <th className="px-4 py-2.5 font-medium">套餐</th>
                  <th className="px-4 py-2.5 font-medium">状态</th>
                  <th className="px-4 py-2.5 font-medium">用量摘要</th>
                  <th className="px-4 py-2.5 font-medium">创建时间</th>
                  <th className="px-4 py-2.5 font-medium text-right">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {items.map((row) => {
                  const statusDisplay = TENANT_STATUS_LABELS[row.status] ?? {
                    label: row.status,
                    tone: "muted" as const,
                  };
                  return (
                    <tr
                      key={row.tenant_id}
                      data-dom-id={`tenants-row-${row.tenant_id}`}
                      className="hover:bg-muted/50 transition-colors"
                    >
                      <td className="px-4 py-2.5 font-mono text-foreground whitespace-nowrap">
                        {row.slug}
                      </td>
                      <td className="px-4 py-2.5 max-w-[240px]">
                        <div className="truncate text-foreground" title={row.name}>
                          {row.name}
                        </div>
                      </td>
                      <td className="px-4 py-2.5 text-muted-foreground whitespace-nowrap">
                        {planLabel(row.plan)}
                      </td>
                      <td className="px-4 py-2.5">
                        <StatusPill tone={statusDisplay.tone} label={statusDisplay.label} size="sm" />
                      </td>
                      <td className="px-4 py-2.5 text-muted-foreground whitespace-nowrap" data-dom-id={`tenants-usage-${row.tenant_id}`}>
                        {row.usage == null || (row.usage.storage_used_gb == null && row.usage.events_this_month == null)
                          ? "—"
                          : `${row.usage.storage_used_gb != null ? fmtCompact(row.usage.storage_used_gb) + " GB" : "—"} · ${
                              row.usage.events_this_month != null ? fmt(row.usage.events_this_month) + " 条/月" : "—"
                            }`}
                      </td>
                      <td className="px-4 py-2.5 text-muted-foreground whitespace-nowrap">
                        {fmtDateTime(row.created_at)}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <button
                          type="button"
                          data-dom-id={`tenants-view-${row.tenant_id}`}
                          onClick={() => navigate(`/tenants/${row.tenant_id}`)}
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
        </section>
      )}

      <CreateTenantModal open={createOpen} onClose={() => setCreateOpen(false)} />
      <TenantSwitchModal open={switchOpen} onClose={() => setSwitchOpen(false)} />
    </div>
  );
}
