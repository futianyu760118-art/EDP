import { Dropdown } from "antd";
import { Bell } from "lucide-react";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { EventResponse } from "../mocks/types";
import { deriveActionLabel } from "../features/audit/vocab";
import { eventsApi } from "../features/events/api";

/** 未读水位 localStorage 键（ISO 时间戳——最近一次已读事件的 occurred_at）。 */
const LAST_READ_KEY = "edp.bell.lastReadTs";
/** 拉取窗口（W5-12 收口后为后端前缀过滤下的兜底窗口：请求携带 event_type_prefix，
 *  客户端 quality. 前缀过滤仅作降级兜底——旧契约/代理剥参时仍正确截断）。 */
const FEED_WINDOW = 50;
const FEED_LIMIT = 20;

/**
 * quality. 前缀事件 → 中文摘要：event_type 复用审计词表（audit/vocab 的
 * QUALITY 前缀 + 复合动词字典——W4 终审 Minor 预留），data 取已知键轻量摘要，
 * 未命中回退原文。 */
function qualityLabel(eventType: string): string {
  const action = `QUALITY_${eventType.replace(/^quality\./, "").replace(/\./g, "_").toUpperCase()}`;
  return deriveActionLabel(action);
}

function qualitySummary(data: Record<string, unknown>): string {
  const stats = data.stats as Record<string, unknown> | undefined;
  if (typeof data.evidence_id === "string") {
    return `证据 ${data.evidence_id.slice(0, 8)} checksum 失配`;
  }
  if (typeof data.mismatched === "number") {
    return `失配 ${data.mismatched} 条（明细见事件详情）`;
  }
  if (stats != null && typeof stats.total === "number") {
    const mismatched = typeof stats.mismatched === "number" ? stats.mismatched : 0;
    return `重算 ${stats.total} 条，失配 ${mismatched}`;
  }
  if (typeof data.scope === "string") {
    return `scope ${data.scope}`;
  }
  return "";
}

function fmtTime(iso: string): string {
  return iso.slice(5, 16).replace("T", " ");
}

/**
 * 顶栏 Bell 最小消息中心（T13）：最近 20 条 quality.* 事件下拉面板。
 * 拉取策略取简——仅按需（挂载取一次供徽标计数 + 打开时重拉），不轮询。
 * W5-12 收口：查询携带 event_type_prefix=quality. 走后端前缀过滤；客户端
 * 前缀过滤降为兜底（FEED_WINDOW 兜底窗口，见常量注释）。
 */
export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();

  const feedQuery = useQuery({
    queryKey: ["bell", "quality-feed"],
    queryFn: () => eventsApi.list({ limit: FEED_WINDOW, event_type_prefix: "quality." }),
    select: (page) =>
      page.items.filter((e) => e.event_type.startsWith("quality.")).slice(0, FEED_LIMIT),
  });
  const items: EventResponse[] = feedQuery.data ?? [];

  const lastRead = window.localStorage.getItem(LAST_READ_KEY);
  const unread = lastRead == null ? items.length : items.filter((e) => e.occurred_at > lastRead).length;

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (next) {
      void queryClient.invalidateQueries({ queryKey: ["bell", "quality-feed"] });
      // 点开即清零：水位推进到最新一条已读（无消息则当前时刻）
      window.localStorage.setItem(
        LAST_READ_KEY,
        items[0]?.occurred_at ?? new Date().toISOString(),
      );
    }
  };

  return (
    <Dropdown
      trigger={["click"]}
      open={open}
      onOpenChange={handleOpenChange}
      placement="bottomRight"
      popupRender={() => (
        <div
          className="w-[340px] bg-card border border-border rounded-xl shadow-lg overflow-hidden"
          data-dom-id="bell-panel"
        >
          <div className="px-4 py-2.5 border-b border-border flex items-center justify-between">
            <span className="text-xs font-semibold text-foreground">质量通知</span>
            <span className="text-[10px] text-muted-foreground">最近 {items.length} 条</span>
          </div>
          {feedQuery.isError ? (
            <p className="px-4 py-6 text-xs text-muted-foreground text-center" data-dom-id="bell-error">
              通知加载失败，请稍后重试
            </p>
          ) : items.length === 0 ? (
            <p className="px-4 py-6 text-xs text-muted-foreground text-center" data-dom-id="bell-empty">
              暂无质量通知
            </p>
          ) : (
            <ul className="max-h-[320px] overflow-y-auto" data-dom-id="bell-list">
              {items.map((event) => {
                const summary = qualitySummary((event.data ?? {}) as Record<string, unknown>);
                return (
                  <li
                    key={event.event_id}
                    data-dom-id={`bell-item-${event.event_id}`}
                    className="px-4 py-2.5 border-b border-border last:border-b-0 hover:bg-muted"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-medium text-foreground truncate">
                        {qualityLabel(event.event_type)}
                      </span>
                      <span className="text-[10px] text-muted-foreground font-mono shrink-0">
                        {fmtTime(event.occurred_at)}
                      </span>
                    </div>
                    {summary !== "" && (
                      <p className="text-[11px] text-muted-foreground mt-0.5 truncate">{summary}</p>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    >
      <button
        type="button"
        className="h-9 px-2.5 border border-border bg-card rounded-lg text-muted-foreground hover:bg-muted flex items-center gap-1.5 relative"
        data-dom-id="notifications-btn"
        aria-label="质量通知"
      >
        <Bell className="w-4 h-4" aria-hidden="true" />
        {unread > 0 && (
          <span
            className="text-[10px] bg-primary text-primary-foreground px-1.5 py-0.5 rounded-full"
            data-dom-id="notifications-badge"
          >
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>
    </Dropdown>
  );
}
