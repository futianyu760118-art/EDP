import { http, HttpResponse } from "msw";
import { errorOf } from "../lib/http";
import { scenarioResponse } from "../lib/scenario";
import { hoursBefore, minutesBefore } from "../lib/demo-time";
import { mockUuid } from "../data/ids";
import type { Schemas } from "../types";

/**
 * W6 EDP-601 全局搜索 GET /api/v1/search：命中/空结果两 fixture（形状按
 * T4 regen 的 SearchResponse/ObjectHit/EventHit/EvidenceHit 简投影）。
 * 匹配语义：q（trim 后空 → 400 VALIDATION_ERROR）对各组业务字段做大小写
 * 不敏感子串匹配；无任何命中即三组全空（total=0，驱动空态三件套）。
 */

type ObjectHit = Schemas["ObjectHit"];
type EventHit = Schemas["EventHit"];
type EvidenceHit = Schemas["EvidenceHit"];

const OBJECT_HITS: ObjectHit[] = [
  {
    object_id: mockUuid(101),
    object_type: "sales_order",
    source_id: "SO-2026-00123",
    updated_at: minutesBefore(12),
  },
  {
    object_id: mockUuid(331),
    object_type: "purchase_order",
    source_id: "PO-2026-00771",
    updated_at: hoursBefore(3),
  },
  {
    object_id: mockUuid(201),
    object_type: "customer",
    source_id: "CUST-1024",
    updated_at: hoursBefore(26),
  },
];

const EVENT_HITS: EventHit[] = [
  {
    event_id: mockUuid(402),
    event_type: "capability.result.order_risk",
    occurred_at: minutesBefore(18),
  },
  {
    event_id: mockUuid(501),
    event_type: "ORDER_SNAPSHOT",
    occurred_at: minutesBefore(42),
  },
];

const EVIDENCE_HITS: EvidenceHit[] = [
  {
    evidence_id: mockUuid(601),
    source_system: "erp",
    source_record_id: "ORDER-2026-0099",
    captured_at: minutesBefore(12),
  },
  {
    evidence_id: mockUuid(602),
    source_system: "mes",
    source_record_id: "ORDER-2026-0231",
    captured_at: hoursBefore(2),
  },
];

const lower = (s: string | undefined) => s?.toLowerCase() ?? "";

export const searchHandlers = [
  http.get("*/api/v1/search", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const q = (new URL(request.url).searchParams.get("q") ?? "").trim();
    if (!q) return errorOf("VALIDATION_ERROR", "q 至少 1 个字符", 400);
    const needle = q.toLowerCase();
    const objects = OBJECT_HITS.filter(
      (hit) => lower(hit.source_id).includes(needle) || lower(hit.object_type).includes(needle),
    );
    const events = EVENT_HITS.filter(
      (hit) => lower(hit.event_type).includes(needle) || lower(hit.event_id).includes(needle),
    );
    const evidence = EVIDENCE_HITS.filter(
      (hit) =>
        lower(hit.source_system).includes(needle) ||
        lower(hit.source_record_id).includes(needle) ||
        lower(hit.evidence_id).includes(needle),
    );
    const total = objects.length + events.length + evidence.length;
    return HttpResponse.json({ objects, events, evidence, query: q, total });
  }),
];
