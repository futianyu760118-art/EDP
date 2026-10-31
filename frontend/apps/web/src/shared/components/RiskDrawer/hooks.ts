import { useQuery } from "@tanstack/react-query";
import { riskDrawerApi } from "./api";

/** 抽屉打开且 id 就绪时才发请求（无轮询）；失败单次重试。 */

export function useRiskEvent(eventId: string | null | undefined, open: boolean) {
  return useQuery({
    queryKey: ["risk-drawer", "event", eventId],
    queryFn: () => riskDrawerApi.event(eventId!),
    enabled: open && eventId != null,
    retry: 1,
  });
}

export function useRiskObject(objectId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ["risk-drawer", "object", objectId],
    queryFn: () => riskDrawerApi.objectDetail(objectId!),
    enabled: enabled && objectId != null,
    retry: 1,
  });
}

export function useRiskObjectEvents(objectId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ["risk-drawer", "object-events", objectId],
    queryFn: () => riskDrawerApi.objectEvents(objectId!),
    enabled: enabled && objectId != null,
    retry: 1,
  });
}

export function useRiskObjectEvidence(objectId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ["risk-drawer", "object-evidence", objectId],
    queryFn: () => riskDrawerApi.objectEvidence(objectId!),
    enabled: enabled && objectId != null,
    retry: 1,
  });
}
