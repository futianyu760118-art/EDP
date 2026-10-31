import type { HealthResponse, OutboxStatus } from "../types";
import { hoursBefore, minutesBefore } from "../lib/demo-time";
import { evidence } from "./evidence";

/** B.13 示例 + mock 扩展（backup 备份卡 / ops_metrics 总览与事件流 KPI 带，spec §3.2）。
 *  idempotency_hit_rate 为 0~1 比值（真后端口径，渲染端 ×100）；其余扩展字段与 mock 扩展契约一致。 */
export const health: HealthResponse = {
  status: "OK",
  db: "OK",
  db_ha: { role: "primary", replication_lag_mb: 0.4, replicas: 1 },
  outbox_pending: 3,
  last_sync: {
    erp: minutesBefore(12),
    mes: minutesBefore(26),
    plm: hoursBefore(3),
    mdm: minutesBefore(40),
    crm: hoursBefore(1),
  },
  version: "2.0.0",
  backup: { last_full_at: hoursBefore(9), wal_archive_at: minutesBefore(4), last_restore_verify: "PASSED" },
  ops_metrics: {
    events_24h: 18421,
    ingest_peak_24h: 742,
    p95_latency_ms: 812,
    idempotency_hit_rate: 0.994,
    dlq: 6,
    audit_events_7d: 15230,
    policy_hits_today: 39,
    adapters_success_rate: 99.5,
    evidence_count: evidence.length,
    evidence_valid_rate: 100,
    object_coverage_pct: 96.8,
    evidence_access_24h: 42,
  },
};

export const outboxStatus: OutboxStatus = {
  pending: 3,
  failed: 0,
  oldest_pending_at: minutesBefore(18),
  published_last_hour: 1240,
};
