import { TriangleAlert } from "lucide-react";
import { Skeleton } from "antd";
import { useNavigate } from "react-router-dom";
import { EmptyState, MonoId, StatusPill, type StatusPillTone } from "@edp/shared";
import { relTime } from "../../lib/labels";
import type { ExceptionItem } from "../../mocks/types";

const riskTone = (level: string): StatusPillTone =>
  level === "P0" ? "error" : level === "P1" ? "warning" : "info";

/**
 * 重点风险/异常列表（T5，视觉基线：`原型设计/pages/风险详情 - 抽屉.html` 行 444~488 入口区）。
 * topExceptions（P1×3）三张卡，点击开风险抽屉。
 */
export function RiskList({ items, loading, error, onOpen }: {
  items?: ExceptionItem[];
  loading: boolean;
  error: unknown;
  onOpen: (item: ExceptionItem) => void;
}) {
  const navigate = useNavigate();
  return (
    <section className="bg-card border border-border rounded-xl p-4" data-dom-id="overview-risk-list">
      <header className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
          <TriangleAlert className="w-4 h-4 text-state-error" aria-hidden="true" />
          重点风险 / 异常
        </h2>
        <a href="#" className="text-xs text-primary hover:underline">
          查看全部
        </a>
      </header>
      {loading ? (
        <Skeleton active paragraph={{ rows: 4 }} />
      ) : error ? (
        <div className="text-xs text-muted-foreground py-6 text-center" data-dom-id="overview-risk-list-error">
          该面板暂不可用
        </div>
      ) : !items?.length ? (
        <div data-dom-id="overview-risk-list-empty">
          <EmptyState
            icon={<TriangleAlert className="w-7 h-7" />}
            title="暂无风险与异常"
            description="当前无待处理风险事件；事件回流后将在此聚合 Top 异常。"
            secondaryAction={{ label: "查看事件流", onClick: () => navigate("/admin/events") }}
          />
        </div>
      ) : (
        <div className="space-y-3">
          {items.map((item) => (
            <button
              key={item.event_id}
              type="button"
              data-dom-id="risk-card"
              onClick={() => onOpen(item)}
              className="w-full text-left border border-border rounded-lg p-3 hover:bg-muted transition-colors"
            >
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-2 min-w-0">
                  <StatusPill tone={riskTone(item.risk_level)} label={item.risk_level} size="sm" />
                  <MonoId id={item.order_no} length={16} copyable={false} />
                </div>
                <span className="shrink-0 text-[10px] text-muted-foreground">{relTime(item.occurred_at)}</span>
              </div>
              <div className="text-xs text-foreground mb-1 truncate">{item.result_type}</div>
              <div className="text-[11px] text-muted-foreground truncate">{item.summary}</div>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
