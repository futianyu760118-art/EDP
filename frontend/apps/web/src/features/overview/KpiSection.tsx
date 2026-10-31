import { Layers, Plug, ScrollText, Shield, ShieldCheck, Timer, TriangleAlert, Zap } from "lucide-react";
import { KpiCard, type SemanticTone } from "@edp/shared";
import { fmt, fmtCompact } from "../../lib/labels";
import type { AdapterSummary, HealthResponse } from "../../mocks/types";

const icon = (Icon: typeof Layers) => <Icon className="w-4 h-4" />;

/**
 * 总览 8 KPI 网格（EDP-202，视觉基线：`原型设计/pages/运营总览.html` 行 375~441 kpi-grid）。
 * 值派生 health.ops_metrics（mock 扩展）+ objectsTotal；字段级缺失（真 API 仅返回 6 字段子集）→ 该卡 "—"。
 */
export function KpiSection({ health, objectsTotal, adapters }: {
  health?: HealthResponse;
  objectsTotal?: number;
  adapters?: AdapterSummary[];
}) {
  const ops = health?.ops_metrics;
  // 适配器失败提示：ops_metrics 无失败计数字段，以适配器清单降级数近似（原型文案「3 次失败已恢复」）
  const failedAdapters = adapters?.filter((a) => a.health !== "OK").length;
  const dlqWarning = (ops?.dlq ?? 0) > 0;
  const dlqTone: SemanticTone = dlqWarning ? "warning" : "primary";

  return (
    <section className="grid grid-cols-2 md:grid-cols-4 gap-4" data-dom-id="overview-kpis">
      {/* 业务对象较昨日差值：mock 无字段，契约回填后补（原型「+12 较昨日」） */}
      <KpiCard label="业务对象" value={objectsTotal != null ? fmt(objectsTotal) : "—"} icon={icon(Layers)} />
      <KpiCard
        label="24H 事件"
        value={ops?.events_24h != null ? fmt(ops.events_24h) : "—"}
        hint={ops?.ingest_peak_24h != null ? `峰值 ${fmt(ops.ingest_peak_24h)} / 小时` : undefined}
        icon={icon(Zap)}
      />
      <KpiCard
        label="证据存储"
        value={ops?.evidence_count != null ? fmtCompact(ops.evidence_count) : "—"}
        hint={ops?.evidence_valid_rate != null ? `校验和有效率 ${ops.evidence_valid_rate}%` : undefined}
        icon={icon(ShieldCheck)}
      />
      <KpiCard
        label="适配器成功率"
        value={ops?.adapters_success_rate != null ? `${ops.adapters_success_rate}%` : "—"}
        hint={
          ops?.adapters_success_rate != null
            ? failedAdapters != null && failedAdapters > 0
              ? `${failedAdapters} 次失败已恢复`
              : "运行平稳"
            : undefined
        }
        icon={icon(Plug)}
      />
      <KpiCard
        label="DLQ 队列"
        value={ops?.dlq != null ? fmt(ops.dlq) : "—"}
        hint={ops?.dlq != null ? "待人工复核" : undefined}
        tone={dlqTone}
        icon={icon(TriangleAlert)}
      />
      <KpiCard
        label="P95 延迟"
        value={ops?.p95_latency_ms != null ? `${fmt(ops.p95_latency_ms)}ms` : "—"}
        hint={ops?.p95_latency_ms != null ? "过去 24 小时" : undefined}
        icon={icon(Timer)}
      />
      <KpiCard
        label="审计日志量"
        value={ops?.audit_events_7d != null ? fmtCompact(ops.audit_events_7d) : "—"}
        hint={ops?.audit_events_7d != null ? "近 7 天" : undefined}
        icon={icon(ScrollText)}
      />
      <KpiCard
        label="策略命中"
        value={ops?.policy_hits_today != null ? fmt(ops.policy_hits_today) : "—"}
        hint={ops?.policy_hits_today != null ? "+今日" : undefined}
        icon={icon(Shield)}
      />
    </section>
  );
}
