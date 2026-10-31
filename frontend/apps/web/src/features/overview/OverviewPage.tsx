import { useState } from "react";
import { HeroCard } from "./HeroCard";
import { KpiSection } from "./KpiSection";
import { RiskList } from "./RiskList";
import { RiskDrawer } from "../../shared/components/RiskDrawer";
import { EventsTimeline } from "./EventsTimeline";
import { BottomThree } from "./BottomThree";
import { useAdapters, useCoverage, useDeepHealth, useObjectsTotal, useTopExceptions } from "./hooks";
import type { ExceptionItem } from "../../mocks/types";

/** 运营总览页：Hero 状态卡 + 8 KPI 网格（T4）+ 风险列表/抽屉（T5）+ 事件时间线/三栏图表（T6）。 */
export function OverviewPage() {
  const [riskOpen, setRiskOpen] = useState(false);
  const [riskItem, setRiskItem] = useState<ExceptionItem | null>(null);
  const coverage = useCoverage();
  const health = useDeepHealth();
  const adapters = useAdapters();
  const topExceptions = useTopExceptions();
  const objectsTotal = useObjectsTotal();

  const openRisk = (item?: ExceptionItem) => {
    setRiskItem(item ?? null);
    setRiskOpen(true);
  };
  // Hero 入口未指定 item → 派生锚定列表第一条 P1（数据到位即生效）
  const selectedRisk = riskItem ?? topExceptions.data?.items[0] ?? null;

  return (
    <div className="space-y-4" data-dom-id="overview-page">
      <HeroCard
        coverage={coverage.data}
        health={health.data}
        p1Count={topExceptions.data?.items.length ?? 0}
        onOpenRisk={() => openRisk()}
      />
      <KpiSection health={health.data} objectsTotal={objectsTotal.data?.total} adapters={adapters.data?.items} />
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4" data-dom-id="overview-risk">
        <RiskList
          items={topExceptions.data?.items}
          loading={topExceptions.isPending}
          error={topExceptions.error}
          onOpen={openRisk}
        />
        <EventsTimeline />
      </div>
      <BottomThree />
      <RiskDrawer eventId={selectedRisk?.event_id} open={riskOpen} onClose={() => setRiskOpen(false)} />
    </div>
  );
}
