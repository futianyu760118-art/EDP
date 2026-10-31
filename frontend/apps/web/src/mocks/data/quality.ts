import type { QualityReport } from "../types";

/**
 * B.13 质量报告 fixtures（W5 T13 对齐后端 T3 派生口径）：
 * - dimensions 为四段标识（reconciliation/coverage/orphans/checksum，后端
 *   derive_dimensions 值域），label 用后端段名；
 * - kpi 派生对齐 service.derive_kpi：sla_pct=抽检通过率 100*(sampled-failed)/
 *   sampled（T3 裁定）、completeness_pct=coverage.overall_pct、overall=四维均分；
 * - pending=OPEN 异常数（7）、high=P0/P1 数（4），一致性测试断言。
 */
export const qualityReport: QualityReport = {
  date: "2026-09-28",
  reconciliation: [
    { source_system: "erp", object_type: "ORDER", source_count: 1200, edp_count: 1180, deviation_pct: 1.67, ok: true },
    { source_system: "erp", object_type: "INVENTORY", source_count: 860, edp_count: 858, deviation_pct: 0.23, ok: true },
    { source_system: "plm", object_type: "PROJECT", source_count: 42, edp_count: 41, deviation_pct: 2.38, ok: true },
    { source_system: "mdm", object_type: "CUSTOMER", source_count: 640, edp_count: 639, deviation_pct: 0.16, ok: true },
    { source_system: "real-crm", object_type: "CONTACT", source_count: null, edp_count: 12, deviation_pct: 0, ok: true },
  ],
  coverage: {
    overall_pct: 96.8,
    by_type: [
      { object_type: "ORDER", coverage_pct: 99.1 },
      { object_type: "CUSTOMER", coverage_pct: 97.6 },
      { object_type: "MATERIAL", coverage_pct: 98.2 },
      { object_type: "PRODUCT", coverage_pct: 96.5 },
      { object_type: "PURCHASE_ORDER", coverage_pct: 98.0 },
      { object_type: "PROJECT", coverage_pct: 94.9 },
    ],
  },
  orphans: { event_orphans: 0, evidence_orphans: 0 },
  // sla = 100*(120-1)/120 = 99.2（抽检通过率，T3 裁定口径）
  checksum_sampling: { sampled: 120, failed: 1 },
  // overall = (100.0+96.8+100.0+99.2)/4 = 99.0；completeness = coverage.overall
  kpi: { overall_pct: 99.0, sla_pct: 99.2, completeness_pct: 96.8, pending_exceptions: 7, high_priority: 4 },
  dimensions: [
    { domain: "reconciliation", label: "对账一致性", score_pct: 100.0 },
    { domain: "coverage", label: "对象覆盖率", score_pct: 96.8 },
    { domain: "orphans", label: "数据悬挂", score_pct: 100.0 },
    { domain: "checksum", label: "证据完整性", score_pct: 99.2 },
  ],
};

export const coverageReport = qualityReport.coverage;
