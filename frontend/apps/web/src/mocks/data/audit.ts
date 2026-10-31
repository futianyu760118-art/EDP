import type { AuditLogItem, PolicyItem } from "../types";
import { daysBefore, hoursBefore, minutesBefore } from "../lib/demo-time";
import { CASE_ORDER_B, EVID_ORDER_A_SNAPSHOT, OBJ_ORDER_B, TENANT_ID, mockUuid } from "./ids";

/**
 * B.6 审计条目（14 条）：含 2 条 GUARD_DENIED（AI 越权可视化举证，总览审计动态用）
 * + 1 条 RATE_LIMITED + 1 条裸名 `records`（W3-13 前缀消歧演示——真实后端 aspect
 * 按表裸名存 resource_type）。
 */
export const auditLogs: AuditLogItem[] = [
  // 注意：最新 4 条（18m~2h）为总览审计动态锚定行（OverviewPage.test 前 4 断言），
  // W4 追加行一律排在 2h 之后，避免扰动总览叙事顺序
  { audit_id: 10232, occurred_at: hoursBefore(2.5), actor_type: "SERVICE", actor_id: "service:report-exporter", action: "RATE_LIMITED", resource_type: "ratelimit", resource_id: "", detail: { retry_after: 12, limit_per_min: 600, path: "/api/v1/evidence" } },
  { audit_id: 10233, occurred_at: hoursBefore(2.8), actor_type: "SERVICE", actor_id: "adapter:erp", action: "EVIDENCE_CREATE", resource_type: "records", resource_id: EVID_ORDER_A_SNAPSHOT, detail: { after: { source_system: "erp", checksum: "9f2c31ab" } } },
  { audit_id: 10231, occurred_at: minutesBefore(18), actor_type: "SERVICE", actor_id: "adapter:plm", action: "ADAPTER_SYNC_FAILED", resource_type: "adapters.sync", resource_id: "plm", detail: { reason: "UPSTREAM_UNAVAILABLE" } },
  { audit_id: 10230, occurred_at: minutesBefore(35), actor_type: "AI", actor_id: "agent:delivery-order-risk", action: "GUARD_DENIED", resource_type: "decision.records", resource_id: CASE_ORDER_B, detail: { reason: "Human-Only 操作，AI principal 被拒" } },
  { audit_id: 10229, occurred_at: minutesBefore(48), actor_type: "SERVICE", actor_id: "service:legacy-etl", action: "GUARD_DENIED", resource_type: "events.batch", resource_id: TENANT_ID, detail: { reason: "readonly scope Key 尝试写入" } },
  { audit_id: 10228, occurred_at: hoursBefore(2), actor_type: "SERVICE", actor_id: "adapter:erp", action: "OBJECT_UPSERT", resource_type: "registry.objects", resource_id: OBJ_ORDER_B, detail: { revision: 7 } },
  { audit_id: 10227, occurred_at: hoursBefore(4), actor_type: "AI", actor_id: "agent:delivery-order-risk", action: "CASE_CREATED", resource_type: "decision.cases", resource_id: CASE_ORDER_B, detail: { case_no: "DC-20260928-007" } },
  { audit_id: 10226, occurred_at: hoursBefore(5), actor_type: "HUMAN", actor_id: "user:manager1", action: "LOGIN", resource_type: "auth.session", resource_id: "manager1", detail: { ip: "10.8.0.12" } },
  { audit_id: 10225, occurred_at: hoursBefore(6), actor_type: "HUMAN", actor_id: "user:manager1", action: "EVIDENCE_VERIFY", resource_type: "evidence.records", resource_id: "批量抽检", detail: { sampled: 120, failed: 0 } },
  { audit_id: 10224, occurred_at: hoursBefore(8), actor_type: "SERVICE", actor_id: "adapter:erp", action: "EVENT_BATCH_INGEST", resource_type: "events.batch", resource_id: "批次#0928-0041", detail: { accepted: 4100, duplicated: 20 } },
  { audit_id: 10223, occurred_at: hoursBefore(26), actor_type: "HUMAN", actor_id: "user:analyst1", action: "EXPORT_REQUEST", resource_type: "audit.logs", resource_id: "audit-log-export", detail: { format: "csv", range: "7d" } },
  { audit_id: 10222, occurred_at: daysBefore(1.2), actor_type: "HUMAN", actor_id: "user:admin", action: "TOKEN_REFRESH", resource_type: "auth.session", resource_id: "admin", detail: {} },
  { audit_id: 10221, occurred_at: daysBefore(2), actor_type: "SERVICE", actor_id: "adapter:mdm", action: "OBJECT_UPSERT", resource_type: "registry.objects", resource_id: "C-008", detail: { revision: 2 } },
  { audit_id: 10220, occurred_at: daysBefore(3), actor_type: "HUMAN", actor_id: "user:manager1", action: "LOGIN", resource_type: "auth.session", resource_id: "manager1", detail: { ip: "10.8.0.12" } },
];

/** 策略 fixture id（测试启停/删除断言锚点）。 */
export const POLICY_EVIDENCE_EXPORT = mockUuid(941);
export const POLICY_DECISION_REVIEW = mockUuid(942);
export const POLICY_ACTION_TOGGLE = mockUuid(943);

/** EDP-032 审计策略（3 条：三维匹配数组空 = 通配语义演示）。 */
export const auditPolicies: PolicyItem[] = [
  {
    policy_id: POLICY_EVIDENCE_EXPORT,
    name: "证据导出管控",
    description: "证据原始快照受控导出，仅数据管理员可执行",
    resource_types: ["evidence.records"],
    actions: ["EVIDENCE_*"],
    actor_types: [],
    notify_channel: "站内消息 + 邮件",
    status: "ACTIVE",
    created_at: daysBefore(30),
    updated_at: daysBefore(2),
    created_by: "user:admin",
    updated_by: "user:admin",
  },
  {
    policy_id: POLICY_DECISION_REVIEW,
    name: "决策人工复核",
    description: "AI 提交决策记录命中即通知",
    resource_types: ["decision.records"],
    actions: ["DECISION_*"],
    actor_types: ["AI"],
    notify_channel: "仅站内消息",
    status: "ACTIVE",
    created_at: daysBefore(12),
    updated_at: daysBefore(12),
    created_by: "user:admin",
    updated_by: "user:admin",
  },
  {
    policy_id: POLICY_ACTION_TOGGLE,
    name: "行动状态流转监控",
    description: "服务账号流转行动状态需告警",
    resource_types: ["action.actions"],
    actions: ["ACTION_*"],
    actor_types: ["SERVICE"],
    notify_channel: "仅邮件",
    status: "DISABLED",
    created_at: daysBefore(6),
    updated_at: daysBefore(1),
    created_by: "user:admin",
    updated_by: "user:admin",
  },
];
