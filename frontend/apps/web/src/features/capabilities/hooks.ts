import { useQuery } from "@tanstack/react-query";
import { capabilitiesApi, type CapabilityListItem } from "./api";

/**
 * 能力清单兜底常量（W5-13 收敛的单一硬编码点）：接口失败/加载中/空列表时
 * 三页筛选降级回演示三能力（UUID 与 MSW fixtures 同源，保证降级态筛选仍可用）。
 */
export const FALLBACK_CAPABILITIES: CapabilityListItem[] = [
  {
    capability_id: "00000000-0000-4000-8000-000000000801",
    name: "订单风险评估",
    domain: "delivery",
    risk_level: "L1",
    permission: "AUTO_ALLOWED",
    endpoint: null,
    owner: "supply-chain-team",
    status: "ACTIVE",
    created_at: "2026-09-01T08:00:00.000Z",
  },
  {
    capability_id: "00000000-0000-4000-8000-000000000802",
    name: "产品就绪度",
    domain: "product",
    risk_level: "L1",
    permission: "AUTO_ALLOWED",
    endpoint: null,
    owner: "planning-team",
    status: "ACTIVE",
    created_at: "2026-09-02T08:00:00.000Z",
  },
  {
    capability_id: "00000000-0000-4000-8000-000000000803",
    name: "数据质量检查",
    domain: "quality",
    risk_level: "L0",
    permission: "READ_ONLY",
    endpoint: null,
    owner: "data-platform-team",
    status: "ACTIVE",
    created_at: "2026-09-03T08:00:00.000Z",
  },
];

export interface CapabilityOption {
  value: string;
  label: string;
}

/**
 * 能力清单单点（W5-13 收敛）：traces/memory 筛选数据源统一拉 GET /capabilities。
 * 降级序列：接口真数据 → 失败/加载中/空列表回退 FALLBACK_CAPABILITIES（兜底硬编码）。
 */
export function useCapabilities() {
  const query = useQuery({
    queryKey: ["capabilities", "list"],
    queryFn: () => capabilitiesApi.list(),
    retry: 0,
    staleTime: 5 * 60 * 1000,
  });
  const items =
    query.data != null && query.data.items.length > 0 ? query.data.items : FALLBACK_CAPABILITIES;
  const options: CapabilityOption[] = items.map((c) => ({ value: c.capability_id, label: c.name }));
  // 降级信号（W6 跟进 D-15）：接口失败或空列表 → 消费页展示「内置清单」轻量提示
  // （加载中为瞬态，不标记——避免首帧闪烁）。
  const isFallback = query.isError || (query.data != null && query.data.items.length === 0);
  return { ...query, items, options, isFallback };
}
