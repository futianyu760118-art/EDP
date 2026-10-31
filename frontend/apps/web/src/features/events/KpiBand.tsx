import { ShieldCheck, Timer, TriangleAlert, Zap } from "lucide-react";
import { KpiCard } from "@edp/shared";
import { fmt } from "../../lib/labels";
import type { HealthResponse } from "../../mocks/types";

const icon = (Icon: typeof Zap) => <Icon className="w-4 h-4" />;

/**
 * 事件流 KPI 带（EDP-301，视觉基线：`原型设计/pages/事件流.html` 行 353~386）：
 * 24H 事件（+峰值副标）/ P95 接入延迟 / 幂等命中率 / 死信队列（warning）。
 * 数据取 health.ops_metrics；字段缺失 → 值「—」且副标隐藏（无环比数据源，环比副标不渲染）。
 */
export function KpiBand({ ops }: { ops?: HealthResponse["ops_metrics"] }) {
  return (
    <section className="grid grid-cols-2 md:grid-cols-4 gap-4" data-dom-id="events-kpi-band">
      <KpiCard
        label="24H 事件"
        value={ops?.events_24h != null ? fmt(ops.events_24h) : "—"}
        hint={ops?.ingest_peak_24h != null ? `峰值 ${fmt(ops.ingest_peak_24h)} / 小时` : undefined}
        icon={icon(Zap)}
      />
      <KpiCard
        label="P95 接入延迟"
        value={ops?.p95_latency_ms != null ? `${(ops.p95_latency_ms / 1000).toFixed(2)}s` : "—"}
        icon={icon(Timer)}
      />
      <KpiCard
        label="幂等命中率"
        value={
          ops?.idempotency_hit_rate != null
            ? `${(ops.idempotency_hit_rate * 100).toFixed(2)}%`
            : "—"
        }
        hint={ops?.idempotency_hit_rate != null ? "重复事件极少" : undefined}
        icon={icon(ShieldCheck)}
      />
      <KpiCard
        label="死信队列"
        value={ops?.dlq != null ? fmt(ops.dlq) : "—"}
        hint={ops?.dlq != null ? "待人工复核" : undefined}
        tone="warning"
        icon={icon(TriangleAlert)}
      />
    </section>
  );
}
