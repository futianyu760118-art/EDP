import { Collapse, Skeleton } from "antd";
import { X } from "lucide-react";
import { MonoId, StatusPill, VerticalTimeline } from "@edp/shared";
import { fmtDateTime } from "../../lib/labels";
import type { ObjectResponse } from "../../mocks/types";
import { DERIVED_TONE, domainLabel, type DerivedStatus } from "./derive";
import { useObjectHistory } from "./hooks";

/**
 * 业务对象详情抽屉（T8，右 480px）：头部 MonoId(source_id) + 派生 pill + 名称；
 * 基本信息格 / attributes JSON 折叠 / revision 时间线（GET /objects/{id}/history）。
 */
export function DetailDrawer({
  obj,
  status,
  onClose,
}: {
  obj: ObjectResponse;
  status: DerivedStatus;
  onClose: () => void;
}) {
  const historyQuery = useObjectHistory(obj.object_id, true);
  const revisions = historyQuery.data?.revisions ?? [];
  const name = typeof obj.attributes?.name === "string" ? obj.attributes.name : obj.source_id;

  const infoCells: { label: string; value: string }[] = [
    { label: "类型", value: obj.object_type },
    { label: "域", value: domainLabel(obj.owner_domain) },
    { label: "来源", value: obj.source_system.toUpperCase() },
    { label: "状态", value: status },
    { label: "创建时间", value: fmtDateTime(obj.created_at) },
    { label: "更新时间", value: fmtDateTime(obj.updated_at) },
  ];

  return (
    <div
      className="fixed inset-y-0 left-[250px] right-0 z-30 flex justify-end bg-foreground/15 backdrop-blur-sm"
      data-dom-id="object-drawer-overlay"
    >
      <div
        data-dom-id="object-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="object-drawer-title"
        className="w-[480px] h-full bg-card border-l border-border shadow-2 flex flex-col rounded-l-lg"
      >
        <div className="flex items-start justify-between gap-4 p-4 border-b border-border">
          <div className="min-w-0">
            <div className="flex items-center gap-2 mb-1.5">
              <h2 id="object-drawer-title" className="text-lg font-semibold text-foreground">
                <MonoId id={obj.source_id} copyable={false} length={obj.source_id.length} />
              </h2>
              <span className="shrink-0">
                <StatusPill tone={DERIVED_TONE[status]} label={status} size="sm" />
              </span>
            </div>
            <div className="text-xs text-muted-foreground truncate">{name}</div>
          </div>
          <button
            type="button"
            data-dom-id="object-drawer-close"
            aria-label="关闭"
            onClick={onClose}
            className="shrink-0 w-8 h-8 rounded-lg border border-border bg-card text-muted-foreground hover:bg-muted grid place-items-center"
          >
            <X className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-5">
          <div data-dom-id="object-drawer-info">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-3">基本信息</div>
            <div className="grid grid-cols-3 gap-2 text-[11px]">
              {infoCells.map((c) => (
                <div key={c.label} className="bg-muted rounded-md px-2.5 py-2">
                  <span className="text-muted-foreground block">{c.label}</span>
                  <span className="font-medium text-foreground">{c.value}</span>
                </div>
              ))}
            </div>
          </div>

          <div data-dom-id="object-drawer-attributes">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-3">对象属性</div>
            <Collapse
              size="small"
              items={[
                {
                  key: "attributes",
                  label: "attributes",
                  children: (
                    <pre className="font-mono text-[11px] text-foreground whitespace-pre-wrap break-all">
                      {JSON.stringify(obj.attributes, null, 2)}
                    </pre>
                  ),
                },
              ]}
            />
          </div>

          <div data-dom-id="object-drawer-history">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-3">修订历史</div>
            {historyQuery.isPending ? (
              <Skeleton active paragraph={{ rows: 4 }} />
            ) : revisions.length === 0 ? (
              <div className="text-xs text-muted-foreground">暂无修订历史</div>
            ) : (
              <VerticalTimeline
                items={[...revisions].reverse().map((r) => ({
                  time: fmtDateTime(r.occurred_at),
                  text: `${r.action} → Rev ${r.revision}`,
                  meta: r.actor_id,
                  tone: "primary" as const,
                }))}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
