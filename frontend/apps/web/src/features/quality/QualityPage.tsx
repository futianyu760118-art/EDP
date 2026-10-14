import { Skeleton, message } from "antd";
import { AlertTriangle, ListChecks, RefreshCw, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { EmptyState, KpiCard, StatusPill } from "@edp/shared";
import type { ExceptionItem } from "../../mocks/types";
import { useQualityExceptions, useQualityReport } from "./hooks";
import { RecheckModal } from "./RecheckModal";
import { TaskLogDrawer } from "./TaskLogDrawer";

const RISK_TONE = { P0: "error", P1: "error", P2: "warning", P3: "info" } as const;

/** 维度短标签：后端 dimensions.domain 为四段标识（T3 derive_dimensions 值域），
 * 非业务域——按段名映射中文，未知域回退响应 label。 */
const DIMENSION_LABELS: Record<string, string> = {
  reconciliation: "对账",
  coverage: "覆盖率",
  orphans: "孤儿",
  checksum: "校验和抽检",
};

/**
 * 数据质量页（EDP-303，视觉基线 `数据质量.html` + `重新校验 - 弹窗.html` +
 * `任务日志 - 抽屉.html`）：KPI 4 卡 + 左维度评分（四段）+ 右异常卡 +
 * 重校验弹窗 + 任务日志抽屉。数据源：真端点（T3 报告/T4 任务 + EBMS 异常）。
 */
export function QualityPage() {
  const [recheckOpen, setRecheckOpen] = useState(false);
  const [taskId, setTaskId] = useState<string | undefined>(undefined);
  const [taskOpen, setTaskOpen] = useState(false);
  const reportQuery = useQualityReport();
  const exceptionsQuery = useQualityExceptions(3);
  const report = reportQuery.data;

  const openTask = (id: string) => {
    setTaskId(id);
    setTaskOpen(true);
  };

  const exceptions = exceptionsQuery.data?.items ?? [];
  const pending = report?.kpi.pending_exceptions ?? exceptionsQuery.data?.items.length;
  const rest = pending != null ? Math.max(0, pending - exceptions.length) : 0;

  return (
    <div className="flex flex-col gap-4 h-full" data-dom-id="quality-page">
      <section className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <h1 className="text-xl font-semibold text-foreground">数据质量</h1>
        <div className="flex items-center gap-2">
          <button
            type="button"
            data-dom-id="quality-view-exceptions"
            onClick={() =>
              document
                .querySelector('[data-dom-id="quality-exceptions"]')
                ?.scrollIntoView({ behavior: "smooth", block: "start" })
            }
            className="h-9 px-3 border border-border bg-card text-foreground rounded-lg text-xs font-medium hover:bg-muted"
          >
            查看异常
          </button>
          <button
            type="button"
            data-dom-id="quality-recheck-btn"
            onClick={() => setRecheckOpen(true)}
            className="h-9 px-4 bg-primary text-primary-foreground rounded-lg text-xs font-medium hover:opacity-90 disabled:opacity-50 disabled:pointer-events-none flex items-center gap-1.5"
          >
            <RefreshCw className="w-4 h-4" aria-hidden="true" />
            重新检查
          </button>
        </div>
      </section>

      {report == null ? (
        reportQuery.isError ? (
          <div
            className="bg-card border border-border rounded-xl p-4 text-xs text-muted-foreground"
            data-dom-id="quality-error"
          >
            质量报告暂不可用，请稍后重试
          </div>
        ) : (
          <div className="bg-card border border-border rounded-xl p-4">
            <Skeleton active paragraph={{ rows: 4 }} />
          </div>
        )
      ) : (
        <>
          <section className="grid grid-cols-2 lg:grid-cols-4 gap-3" data-dom-id="quality-kpi-band">
            <KpiCard
              label="综合质量"
              value={`${report.kpi.overall_pct}%`}
              hint="四维度评分均分"
              icon={<ShieldAlert className="w-4 h-4" />}
              tone="success"
            />
            <KpiCard
              label="校验通过率"
              value={`${report.kpi.sla_pct}%`}
              hint="证据 checksum 抽检通过率"
              icon={<RefreshCw className="w-4 h-4" />}
              tone="info"
            />
            <KpiCard
              label="完整性"
              value={`${report.kpi.completeness_pct}%`}
              hint="对象覆盖率口径"
              icon={<ListChecks className="w-4 h-4" />}
            />
            <KpiCard
              label="待处理异常"
              value={report.kpi.pending_exceptions}
              hint={`其中 ${report.kpi.high_priority} 项高优先级`}
              icon={<AlertTriangle className="w-4 h-4" />}
              tone="warning"
            />
          </section>

          <section className="grid grid-cols-1 xl:grid-cols-2 gap-4 flex-1 min-h-0 grid-rows-[repeat(2,minmax(0,1fr))] xl:grid-rows-1">
            <div
              className="bg-card border border-border rounded-xl p-4 min-h-0 overflow-auto"
              data-dom-id="quality-dimensions"
            >
              <h2 className="text-xs font-semibold text-foreground mb-3">
                {report.dimensions.length} 个维度 · 实时评分
              </h2>
              <ul className="space-y-3">
                {report.dimensions.map((dimension) => {
                  const low = dimension.score_pct < 95;
                  return (
                    <li key={dimension.domain}>
                      <div className="flex items-center justify-between text-[11px] mb-1">
                        <span className="text-muted-foreground">
                          {DIMENSION_LABELS[dimension.domain] ?? dimension.label}
                        </span>
                        <span className={low ? "text-state-warning" : "text-foreground"}>
                          {dimension.score_pct}%
                        </span>
                      </div>
                      <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                        <div
                          className={`h-full rounded-full ${
                            low ? "bg-state-warning" : "bg-state-success"
                          }`}
                          style={{ width: `${Math.min(100, dimension.score_pct)}%` }}
                          data-dom-id={`quality-dim-${dimension.domain}`}
                        />
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>

            <div
              className="bg-card border border-border rounded-xl p-4 min-h-0 overflow-auto"
              data-dom-id="quality-exceptions"
            >
              <h2 className="text-xs font-semibold text-foreground mb-3">全部异常</h2>
              {exceptionsQuery.isError ? (
                <p className="text-xs text-muted-foreground">异常列表暂不可用</p>
              ) : exceptions.length === 0 && exceptionsQuery.isSuccess ? (
                <div data-dom-id="quality-exceptions-empty">
                  <EmptyState
                    icon={<ListChecks className="w-7 h-7" />}
                    title="当前无待处理异常"
                    description="各维度校验通过；可运行重校验刷新最新报告。"
                    primaryAction={{ label: "运行重校验", onClick: () => setRecheckOpen(true) }}
                  />
                </div>
              ) : exceptions.length === 0 ? (
                <p className="text-xs text-muted-foreground">加载中…</p>
              ) : (
                <ul className="space-y-2">
                  {exceptions.map((item: ExceptionItem) => (
                    <li
                      key={item.event_id}
                      className="border border-border rounded-lg px-3 py-2.5 flex items-start gap-2"
                      data-dom-id={`quality-exception-${item.event_id}`}
                    >
                      <StatusPill
                        tone={RISK_TONE[item.risk_level as keyof typeof RISK_TONE] ?? "muted"}
                        label={item.risk_level}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="text-xs font-medium text-foreground truncate">
                          {item.summary}
                        </div>
                        <div className="text-[10px] text-muted-foreground mt-0.5">
                          {item.order_no} · {item.result_type}
                        </div>
                      </div>
                      <button
                        type="button"
                        data-dom-id={`quality-handle-${item.event_id}`}
                        onClick={() => void message.info("异常处理流程 W4 闭环案例页交付")}
                        className="text-[11px] px-2 py-0.5 rounded border border-border text-muted-foreground hover:bg-muted"
                      >
                        处理
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {rest > 0 && (
                <p className="mt-3 text-[10px] text-muted-foreground" data-dom-id="quality-merged">
                  剩余 {rest} 项异常已合并为低优先级队列
                </p>
              )}
            </div>
          </section>
        </>
      )}

      <RecheckModal
        open={recheckOpen}
        onClose={() => setRecheckOpen(false)}
        onSubmitted={openTask}
      />
      <TaskLogDrawer taskId={taskId} open={taskOpen} onClose={() => setTaskOpen(false)} />
    </div>
  );
}
