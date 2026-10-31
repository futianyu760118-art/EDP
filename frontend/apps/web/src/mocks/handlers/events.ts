import { http, HttpResponse } from "msw";
import type { EventResponse } from "../types";
import { clampLimit, paginate } from "../lib/cursor";
import { errorOf } from "../lib/http";
import { scenarioResponse } from "../lib/scenario";
import { events } from "../data/events";
import { findObject } from "../data/objects";
import { TENANT_ID, mockUuid } from "../data/ids";
import { iso } from "../lib/demo-time";

/** 写语义：会话内追加 + Idempotency-Key 档案（B.3），刷新即复位。 */
const store: EventResponse[] = events.map((e) => ({ ...e }));
const batchArchive = new Map<string, { accepted: number; duplicated: number; rejected: number }>();
let syntheticSeq = 1000; // batch 写入生成段（mockUuid 1000+）

function sortedAll(): EventResponse[] {
  return [...store].sort((a, b) =>
    b.occurred_at.localeCompare(a.occurred_at) || b.event_id.localeCompare(a.event_id),
  );
}

interface EventInBody {
  events?: {
    event_id?: string;
    event_type?: string;
    object_id?: string;
    source_system?: string;
    occurred_at?: string;
    actor_type?: "HUMAN" | "SERVICE" | "AI";
    actor_id?: string | null;
    result_type?: string | null;
    risk_level?: "P0" | "P1" | "P2" | "P3" | null;
    score?: number | null;
    data?: Record<string, unknown>;
  }[];
}

export const eventHandlers = [
  // B.3 GET /events：过滤（object_id/event_type 精确/event_type_prefix 前缀 LIKE/risk_level/since/until 闭区间）
  // + 游标分页（occurred_at DESC）
  http.get("*/api/v1/events", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const q = new URL(request.url).searchParams;
    const prefix = q.get("event_type_prefix");
    const filtered = sortedAll().filter((e) => {
      if (q.get("object_id") && e.object_id !== q.get("object_id")) return false;
      if (q.get("event_type") && e.event_type !== q.get("event_type")) return false;
      if (prefix && !e.event_type.startsWith(prefix)) return false;
      if (q.get("risk_level") && e.risk_level !== q.get("risk_level")) return false;
      if (q.get("since") && e.occurred_at < q.get("since")!) return false;
      if (q.get("until") && e.occurred_at > q.get("until")!) return false;
      return true;
    });
    return HttpResponse.json(paginate(filtered, clampLimit(q.get("limit")), q.get("cursor")));
  }),

  // B.3 GET /events/{id}：404 统一
  http.get("*/api/v1/events/:eventId", ({ params }) => {
    const found = store.find((e) => e.event_id === String(params.eventId));
    if (!found) return errorOf("NOT_FOUND", "资源不存在", 404);
    return HttpResponse.json(found);
  }),

  // B.3 POST /events/batch：Idempotency-Key 必填；重放返回存档 + deduplicated=true
  http.post("*/api/v1/events/batch", async ({ request }) => {
    const key = request.headers.get("Idempotency-Key");
    if (!key) return errorOf("VALIDATION_ERROR", "缺少 Idempotency-Key 头", 400);
    const archived = batchArchive.get(key);
    if (archived) {
      return HttpResponse.json({ ...archived, deduplicated: true });
    }
    const body = (await request.json().catch(() => null)) as EventInBody | null;
    if (!body?.events?.length) return errorOf("VALIDATION_ERROR", "events 不能为空", 400);
    let accepted = 0;
    for (const item of body.events) {
      if (!item.event_type || !item.object_id || !item.source_system || !item.occurred_at) {
        continue; // 字段不全 → rejected（mock 简化）
      }
      accepted += 1;
      syntheticSeq += 1;
      store.push({
        event_id: item.event_id ?? mockUuid(syntheticSeq),
        tenant_id: TENANT_ID,
        event_type: item.event_type,
        object_id: item.object_id,
        source_system: item.source_system,
        occurred_at: item.occurred_at,
        actor_type: item.actor_type ?? "SERVICE",
        actor_id: item.actor_id ?? "service:mock",
        result_type: item.result_type ?? null,
        risk_level: item.risk_level ?? null,
        score: item.score ?? null,
        data: item.data ?? {},
        idempotency_key: key,
        // 刚入库未分发（outbox PENDING）；耗时由生成序号确定性派生（60~299ms）
        ingest_latency_ms: 60 + (syntheticSeq % 240),
        delivery_status: "PENDING",
        object_source_id: findObject(item.object_id)?.source_id ?? null,
        created_at: iso("2026-09-28T08:30:00Z"),
      });
    }
    const rejected = body.events.length - accepted;
    const result = { accepted, duplicated: 0, rejected };
    batchArchive.set(key, result);
    return HttpResponse.json({ ...result, deduplicated: false });
  }),
];
