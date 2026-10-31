import { ArrowRight, Download } from "lucide-react";
import { StatusPill } from "@edp/shared";
import type { HealthResponse, QualityReport } from "../../mocks/types";

/**
 * 总览 Hero 状态卡（EDP-202，视觉基线：`原型设计/pages/运营总览.html` 行 335~373；
 * 主卡改为品牌主色底：bg-primary text-primary-foreground）。三指标缺数据时 "—" 兜底。
 */
export function HeroCard({ coverage, health, p1Count, onOpenRisk }: {
  coverage?: QualityReport["coverage"];
  health?: HealthResponse;
  /** 待处理 P1 风险数（父层传 topExceptions.items.length） */
  p1Count: number;
  /** T5 接风险抽屉 */
  onOpenRisk: () => void;
}) {
  const ops = health?.ops_metrics;
  return (
    <section data-dom-id="overview-hero" className="rounded-xl bg-primary text-primary-foreground p-6">
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <div>
          <div className="mb-3">
            <StatusPill tone="success" label="运行中 · 多租户工作空间" dot />
          </div>
          <h1 className="text-xl font-semibold mb-2" data-dom-id="overview-hero-title">
            今天的 EDP 状态：证据链健康，{p1Count} 个 P1 风险需要处理
          </h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onOpenRisk}
            data-dom-id="overview-hero-risk"
            className="h-9 px-4 bg-primary-foreground text-primary rounded-lg text-xs font-medium flex items-center gap-1.5"
          >
            <ArrowRight className="w-4 h-4" aria-hidden="true" />
            查看风险详情
          </button>
          <button
            type="button"
            data-dom-id="overview-hero-export"
            className="h-9 px-4 border border-primary-foreground/40 text-primary-foreground rounded-lg text-xs font-medium flex items-center gap-1.5"
          >
            <Download className="w-4 h-4" aria-hidden="true" />
            导出日报
          </button>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-4 mt-6 pt-6 border-t border-primary-foreground/20">
        <HeroMetric domId="overview-hero-coverage" label="对象覆盖率" value={coverage ? `${coverage.overall_pct}%` : "—"} />
        <HeroMetric domId="overview-hero-p95" label="P95 接入延迟" value={ops?.p95_latency_ms != null ? `${(ops.p95_latency_ms / 1000).toFixed(2)}s` : "—"} />
        <HeroMetric domId="overview-hero-success" label="适配器成功率" value={ops?.adapters_success_rate != null ? `${ops.adapters_success_rate}%` : "—"} />
      </div>
    </section>
  );
}

/** Hero 内嵌指标格：10px 大写标签 + text-2xl 数值。 */
function HeroMetric({ domId, label, value }: { domId: string; label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider mb-1 text-primary-foreground/70">{label}</div>
      <div className="text-2xl font-semibold" data-dom-id={domId}>
        {value}
      </div>
    </div>
  );
}
