import { Download, Plus } from "lucide-react";
import { useState } from "react";
import type { AuditLogFilters } from "./api";
import { AuditTable } from "./AuditTable";
import { ExportModal } from "./ExportModal";
import { PolicyTab } from "./PolicyTab";

type AuditTab = "logs" | "policies";

const TABS: { value: AuditTab; label: string; domId: string }[] = [
  { value: "logs", label: "日志", domId: "audit-tab-logs" },
  { value: "policies", label: "策略", domId: "audit-tab-policies" },
];

/**
 * 审计日志页（EDP-401，视觉基线 `原型设计/pages/审计日志.html` + 设计 13.6.3）：
 * 双 tab（日志 AuditTable / 策略 PolicyTab）；头部「导出审计日志」（回显当前
 * 日志筛选的 ExportModal）与「新建策略」（切策略 tab + 打开新建弹窗）；
 * 筛选状态提升到本页，供导出范围回显与接口参数共用同一来源。
 */
export function AuditPage() {
  const [tab, setTab] = useState<AuditTab>("logs");
  const [filters, setFilters] = useState<AuditLogFilters>({});
  const [exportOpen, setExportOpen] = useState(false);
  const [policyCreateOpen, setPolicyCreateOpen] = useState(false);

  const openCreateModal = () => {
    setTab("policies");
    setPolicyCreateOpen(true);
  };

  return (
    <div className="flex flex-col gap-4 h-full" data-dom-id="audit-page">
      <section className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <h1 className="text-xl font-semibold text-foreground">审计日志</h1>
        <div className="flex items-center gap-2">
          <button
            type="button"
            data-dom-id="audit-export"
            onClick={() => setExportOpen(true)}
            className="h-9 px-3 border border-border bg-card rounded-lg text-xs text-muted-foreground hover:bg-muted flex items-center gap-1.5"
          >
            <Download className="w-4 h-4" aria-hidden="true" />
            <span>导出审计日志</span>
          </button>
          <button
            type="button"
            data-dom-id="policy-create"
            onClick={openCreateModal}
            className="h-9 px-3 bg-primary text-primary-foreground rounded-lg text-xs hover:opacity-90 flex items-center gap-1.5"
          >
            <Plus className="w-4 h-4" aria-hidden="true" />
            <span>新建策略</span>
          </button>
        </div>
      </section>

      {/* tab 切换（日志 / 策略） */}
      <div className="flex items-center gap-1 border-b border-border" data-dom-id="audit-tabs" role="tablist">
        {TABS.map((item) => (
          <button
            key={item.value}
            type="button"
            role="tab"
            aria-selected={tab === item.value}
            data-dom-id={item.domId}
            onClick={() => setTab(item.value)}
            className={`h-9 px-4 text-xs font-medium border-b-2 -mb-px transition-colors ${
              tab === item.value
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === "logs" ? (
        <AuditTable filters={filters} onFiltersChange={setFilters} />
      ) : (
        <PolicyTab
          createOpen={policyCreateOpen}
          onCreateOpen={() => setPolicyCreateOpen(true)}
          onCreateClose={() => setPolicyCreateOpen(false)}
        />
      )}

      <ExportModal open={exportOpen} filters={filters} onClose={() => setExportOpen(false)} />
    </div>
  );
}
