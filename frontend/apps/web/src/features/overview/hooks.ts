import { useQuery } from "@tanstack/react-query";
import { overviewApi } from "./api";

/** 总览数据源统一 30s 轮询、单次重试；失败由 PanelCard 面板级降级承接。 */
export const useCoverage = () =>
  useQuery({
    queryKey: ["overview", "coverage"],
    queryFn: overviewApi.coverage,
    refetchInterval: 30_000,
    retry: 1,
  });

export const useDeepHealth = () =>
  useQuery({
    queryKey: ["overview", "health"],
    queryFn: overviewApi.health,
    refetchInterval: 30_000,
    retry: 1,
  });

export const useAdapters = () =>
  useQuery({
    queryKey: ["overview", "adapters"],
    queryFn: overviewApi.adapters,
    refetchInterval: 30_000,
    retry: 1,
  });

/** 三栏「数据健康」子指标（SLA/完整性/孤儿事件）取全量质量报告（coverage 端点无 kpi/orphans）。 */
export const useQualityReport = () =>
  useQuery({
    queryKey: ["overview", "quality"],
    queryFn: overviewApi.qualityReport,
    refetchInterval: 30_000,
    retry: 1,
  });

export const useTopExceptions = () =>
  useQuery({
    queryKey: ["overview", "exceptions"],
    queryFn: overviewApi.topExceptions,
    refetchInterval: 30_000,
    retry: 1,
  });

export const useRecentEvents = () =>
  useQuery({
    queryKey: ["overview", "events"],
    queryFn: overviewApi.recentEvents,
    refetchInterval: 30_000,
    retry: 1,
  });

export const useRecentAudit = () =>
  useQuery({
    queryKey: ["overview", "audit"],
    queryFn: overviewApi.recentAudit,
    refetchInterval: 30_000,
    retry: 1,
  });

export const useObjectsTotal = () =>
  useQuery({
    queryKey: ["overview", "objectsTotal"],
    queryFn: overviewApi.objectsTotal,
    refetchInterval: 30_000,
    retry: 1,
  });
