import { apiClient } from "../auth/api";
import type { Schemas } from "../../mocks/types";

export type SearchResponse = Schemas["SearchResponse"];
export type ObjectHit = Schemas["ObjectHit"];
export type EventHit = Schemas["EventHit"];
export type EvidenceHit = Schemas["EvidenceHit"];

/** 每组返回上限（契约 GET /search?q=&limit=）。 */
export const SEARCH_GROUP_LIMIT = 5;

export const searchApi = {
  /** GET /api/v1/search：三组命中 + total（B.0 冻结契约，T4 已 regen）。 */
  global: (q: string, limit = SEARCH_GROUP_LIMIT): Promise<SearchResponse> =>
    apiClient.get<SearchResponse>(`/api/v1/search?q=${encodeURIComponent(q)}&limit=${limit}`),
};
