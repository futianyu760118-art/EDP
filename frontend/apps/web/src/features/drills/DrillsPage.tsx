import { Skeleton } from "antd";
import { History } from "lucide-react";
import { EmptyState } from "@edp/shared";
import { DrillCard } from "./DrillCard";
import { useDrills } from "./hooks";

/**
 * 演练回放页（EDP-502，无设计稿——13.7 卡片模式；运维监控组）：
 * 三演练记录卡纵排（主备切换/整库 PITR 恢复/租户级恢复），SUCCEEDED 呈现实测
 * RTO/RPO 与 readings 读数，PLANNED 降饱和待 T14~T16 实测回填；只读归档无操作。
 */
export function DrillsPage() {
  const drillsQuery = useDrills();
  const items = drillsQuery.data?.items ?? [];

  return (
    <div className="space-y-4" data-dom-id="drills-page">
      <section className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold text-foreground">演练回放</h1>
        <p className="text-xs text-muted-foreground">
          容灾演练实测读数归档（RTO/RPO + 探测读数 + 拓扑）；PLANNED 项待实测后回填。
        </p>
      </section>

      {drillsQuery.isError && drillsQuery.data == null ? (
        <div
          className="bg-card border border-border rounded-xl text-xs text-muted-foreground py-10 text-center"
          data-dom-id="drills-error"
        >
          演练记录暂不可用
        </div>
      ) : drillsQuery.data == null ? (
        <div className="bg-card border border-border rounded-xl p-4">
          <Skeleton active paragraph={{ rows: 6 }} />
        </div>
      ) : items.length === 0 ? (
        <div data-dom-id="drills-empty">
          <EmptyState
            icon={<History className="w-7 h-7" />}
            title="暂无演练记录"
            description="演练记录尚未生成，完成演练后将在此归档实测读数。"
          />
        </div>
      ) : (
        <section className="flex flex-col gap-4" data-dom-id="drills-content">
          {items.map((drill) => (
            <DrillCard key={drill.drill_type} drill={drill} />
          ))}
        </section>
      )}
    </div>
  );
}
