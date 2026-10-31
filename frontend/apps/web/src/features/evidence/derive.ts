import type { EvidenceRecord } from "../../mocks/types";

/** verify 结果（本会话状态；列表无状态字段——未校验为中性）。 */
export type VerifyState = "unverified" | "pending" | "valid" | "invalid";

/**
 * 能力聚合类来源集合（Derived 回退判定用）：后端能力结果事件同事务落的
 * 结果证据 source_system="agent-hub"（demo dataset ResultEventSpec 缺省值）。
 */
const CAPABILITY_SOURCE_SYSTEMS = new Set(["agent-hub"]);

/** 证据类型：含 RESULT/CASE link 的结果证据为 Derived，其余 Primary（设计 13.6.2）。
 *  links 缺省（真模式列表简投影无 links，W3-06）时回退按 source_system 判定：
 *  能力聚合类来源（agent-hub，见 CAPABILITY_SOURCE_SYSTEMS）视为 Derived、
 *  其余（erp/plm 等源记录证据）视为 Primary。 */
export function evidenceKind(record: EvidenceRecord): "Primary" | "Derived" {
  if (record.links == null) {
    return CAPABILITY_SOURCE_SYSTEMS.has(record.source_system) ? "Derived" : "Primary";
  }
  const derived = record.links.some(
    (link) => link.ref_type === "RESULT" || link.ref_type === "CASE",
  );
  return derived ? "Derived" : "Primary";
}

/** snapshot 摘要（列表简投影无 snapshot 时返回 undefined；MSW 有）。 */
export function summarizeSnapshot(record: EvidenceRecord): string | undefined {
  if (record.snapshot == null) return undefined;
  const parts = Object.entries(record.snapshot)
    .filter(([, value]) => value != null && typeof value !== "object")
    .slice(0, 3)
    .map(([key, value]) => `${key}=${String(value)}`);
  return parts.length > 0 ? parts.join(" · ") : undefined;
}

/** 列表/链图共用的时间展示（MM-DD HH:mm）。 */
export function fmtTime(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
