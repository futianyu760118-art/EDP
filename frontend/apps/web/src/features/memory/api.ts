import { apiClient } from "../auth/api";
import type { Schemas } from "../../mocks/types";

const BASE = "/api/v1";

// SDK 生成类型单点（B.11 契约冻结）
export type MemoryListItem = Schemas["MemoryListItem"];
export type PageMemoryList = Schemas["Page_MemoryListItem_"];

/** 列表页大小（与 MemoryPage 分页区间计算共用）。 */
export const MEMORY_PAGE_LIMIT = 20;

/** 评审状态三值（B.11：创建即 CANDIDATE，APPROVED/REJECTED 为已评审终态）。 */
export type MemoryStatus = "CANDIDATE" | "APPROVED" | "REJECTED";

/** GET /memories 查询参数（status/capability_id + 游标）。 */
export interface MemoryListParams {
  status?: MemoryStatus;
  capability_id?: string;
  limit?: number;
  cursor?: string | null;
}

export const memoriesApi = {
  /** B.11 GET /memories（created_at DESC 游标分页）。 */
  list: (params: MemoryListParams = {}): Promise<PageMemoryList> => {
    const q = new URLSearchParams();
    if (params.status) q.set("status", params.status);
    if (params.capability_id) q.set("capability_id", params.capability_id);
    q.set("limit", String(params.limit ?? MEMORY_PAGE_LIMIT));
    if (params.cursor) q.set("cursor", params.cursor);
    return apiClient.get<PageMemoryList>(`${BASE}/memories?${q.toString()}`);
  },
};
