import { Skeleton } from "antd";
import { Zap } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { EmptyState, VerticalTimeline, type SemanticTone } from "@edp/shared";
import { fmtDateTime } from "../../lib/labels";
import type { EventResponse } from "../../mocks/types";
import { useRecentEvents } from "./hooks";

const eventTone = (e: EventResponse): SemanticTone =>
  e.risk_level === "P0"
    ? "error"
    : e.risk_level === "P1"
      ? "warning"
      : e.result_type === "DATA_QUALITY"
        ? "info"
        : "primary";

/**
 * 事件与闭环时间线（T6，视觉基线：`原型设计/pages/运营总览.html` 行 490~530 ——
 * 最近 5 条事件 VerticalTimeline，右上「进入事件流」入口；不足 5 条渲染实际条数）。
 */
export function EventsTimeline() {
  const navigate = useNavigate();
  const { data, isPending, error } = useRecentEvents();
  const items = data?.items ?? [];

  return (
    <section className="bg-card border border-border rounded-xl p-4" data-dom-id="overview-events-timeline">
      <header className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
          <Zap className="w-4 h-4 text-primary" aria-hidden="true" />
          事件与闭环
        </h2>
        <Link to="/admin/events" className="text-xs text-primary hover:underline">
          进入事件流 →
        </Link>
      </header>
      {isPending ? (
        <Skeleton active paragraph={{ rows: 4 }} />
      ) : error ? (
        <div className="text-xs text-muted-foreground py-6 text-center" data-dom-id="overview-events-error">
          该面板暂不可用
        </div>
      ) : items.length === 0 ? (
        <div data-dom-id="overview-events-empty">
          <EmptyState
            icon={<Zap className="w-7 h-7" />}
            title="暂无事件回流"
            description="接入适配器或回放历史事件后，最近事件将在此按时间线展示。"
            primaryAction={{ label: "进入事件流", onClick: () => navigate("/admin/events") }}
          />
        </div>
      ) : (
        <div data-dom-id="overview-events-list">
          <VerticalTimeline
            items={items.map((e) => ({
              time: fmtDateTime(e.occurred_at),
              text: e.event_type,
              meta: `${e.event_id.slice(0, 8)} · ${e.source_system}`,
              tone: eventTone(e),
            }))}
          />
        </div>
      )}
    </section>
  );
}
