import { Skeleton } from "antd";
import { Boxes, ShieldCheck, Zap } from "lucide-react";
import type { ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { EmptyState, MonoId, StatusPill } from "@edp/shared";
import { eventTypeDisplay, fmtDateTime } from "../../lib/labels";
import type { EventHit, EvidenceHit, ObjectHit, SearchResponse } from "./api";
import { useGlobalSearch } from "./hooks";

function HitSection({
  domId,
  icon,
  title,
  count,
  children,
}: {
  domId: string;
  icon: ReactNode;
  title: string;
  count: number;
  children: ReactNode;
}) {
  return (
    <section className="bg-card border border-border rounded-xl overflow-hidden" data-dom-id={domId}>
      <header className="px-4 py-3 border-b border-border flex items-center gap-2">
        <span className="text-primary">{icon}</span>
        <span className="text-xs font-semibold text-foreground">{title}</span>
        <span className="text-[10px] text-muted-foreground" data-dom-id={`${domId}-count`}>
          {count} 条
        </span>
      </header>
      <ul className="divide-y divide-border">
        {count === 0 ? (
          <li className="px-4 py-4 text-xs text-muted-foreground text-center">本组无命中</li>
        ) : (
          children
        )}
      </ul>
    </section>
  );
}

function ObjectsSection({ hits }: { hits: ObjectHit[] }) {
  return (
    <HitSection domId="search-section-objects" icon={<Boxes className="w-4 h-4" />} title="业务对象" count={hits.length}>
      {hits.map((hit) => (
        <li
          key={hit.object_id}
          data-dom-id="search-object-row"
          className="px-4 py-3 flex items-center gap-3"
        >
          <StatusPill tone="info" label={hit.object_type} size="sm" />
          <MonoId id={hit.source_id} length={16} copyable={false} />
          <span className="ml-auto text-[10px] text-muted-foreground whitespace-nowrap">
            更新于 {fmtDateTime(hit.updated_at)}
          </span>
        </li>
      ))}
    </HitSection>
  );
}

function EventsSection({ hits }: { hits: EventHit[] }) {
  return (
    <HitSection domId="search-section-events" icon={<Zap className="w-4 h-4" />} title="事件" count={hits.length}>
      {hits.map((hit) => {
        const display = eventTypeDisplay(hit.event_type);
        return (
          <li
            key={hit.event_id}
            data-dom-id="search-event-row"
            className="px-4 py-3 flex items-center gap-3"
          >
            <StatusPill tone={display.tone} label={display.label} size="sm" />
            <span className="font-mono text-[10px] text-muted-foreground">{hit.event_type}</span>
            <span className="ml-auto text-[10px] text-muted-foreground whitespace-nowrap">
              {fmtDateTime(hit.occurred_at)}
            </span>
          </li>
        );
      })}
    </HitSection>
  );
}

function EvidenceSection({ hits }: { hits: EvidenceHit[] }) {
  return (
    <HitSection domId="search-section-evidence" icon={<ShieldCheck className="w-4 h-4" />} title="证据" count={hits.length}>
      {hits.map((hit) => (
        <li
          key={hit.evidence_id}
          data-dom-id="search-evidence-row"
          className="px-4 py-3 flex items-center gap-3"
        >
          <StatusPill tone="muted" label={hit.source_system} size="sm" />
          <MonoId id={hit.source_record_id} length={16} copyable={false} />
          <span className="ml-auto text-[10px] text-muted-foreground whitespace-nowrap">
            采集于 {fmtDateTime(hit.captured_at)}
          </span>
        </li>
      ))}
    </HitSection>
  );
}

/**
 * 全局搜索结果页（EDP-601，设计 13.7 列表卡模式；顶栏 global-search 回车跳入）：
 * 三组命中区块（业务对象/事件/证据，各带计数）+ 空态三件套 + 清除搜索回空引导。
 * 命中形状按冻结契约 ObjectHit/EventHit/EvidenceHit 简投影（无 revision/risk/
 * verify 字段，行内以 object_type/事件类型/来源 pill 语义化呈现）。
 * 如需 revision/risk_level/verify 等字段须后端契约变更后 api-sdk regen（本轮契约已冻结）。
 * 空态文案口径：原设计稿 21 为证据库语境（「未找到匹配结果/清除筛选」），搜索页
 * 改编为「未找到相关结果/清除搜索」。
 */
export function SearchPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const q = (searchParams.get("q") ?? "").trim();
  const searchQuery = useGlobalSearch(q);
  const data: SearchResponse | undefined = searchQuery.data;

  return (
    <div className="space-y-4" data-dom-id="search-page">
      <section className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold text-foreground">全局搜索</h1>
        <p className="text-xs text-muted-foreground" data-dom-id="search-summary">
          {q
            ? `关键词「${q}」${data != null ? ` · 共 ${data.total} 条结果` : ""}`
            : "检索业务对象、事件与证据"}
        </p>
      </section>

      {!q ? (
        <div data-dom-id="search-idle">
          <EmptyState
            title="输入关键词开始搜索"
            description="在顶栏搜索框输入关键词并回车，检索业务对象、事件与证据。"
          />
        </div>
      ) : searchQuery.isError ? (
        <div
          className="bg-card border border-border rounded-xl text-xs text-muted-foreground py-10 text-center"
          data-dom-id="search-error"
        >
          搜索暂不可用，请稍后重试
        </div>
      ) : data == null ? (
        <div className="bg-card border border-border rounded-xl p-4">
          <Skeleton active paragraph={{ rows: 6 }} />
        </div>
      ) : data.total === 0 ? (
        <div data-dom-id="search-empty">
          <EmptyState
            title="未找到相关结果"
            description={`没有找到与「${q}」匹配的业务对象、事件或证据，请尝试其他关键词。`}
            primaryAction={{ label: "清除搜索", onClick: () => navigate("/search") }}
            secondaryAction={{ label: "查看业务对象", onClick: () => navigate("/admin/registry") }}
          />
        </div>
      ) : (
        <>
          <ObjectsSection hits={data.objects ?? []} />
          <EventsSection hits={data.events ?? []} />
          <EvidenceSection hits={data.evidence ?? []} />
        </>
      )}
    </div>
  );
}
