import { apiClient } from "../auth/api";
import type { Schemas } from "../../mocks/types";

const BASE = "/api/v1";

// SDK 生成类型单点（W3R 契约冻结：B.7 能力注册）
export type CapabilityListItem = Schemas["CapabilityListItem"];
export type CapabilitiesPage = Schemas["Page_CapabilityListItem_"];

/** 筛选下拉一次取全量（演示量级 ≤100，真实量级增长后改搜索式）。 */
export const CAPABILITIES_PAGE_LIMIT = 100;

export interface CapabilityListParams {
  domain?: string;
  status?: string;
}

export const capabilitiesApi = {
  list: (params: CapabilityListParams = {}): Promise<CapabilitiesPage> => {
    const q = new URLSearchParams();
    if (params.domain) q.set("domain", params.domain);
    if (params.status) q.set("status", params.status);
    q.set("limit", String(CAPABILITIES_PAGE_LIMIT));
    return apiClient.get<CapabilitiesPage>(`${BASE}/capabilities?${q.toString()}`);
  },
};
