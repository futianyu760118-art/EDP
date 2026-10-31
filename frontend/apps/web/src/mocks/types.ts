import type { components } from "@edp/api-sdk";

export type Schemas = components["schemas"];
export type ObjectResponse = Schemas["ObjectResponse"];
export type EventResponse = Schemas["EventResponse"];

/** 列表包裹：items/next_cursor 对齐 B.0 分页约定；total 随 T14 契约冻结（Page.total 可选，本轮仅 events 填充）——mock 始终填充。 */
export interface Page<T> {
  items: T[];
  next_cursor: string | null;
  total: number;
}

// ---------- 未冻结契约（后端 M2/M3 实现后以真实契约回归；出处标注见各注释） ----------

/** B.4 证据记录。links 用于 ?ref_type=&ref_id= 逆向追溯过滤（B.4 列表参数）。 */
export interface EvidenceLink {
  ref_type: string;
  ref_id: string;
}

export interface EvidenceRecord {
  evidence_id: string;
  source_system: string;
  source_record_id: string;
  object_id: string;
  checksum: string;
  snapshot: Record<string, unknown>;
  captured_at: string;
  links?: EvidenceLink[];
}

/** B.4 GET /evidence/{id}/verify 响应。 */
export interface EvidenceVerifyResponse {
  evidence_id: string;
  valid: boolean;
  verified_at: string;
}

/** B.9 GET /ebms/exceptions 列表项。 */
export interface ExceptionItem {
  event_id: string;
  result_type: string;
  risk_level: string;
  object_id: string;
  order_no: string;
  summary: string;
  occurred_at: string;
  case_id: string | null;
}

/** B.13 GET /admin/quality/reports（契约已冻结，直接引 SDK 生成类型）。 */
export type ReconciliationRow = Schemas["ReconciliationRow"];
export type QualityReport = Schemas["QualityReport"];

/** B.13 GET /api/v1/health；backup 与 ops_metrics 为 mock 扩展（备份卡/总览与事件流 KPI 带，spec §3.2/§5.2）。
 *  db_ha 仅 ?deep=true 返回（真实模式缺省）；ops_metrics 前 6 字段为真实子集，后 4 字段为 mock 扩展（真 API 缺省 → 字段级兜底）。 */
export interface HealthResponse {
  status: string;
  db: string;
  db_ha?: { role: string; replication_lag_mb: number; replicas: number };
  outbox_pending: number;
  last_sync: Record<string, string>;
  version: string;
  backup?: { last_full_at: string; wal_archive_at: string; last_restore_verify: string };
  ops_metrics?: {
    events_24h: number;
    ingest_peak_24h: number;
    p95_latency_ms: number;
    /** 0~1 比值（真后端口径）；渲染端按 rate*100 转百分数。 */
    idempotency_hit_rate: number;
    dlq: number;
    evidence_count: number;
    audit_events_7d?: number;
    policy_hits_today?: number;
    adapters_success_rate?: number;
    evidence_valid_rate?: number;
    /** mock 扩展：对象覆盖率（%）；真实后端 W5 质量报表交付。 */
    object_coverage_pct?: number;
    /** mock 扩展：过去 24 小时证据原文访问次数；真实后端 W5 计量接入。 */
    evidence_access_24h?: number;
  };
}

/** B.13 GET /admin/outbox/status。 */
export interface OutboxStatus {
  pending: number;
  failed: number;
  oldest_pending_at: string | null;
  published_last_hour: number;
}

/** B.12 适配器清单/状态（13.6 适配器页与总览 KPI 用）。 */
export interface AdapterSummary {
  adapter: string;
  mode: string;
  access: string;
  team: string;
  last_sync: string;
  health: string;
  health_pct: number;
  status: string;
  isolation: string;
}

export interface AdapterSyncResponse {
  sync_id: string;
  status: string;
  started_at: string;
}

/** B.6 审计条目。 */
export interface AuditLogItem {
  audit_id: number;
  occurred_at: string;
  actor_type: string;
  actor_id: string;
  action: string;
  resource_type: string;
  resource_id: string;
  detail: Record<string, unknown>;
}

// W4 EDP-032 审计策略（契约已冻结，直接引 SDK 生成类型）
export type PolicyItem = Schemas["PolicyItem"];
export type PolicyCreateRequest = Schemas["PolicyCreateRequest"];
export type PolicyUpdateRequest = Schemas["PolicyUpdateRequest"];

/** B.13 任务轨道：GET /admin/quality/tasks/{id} 响应（SDK QualityTaskOut——recheck/reindex 轮询共用）。 */
export type QualityTask = Schemas["QualityTaskOut"];
