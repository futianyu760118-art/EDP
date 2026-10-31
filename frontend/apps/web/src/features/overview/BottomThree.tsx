import { Bot, Check, Settings, User } from "lucide-react";
import { Link } from "react-router-dom";
import { StatusPill, type StatusPillTone } from "@edp/shared";
import { fmt, relTime } from "../../lib/labels";
import type { AuditLogItem } from "../../mocks/types";
import { PanelCard } from "./PanelCard";
import { MiniBarChart } from "./charts/MiniBarChart";
import { DonutRing } from "./charts/DonutRing";
import { useDeepHealth, useQualityReport, useRecentAudit } from "./hooks";

const denied = (action: string) => action.includes("GUARD_DENIED") || action.includes("DENIED");

const actorIcon = (actorType: string) => (actorType === "HUMAN" ? User : actorType === "AI" ? Bot : Settings);

function MetricCell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] text-muted-foreground">{label}</div>
      <div className="text-sm font-semibold text-foreground">{value}</div>
    </div>
  );
}

function AuditRow({ item }: { item: AuditLogItem }) {
  const Icon = actorIcon(item.actor_type);
  const tone: StatusPillTone = denied(item.action) ? "error" : "muted";
  return (
    <div className="flex items-start gap-3" data-dom-id="overview-audit-row">
      <div className="w-6 h-6 rounded-full bg-primary-50 text-primary grid place-items-center shrink-0">
        <Icon className="w-3 h-3" aria-hidden="true" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-foreground truncate">{item.actor_id}</span>
          <span className="shrink-0">
            <StatusPill tone={tone} label={item.action} size="sm" />
          </span>
        </div>
        <div className="text-[10px] text-muted-foreground truncate">
          {relTime(item.occurred_at)} ·{" "}
          <span className="font-mono" title={item.resource_id}>
            {item.resource_id.length > 16 ? `${item.resource_id.slice(0, 16)}…` : item.resource_id}
          </span>
        </div>
      </div>
    </div>
  );
}

/**
 * 总览底部三栏（T6，视觉基线：`原型设计/pages/运营总览.html` 行 533~635 ——
 * 数据健康（24H 柱图 + 质量子指标）/ 证据链健康（有效率环形）/ 审计动态（GUARD 越权高亮））。
 * 三数据源独立 PanelCard 降级；原型三栏无面板标题，标题为导航/无障碍补充。
 */
export function BottomThree() {
  const health = useDeepHealth();
  const quality = useQualityReport();
  const audit = useRecentAudit();
  const ops = health.data?.ops_metrics;
  const kpi = quality.data?.kpi;
  const auditItems = audit.data?.items ?? [];

  return (
    <div className="three-col" data-dom-id="overview-bottom">
      <PanelCard
        domId="panel-data-health"
        title="数据健康"
        loading={quality.isPending}
        error={quality.error}
        action={<span className="text-[10px] text-muted-foreground">过去 24 小时</span>}
      >
        <MiniBarChart peak={ops?.ingest_peak_24h} />
        <div className="grid grid-cols-2 gap-3 pt-3 mt-3 border-t border-border">
          <MetricCell label="校验通过率" value={kpi ? `${kpi.sla_pct}%` : "—"} />
          <MetricCell label="完整性" value={kpi ? `${kpi.completeness_pct}%` : "—"} />
          <MetricCell label="对象覆盖率" value={quality.data ? `${quality.data.coverage.overall_pct}%` : "—"} />
          <MetricCell label="孤儿事件" value={quality.data ? fmt(quality.data.orphans.event_orphans) : "—"} />
        </div>
      </PanelCard>

      <PanelCard
        domId="panel-evidence-health"
        title="证据链健康"
        loading={health.isPending}
        error={health.error}
        empty={ops == null}
        action={<StatusPill tone="success" label="健康" size="sm" />}
      >
        <div className="flex items-center justify-center py-4">
          <DonutRing pct={ops?.evidence_valid_rate ?? 0} label="完整" />
        </div>
        <div className="space-y-2 pt-3 border-t border-border">
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">证据总量</span>
            <span className="font-medium text-foreground">{fmt(ops?.evidence_count ?? 0)}</span>
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">校验和有效率</span>
            <span className="font-medium text-state-success">{ops?.evidence_valid_rate ?? 0}%</span>
          </div>
          <div className="flex items-center gap-1.5 text-[11px] text-state-success">
            <Check className="w-3.5 h-3.5" aria-hidden="true" />
            依赖关系完整
          </div>
        </div>
      </PanelCard>

      <PanelCard
        domId="panel-audit"
        title="审计动态"
        loading={audit.isPending}
        error={audit.error}
        empty={auditItems.length === 0}
        action={
          <Link to="/admin/audit" className="text-xs text-primary hover:underline">
            更多
          </Link>
        }
      >
        <div className="space-y-3">
          {auditItems.map((item) => (
            <AuditRow key={item.audit_id} item={item} />
          ))}
        </div>
      </PanelCard>
    </div>
  );
}
