import { apiClient } from "../../../features/auth/api";
import type { EventResponse, EvidenceRecord, ObjectResponse, Page } from "../../../mocks/types";

const BASE = "/api/v1";

/**
 * 风险抽屉按需取数（W4 EDP-403 自 features/overview 泛化提升）：
 * eventId 必填驱动——事件详情 → 受影响对象 → 对象事件/证据 联动（总览/案例详情共用）。
 */
export const riskDrawerApi = {
  event: (eventId: string): Promise<EventResponse> =>
    apiClient.get<EventResponse>(`${BASE}/events/${eventId}`),
  objectDetail: (objectId: string): Promise<ObjectResponse> =>
    apiClient.get<ObjectResponse>(`${BASE}/objects/${objectId}`),
  objectEvents: (objectId: string): Promise<Page<EventResponse>> =>
    apiClient.get<Page<EventResponse>>(
      `${BASE}/events?object_id=${encodeURIComponent(objectId)}&limit=4`,
    ),
  objectEvidence: (objectId: string): Promise<Page<EvidenceRecord>> =>
    apiClient.get<Page<EvidenceRecord>>(
      `${BASE}/evidence?object_id=${encodeURIComponent(objectId)}&limit=5`,
    ),
};
