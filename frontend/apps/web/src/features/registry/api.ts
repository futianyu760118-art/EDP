import { apiClient } from "../auth/api";
import type { EventResponse, ObjectResponse, Page } from "../../mocks/types";

const BASE = "/api/v1";

/** 列表页大小：与 RegistryPage 分页区间计算共用。 */
export const OBJECTS_PAGE_LIMIT = 20;

export interface ObjectListParams {
  object_type?: string;
  owner_domain?: string;
  source_id?: string;
  limit?: number;
  cursor?: string | null;
}

export type ObjectsPage = Page<ObjectResponse>;

/** POST /objects 请求体（ObjectUpsertRequest，B.2）。 */
export interface ObjectCreateBody {
  object_type: string;
  owner_domain: string;
  source_system: string;
  source_id: string;
  attributes: {
    name: string;
    owner?: string;
    description?: string;
    sources: string[];
    [key: string]: unknown;
  };
}

/** POST /objects 响应（ObjectCreatedResponse，201/200 共用）。 */
export interface ObjectCreatedResult {
  object_id: string;
  revision: number;
  status: string;
  created_at: string;
}

/** GET /objects/{id}/history 单条 revision 轨迹。 */
export interface ObjectRevision {
  revision: number;
  action: string;
  actor_id: string;
  occurred_at: string;
}

export interface ObjectHistoryResponse {
  object_id: string;
  revisions: ObjectRevision[];
}

/**
 * 派生状态索引源事件类型。计划写 ORDER_RISK/DATA_QUALITY，但那是 B.3 的
 * result_type；MSW /events 仅支持 event_type 精确匹配，fixtures 的能力结果
 * 事件 event_type 为 capability.result.*，故按真实 event_type 取（三类风险
 * 能力 + DQ 检查）。
 */
const RISK_EVENT_TYPES = [
  "capability.result.order_risk",
  "capability.result.order_quality",
  "capability.result.product_readiness",
];
const DQ_EVENT_TYPE = "capability.result.dq_check";

export const objectsApi = {
  list: (params: ObjectListParams = {}): Promise<ObjectsPage> => {
    const q = new URLSearchParams();
    if (params.object_type) q.set("object_type", params.object_type);
    if (params.owner_domain) q.set("owner_domain", params.owner_domain);
    if (params.source_id) q.set("source_id", params.source_id);
    q.set("limit", String(params.limit ?? OBJECTS_PAGE_LIMIT));
    if (params.cursor) q.set("cursor", params.cursor);
    return apiClient.get<ObjectsPage>(`${BASE}/objects?${q.toString()}`);
  },
  /** 风险索引：limit=100 覆盖 fixtures 全量能力结果事件（三类合并）。 */
  riskIndexEvents: (): Promise<EventResponse[]> =>
    Promise.all(
      RISK_EVENT_TYPES.map((t) =>
        apiClient.get<Page<EventResponse>>(
          `${BASE}/events?event_type=${encodeURIComponent(t)}&limit=100`,
        ),
      ),
    ).then((pages) => pages.flatMap((p) => p.items)),
  /** DQ 索引：DATA_QUALITY 异常事件（result_type 复核见 hooks select）。 */
  dqIndexEvents: (): Promise<Page<EventResponse>> =>
    apiClient.get<Page<EventResponse>>(
      `${BASE}/events?event_type=${encodeURIComponent(DQ_EVENT_TYPE)}&limit=100`,
    ),
  /** POST /objects（B.2 upsert；新建弹窗走 201 分支）。 */
  create: (body: ObjectCreateBody): Promise<ObjectCreatedResult> =>
    apiClient.post(`${BASE}/objects`, body),
  /** GET /objects/{id}/history：revision 轨迹（mock 按 revision 数生成）。 */
  history: (objectId: string): Promise<ObjectHistoryResponse> =>
    apiClient.get(`${BASE}/objects/${objectId}/history`),
};
