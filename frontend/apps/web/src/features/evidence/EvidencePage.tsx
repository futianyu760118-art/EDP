import { message, Skeleton } from "antd";
import {
  ChevronLeft,
  ChevronRight,
  FileSearch,
  Percent,
  RotateCw,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  CursorPagination,
  EmptyState,
  FilterChips,
  KpiCard,
  type FilterChip,
} from "@edp/shared";
import type { EvidenceRecord } from "../../mocks/types";
import { EVIDENCE_PAGE_LIMIT } from "./api";
import { ChainPanel } from "./ChainPanel";
import type { VerifyState } from "./derive";
import { EvidenceList } from "./EvidenceList";
import { useEvidenceHealth, useEvidenceList, useObjectEvidence, useVerifyEvidence } from "./hooks";
import { ReindexWizard } from "./ReindexWizard";

const SOURCES = ["erp", "plm", "mes", "mdm", "crm"] as const;

function KpiBand({
  ops,
}: {
  ops:
    | {
        evidence_count: number;
        evidence_valid_rate?: number;
        object_coverage_pct?: number;
        evidence_access_24h?: number;
      }
    | undefined;
}) {
  const count = ops?.evidence_count;
  const validRate = ops?.evidence_valid_rate;
  const coverage = ops?.object_coverage_pct;
  const access24h = ops?.evidence_access_24h;
  return (
    <section className="grid grid-cols-2 lg:grid-cols-4 gap-3" data-dom-id="evidence-kpi-band">
      <KpiCard
        label="证据数量"
        value={count != null ? count.toLocaleString() : "—"}
        icon={<FileSearch className="w-4 h-4" />}
      />
      <KpiCard
        label="对象覆盖率"
        value={coverage != null ? `${coverage.toFixed(1)}%` : "—"}
        hint={coverage != null ? undefined : "W5 质量报表交付"}
        icon={<Percent className="w-4 h-4" />}
        tone={coverage != null ? "primary" : "muted"}
      />
      <KpiCard
        label="校验和有效"
        value={validRate != null ? `${validRate.toFixed(2)}%` : "—"}
        hint={validRate != null ? "仅少量异常" : undefined}
        icon={<ShieldCheck className="w-4 h-4" />}
        tone="success"
      />
      <KpiCard
        label="原文访问"
        value={access24h != null ? access24h.toLocaleString() : "—"}
        hint={access24h != null ? "过去 24 小时" : "过去 24 小时 · W5 计量接入"}
        icon={<FileSearch className="w-4 h-4" />}
        tone={access24h != null ? "primary" : "muted"}
      />
    </section>
  );
}

/**
 * 证据库页（EDP-302，视觉基线 `原型设计/pages/证据库.html` + 设计 13.6.2）：
 * KPI 带 + 工具栏（卡内搜索/来源筛选）+ 双栏（证据列表 | 证据链图）+
 * verify 联动（本会话状态 pill）+ 重建索引三步向导（T6 真端点，全量 scope）。
 */
export function EvidencePage() {
  const [search, setSearch] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [sourceSystem, setSourceSystem] = useState("");
  const [cursorStack, setCursorStack] = useState<(string | null)[]>([null]);
  const [selected, setSelected] = useState<EvidenceRecord | undefined>(undefined);
  const [verifyState, setVerifyState] = useState<Record<string, VerifyState>>({});
  const [wizardOpen, setWizardOpen] = useState(false);
  const pageIndex = cursorStack.length - 1;
  const cursor = cursorStack[pageIndex];

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQ(search.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  const listQuery = useEvidenceList({ q: debouncedQ || undefined }, cursor);
  const healthQuery = useEvidenceHealth();
  const verify = useVerifyEvidence();
  const objectEvidence = useObjectEvidence(selected?.object_id);

  const items = useMemo(() => {
    const all = listQuery.data?.items ?? [];
    return sourceSystem
      ? all.filter((item) => item.source_system === sourceSystem)
      : all;
  }, [listQuery.data, sourceSystem]);
  const nextCursor = listQuery.data?.next_cursor ?? null;

  const resetCursor = () => setCursorStack([null]);
  const clearFilters = () => {
    setSearch("");
    setDebouncedQ("");
    setSourceSystem("");
    resetCursor();
  };
  const removeChip = (key: string) => {
    if (key === "q") {
      setSearch("");
      setDebouncedQ("");
      resetCursor();
    } else if (key === "source") {
      setSourceSystem("");
    }
  };

  const chips: FilterChip[] = [];
  if (debouncedQ) chips.push({ key: "q", label: `关键词：${debouncedQ}` });
  if (sourceSystem) chips.push({ key: "source", label: `来源：${sourceSystem}` });

  const offset = pageIndex * EVIDENCE_PAGE_LIMIT;
  const start = items.length === 0 ? 0 : offset + 1;
  const end = offset + items.length;
  const navLocked = listQuery.isFetching;

  const handleVerify = (record: EvidenceRecord) => {
    setVerifyState((state) => ({ ...state, [record.evidence_id]: "pending" }));
    verify.mutate(record.evidence_id, {
      onSuccess: (result) => {
        setVerifyState((state) => ({
          ...state,
          [record.evidence_id]: result.valid ? "valid" : "invalid",
        }));
        void message[result.valid ? "success" : "error"](
          result.valid ? "校验通过：快照与 checksum 一致" : "校验失败：快照可能被篡改",
        );
      },
      onError: () => {
        setVerifyState((state) => ({ ...state, [record.evidence_id]: "unverified" }));
        void message.error("校验请求失败，请稍后重试");
      },
    });
  };

  const navButtonClass =
    "h-8 px-2.5 border border-border rounded-lg text-muted-foreground hover:bg-muted disabled:opacity-50 disabled:pointer-events-none";

  return (
    <div className="flex flex-col gap-4 h-full" data-dom-id="evidence-page">
      <section className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <h1 className="text-xl font-semibold text-foreground">证据库</h1>
        <div className="flex items-center gap-2">
          <button
            type="button"
            data-dom-id="evidence-sample-btn"
            onClick={() => void message.info("完整性抽检任务 W5 交付")}
            className="h-9 px-3 border border-border bg-card text-foreground rounded-lg text-xs font-medium hover:bg-muted"
          >
            完整性抽检
          </button>
          <button
            type="button"
            data-dom-id="evidence-reindex-btn"
            onClick={() => setWizardOpen(true)}
            className="h-9 px-4 bg-primary text-primary-foreground rounded-lg text-xs font-medium hover:opacity-90 flex items-center gap-1.5"
          >
            <RotateCw className="w-4 h-4" aria-hidden="true" />
            重建索引
          </button>
        </div>
      </section>

      <KpiBand ops={healthQuery.data} />

      <section className="bg-card border border-border rounded-xl p-3">
        <div className="flex flex-col lg:flex-row lg:items-center gap-3">
          <input
            type="search"
            data-dom-id="evidence-search"
            aria-label="搜索证据"
            placeholder="搜索业务键 / 来源系统"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              resetCursor();
            }}
            className="h-9 px-3 text-xs bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring lg:w-72"
          />
          <select
            data-dom-id="evidence-source"
            aria-label="来源系统筛选"
            value={sourceSystem}
            onChange={(e) => setSourceSystem(e.target.value)}
            className="h-9 px-3 text-xs bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="">全部来源</option>
            {SOURCES.map((source) => (
              <option key={source} value={source}>
                {source}
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
          data-dom-id="evidence-error"
        >
          证据列表暂不可用
        </div>
      ) : listQuery.data == null ? (
        <div className="bg-card border border-border rounded-xl p-4">
          <Skeleton active paragraph={{ rows: 6 }} />
        </div>
      ) : items.length === 0 ? (
        <div data-dom-id="evidence-empty">
          <EmptyState
            title="未找到证据"
            description={
              debouncedQ
                ? `没有匹配「${debouncedQ}」的证据，建议尝试更短的关键词或更换来源筛选。`
                : "当前筛选条件没有匹配结果，请调整筛选条件。"
            }
            primaryAction={{ label: "清空筛选", onClick: clearFilters }}
            secondaryAction={{
              label: "重建索引",
              onClick: () => setWizardOpen(true),
            }}
          />
        </div>
      ) : (
        <section className="grid grid-cols-1 xl:grid-cols-[1.2fr_0.8fr] gap-4 flex-1 min-h-0 grid-rows-[repeat(2,minmax(0,1fr))] xl:grid-rows-1">
          <div
            className="bg-card border border-border rounded-xl overflow-hidden flex flex-col min-h-0"
            data-dom-id="evidence-content"
          >
            <EvidenceList
              items={items}
              verifyState={verifyState}
              selectedId={selected?.evidence_id}
              onSelect={setSelected}
              onVerify={handleVerify}
            />
            {listQuery.data.total != null ? (
              <CursorPagination
                start={start}
                end={end}
                total={listQuery.data.total}
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
                data-dom-id="evidence-pagination-fallback"
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
          </div>

          <ChainPanel
            selected={selected}
            objectEvidence={objectEvidence.data}
            verifyState={verifyState}
            onSelect={setSelected}
          />
        </section>
      )}

      <ReindexWizard open={wizardOpen} onClose={() => setWizardOpen(false)} />
    </div>
  );
}
