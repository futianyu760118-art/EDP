import { http, HttpResponse } from "msw";
import type { ObjectResponse } from "../types";
import { clampLimit, paginate } from "../lib/cursor";
import { errorOf } from "../lib/http";
import { scenarioResponse } from "../lib/scenario";
import { objects } from "../data/objects";
import { TENANT_ID } from "../data/ids";
import { msBefore } from "../lib/demo-time";

/** 写语义（spec §5.2）：会话内可变 Map，刷新即复位。 */
const store = new Map<string, ObjectResponse>(objects.map((o) => [o.object_id, { ...o }]));

function sortedAll(): ObjectResponse[] {
  return [...store.values()].sort((a, b) =>
    b.updated_at.localeCompare(a.updated_at) || b.object_id.localeCompare(a.object_id),
  );
}

interface UpsertBody {
  object_type?: string;
  owner_domain?: string;
  source_system?: string;
  source_id?: string;
  idempotency?: { expected_revision?: number | null };
  attributes?: Record<string, unknown>;
}

export const registryHandlers = [
  // B.2 GET /objects：组合键过滤 + 游标分页
  http.get("*/api/v1/objects", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const q = new URL(request.url).searchParams;
    const filtered = sortedAll().filter((o) => {
      if (q.get("object_type") && o.object_type !== q.get("object_type")) return false;
      if (q.get("source_system") && o.source_system !== q.get("source_system")) return false;
      if (q.get("source_id") && o.source_id !== q.get("source_id")) return false;
      if (q.get("owner_domain") && o.owner_domain !== q.get("owner_domain")) return false;
      if (q.get("status") && o.status !== q.get("status")) return false;
      return true;
    });
    return HttpResponse.json(paginate(filtered, clampLimit(q.get("limit")), q.get("cursor")));
  }),

  // B.2 GET /objects/{id}：跨租户/不存在统一 404
  http.get("*/api/v1/objects/:objectId", ({ params }) => {
    const found = store.get(String(params.objectId));
    if (!found) return errorOf("NOT_FOUND", "资源不存在", 404);
    return HttpResponse.json(found);
  }),

  // B.2 POST /objects：首次 201 / upsert 200（revision+1）；乐观锁 409 + current_revision
  http.post("*/api/v1/objects", async ({ request }) => {
    const body = (await request.json().catch(() => null)) as UpsertBody | null;
    if (!body?.object_type || !body.owner_domain || !body.source_system || !body.source_id) {
      return errorOf("VALIDATION_ERROR", "object_type/owner_domain/source_system/source_id 均为必填", 400);
    }
    const existing = sortedAll().find(
      (o) =>
        o.object_type === body.object_type &&
        o.source_system === body.source_system &&
        o.source_id === body.source_id,
    );
    const expected = body.idempotency?.expected_revision ?? null;
    if (existing && expected !== null && expected !== existing.revision) {
      return errorOf("CONFLICT", "版本冲突：对象已被修改", 409, { current_revision: existing.revision });
    }
    const now = msBefore(0);
    if (existing) {
      existing.revision += 1;
      existing.attributes = { ...(body.attributes ?? existing.attributes) };
      existing.updated_at = now;
      return HttpResponse.json({
        object_id: existing.object_id,
        revision: existing.revision,
        status: existing.status,
        created_at: existing.created_at,
      });
    }
    const object_id = crypto.randomUUID();
    const record: ObjectResponse = {
      object_id,
      tenant_id: TENANT_ID,
      object_type: body.object_type,
      owner_domain: body.owner_domain,
      source_system: body.source_system,
      source_id: body.source_id,
      revision: 1,
      status: "ACTIVE",
      merged_into: null,
      attributes: body.attributes ?? {},
      created_at: now,
      updated_at: now,
    };
    store.set(object_id, record);
    return HttpResponse.json({ object_id, revision: 1, status: "ACTIVE", created_at: now }, { status: 201 });
  }),

  // B.2 GET /objects/{id}/history：revision 轨迹（mock 按 revision 数生成）
  http.get("*/api/v1/objects/:objectId/history", ({ params }) => {
    const found = store.get(String(params.objectId));
    if (!found) return errorOf("NOT_FOUND", "资源不存在", 404);
    const revisions = Array.from({ length: found.revision }, (_, i) => ({
      revision: i + 1,
      action: "OBJECT_UPSERT",
      actor_id: `adapter:${found.source_system}`,
      occurred_at: msBefore((found.revision - i) * 6 * 60 * 60 * 1000),
    }));
    return HttpResponse.json({ object_id: found.object_id, revisions });
  }),
];
