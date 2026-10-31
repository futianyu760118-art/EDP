/**
 * 审计词表（EDP-401）：action / resource_type → 中文展示的纯函数单点。
 * 事实来源（后端实测枚举，禁止凭空扩词）：
 * - `modules/audit/aspect.py`：ACTION_PREFIXES（OBJECT/EVENT/EVIDENCE/DECISION/
 *   CASE/ACTION/POLICY + 裸名回退）与 ORM 动词 CREATE/UPDATE/DELETE
 *   （`{PREFIX}_{VERB}`）；
 * - 显式补点常量：ratelimit.py `RATE_LIMITED`/`RATE_LIMIT_WARNING`、
 *   decisions/actions/memories/tools `GUARD_DENIED`、evidence
 *   `EVIDENCE_VERIFY_FAILED`、traces `TRACE_CREATE`、events/ingest `EVENT_CREATE`；
 * - resource_type 裸名 → schema 全名歧义（W3-13/W3R-03）：aspect 按表裸名存
 *   resource_type，`records` 裸名同指 evidence.records / decision.records，
 *   依 action 前缀 EVIDENCE_* / DECISION_*|CASE_* 消歧（裸名回退 EVIDENCE）；
 * - ADAPTER/TOKEN/EXPORT 为预留前缀（后端暂无对应审计枚举，W5+ 端点启用）；
 * - QUALITY 亦为预留前缀（W4 终审 Minor）：复合动词对齐后端质量事件
 *   event_type 实测常量（quality.service / evidence.service）——
 *   quality.checksum_failed / recheck_succeeded / recheck_failed /
 *   reindex_mismatch / reindex_succeeded / reindex_failed 的大写下划线
 *   形态（后端现落事件表、未以 QUALITY_* 落审计 action，预留 W5+ 兜底）。
 */

/** 显式常量全集（record_explicit 实测枚举 + 登录会话演示动作）。 */
export const ACTION_LABELS: Record<string, string> = {
  RATE_LIMITED: "限流拒绝",
  RATE_LIMIT_WARNING: "限流预警",
  GUARD_DENIED: "越权拦截",
  EVIDENCE_VERIFY_FAILED: "证据校验失败",
  TRACE_CREATE: "链路创建",
  EVENT_CREATE: "事件创建",
  LOGIN: "登录",
};

/** `{PREFIX}_{VERB}` 前缀字典（aspect.ACTION_PREFIXES 的中文侧）。 */
export const ACTION_PREFIX_LABELS: Record<string, string> = {
  OBJECT: "对象",
  EVENT: "事件",
  EVIDENCE: "证据",
  DECISION: "决策",
  CASE: "案例",
  ACTION: "行动",
  POLICY: "策略",
  ADAPTER: "适配器",
  TOKEN: "令牌",
  EXPORT: "导出",
  QUALITY: "质量",
};

/** 动词 / 复合动词字典（派生规则后半段，未命中走原文回退）。 */
export const ACTION_VERB_LABELS: Record<string, string> = {
  CREATE: "创建",
  CREATED: "创建",
  UPDATE: "更新",
  UPDATED: "更新",
  DELETE: "删除",
  DELETED: "删除",
  UPSERT: "写入",
  REFRESH: "刷新",
  VERIFY: "校验",
  BATCH_INGEST: "批量写入",
  SYNC_FAILED: "同步失败",
  // QUALITY_* 复合动词（后端质量事件 event_type 实测：quality.checksum_failed 等）
  CHECKSUM_FAILED: "校验和失败",
  RECHECK_SUCCEEDED: "复检成功",
  RECHECK_FAILED: "复检失败",
  REINDEX_MISMATCH: "重索引失配",
  REINDEX_SUCCEEDED: "重索引成功",
  REINDEX_FAILED: "重索引失败",
};

/** action → 中文：显式常量优先，其次前缀+动词派生，未命中回退原文。 */
export function deriveActionLabel(action: string): string {
  const explicit = ACTION_LABELS[action];
  if (explicit != null) return explicit;
  const idx = action.indexOf("_");
  if (idx > 0) {
    const prefix = ACTION_PREFIX_LABELS[action.slice(0, idx)] ?? undefined;
    const verb = ACTION_VERB_LABELS[action.slice(idx + 1)] ?? undefined;
    if (prefix != null && verb != null) return `${prefix}${verb}`;
  }
  return action;
}

/** 裸表名 → schema 全名（无 schema 前缀的表形态；`records` 歧义另走消歧函数）。 */
export const RESOURCE_LABELS: Record<string, string> = {
  events: "event.events",
  business_objects: "master.business_objects",
  cases: "decision.cases",
  actions: "action.actions",
  memories: "memory.memories",
  audit_logs: "platform.audit_logs",
};

/**
 * resource_type 展示归一（W3-13 收口）：含 `.` 的 fullname 原样；
 * `records` 裸名按 action 前缀消歧（EVIDENCE_ 前缀 → evidence.records，
 * DECISION_ 或 CASE_ 前缀 → decision.records，缺省回退 EVIDENCE——与 aspect
 * 裸名回退一致）；其余裸名查 RESOURCE_LABELS，未命中原样返回。
 */
export function resolveResourceType(resourceType: string, action?: string): string {
  if (resourceType.includes(".")) return resourceType;
  if (resourceType === "records") {
    if (action != null && (action.startsWith("DECISION_") || action.startsWith("CASE_"))) {
      return "decision.records";
    }
    return "evidence.records";
  }
  return RESOURCE_LABELS[resourceType] ?? resourceType;
}

export type AuditSeverity = "success" | "warning" | "error";

/** 级别判定（第 7 列 pill + GUARD_DENIED 行高亮共用）。 */
const ACTION_SEVERITY: Record<string, AuditSeverity> = {
  GUARD_DENIED: "error",
  RATE_LIMITED: "error",
  EVIDENCE_VERIFY_FAILED: "error",
  RATE_LIMIT_WARNING: "warning",
  ADAPTER_SYNC_FAILED: "warning",
};

export function severityOfAction(action: string): AuditSeverity {
  return ACTION_SEVERITY[action] ?? "success";
}

/** 级别 pill 文案（对齐原型「结果」列：成功/预警/拒绝）。 */
export const SEVERITY_LABELS: Record<AuditSeverity, string> = {
  success: "成功",
  warning: "预警",
  error: "拒绝",
};

/** actor_type → pill 色调（HUMAN 绿 / AI 橙 / SERVICE 蓝）。 */
export const ACTOR_TYPE_TONES: Record<string, "success" | "warning" | "info" | "muted"> = {
  HUMAN: "success",
  AI: "warning",
  SERVICE: "info",
};

export const ACTOR_TYPE_LABELS: Record<string, string> = {
  HUMAN: "人工",
  AI: "AI",
  SERVICE: "服务",
};

/** actor_id 缩写展示：剥离 user:/agent:/adapter:/service: 前缀（title 携全量）。 */
export function shortActorId(actorId: string): string {
  const idx = actorId.indexOf(":");
  return idx > 0 ? actorId.slice(idx + 1) : actorId;
}
