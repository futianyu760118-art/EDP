import type { EvidenceRecord } from "../types";
import { hoursBefore } from "../lib/demo-time";
import {
  CASE_ORDER_B, EVID_ORDER_A_SNAPSHOT, EVID_ORDER_B_INVENTORY, EVID_ORDER_B_LEADTIME, EVID_ORDER_B_PO,
  EVID_ORDER_B_SNAPSHOT, EVID_ORDER_C_PO_DELAY, EVID_ORDER_E_INVENTORY, EVID_ORDER_I_DUAL,
  EVID_PRJD_READINESS, EVID_S030_DISCONTINUE, OBJ_CUSTOMER_C030A, OBJ_MATERIAL_X100, OBJ_ORDER_A,
  OBJ_ORDER_B, OBJ_ORDER_C, OBJ_ORDER_E, OBJ_ORDER_G, OBJ_ORDER_H, OBJ_ORDER_I, OBJ_ORDER_J,
  OBJ_ORDER_R1, OBJ_ORDER_R2,
  OBJ_PO_00771, OBJ_PO_00785, OBJ_PRODUCT_PF, OBJ_PROJECT_PRJD, OBJ_SUPPLIER_S021, OBJ_SUPPLIER_S030,
  mockUuid,
} from "./ids";

/** 确定性伪 sha256（64 hex）：序号十六进制重复 16 次。展示层截断为 a4c1…9f3d 样式。 */
export function fakeChecksum(n: number): string {
  return `sha256:${n.toString(16).padStart(4, "0").repeat(16)}`;
}

/** 订单 B 证据链（M4 主线，Result→CASE→源记录，4 份）。 */
const orderBLinks = [
  { ref_type: "CASE", ref_id: CASE_ORDER_B },
  { ref_type: "OBJECT", ref_id: OBJ_ORDER_B },
];

/** 20 条证据：10 具名（场景链路）+ 10 常规快照。 */
export const evidence: EvidenceRecord[] = [
  { evidence_id: EVID_ORDER_B_SNAPSHOT, source_system: "erp", source_record_id: "SO-2026-00123#v7", object_id: OBJ_ORDER_B, checksum: fakeChecksum(0xa4c1), snapshot: { order_no: "SO-2026-00123", amount: 120000, delivery_date: "2026-10-15", customer: "C-008" }, captured_at: hoursBefore(5), links: orderBLinks },
  { evidence_id: EVID_ORDER_B_INVENTORY, source_system: "erp", source_record_id: "INV-X-100#20260927", object_id: OBJ_MATERIAL_X100, checksum: fakeChecksum(0x0259), snapshot: { material_code: "X-100", warehouses: [{ warehouse: "WH-01", available: 3200, reserved: 800 }], total_available: 3200 }, captured_at: hoursBefore(5), links: orderBLinks },
  { evidence_id: EVID_ORDER_B_PO, source_system: "erp", source_record_id: "PO-2026-00771", object_id: OBJ_PO_00771, checksum: fakeChecksum(0x77d2), snapshot: { po_no: "PO-2026-00771", supplier_code: "S-021", quantity: 2000, expected_date: "2026-10-20", status: "在途" }, captured_at: hoursBefore(5), links: orderBLinks },
  { evidence_id: EVID_ORDER_B_LEADTIME, source_system: "erp", source_record_id: "SLT-S-021", object_id: OBJ_SUPPLIER_S021, checksum: fakeChecksum(0x9f3d), snapshot: { supplier_code: "S-021", material_code: "X-100", lead_time_days: 10 }, captured_at: hoursBefore(5), links: orderBLinks },
  { evidence_id: EVID_ORDER_C_PO_DELAY, source_system: "erp", source_record_id: "PO-2026-00785#delay", object_id: OBJ_PO_00785, checksum: fakeChecksum(0x31e8), snapshot: { po_no: "PO-2026-00785", expected_date_old: "2026-09-30", expected_date_new: "2026-10-12", supplier_code: "S-118" }, captured_at: hoursBefore(20), links: [{ ref_type: "OBJECT", ref_id: OBJ_ORDER_C }] },
  { evidence_id: EVID_PRJD_READINESS, source_system: "plm", source_record_id: "PRJ-D#readiness", object_id: OBJ_PROJECT_PRJD, checksum: fakeChecksum(0x55b0), snapshot: { project: "PRJ-D", status: "验证中", blocking: "完成验证与测试", readiness: "未达产" }, captured_at: hoursBefore(32), links: [{ ref_type: "OBJECT", ref_id: OBJ_PROJECT_PRJD }] },
  { evidence_id: EVID_ORDER_E_INVENTORY, source_system: "erp", source_record_id: "INV-P-F#20260927", object_id: OBJ_PRODUCT_PF, checksum: fakeChecksum(0xc2a7), snapshot: { product_code: "P-F", available: 38, note: "仅剩少量库存" }, captured_at: hoursBefore(8), links: [{ ref_type: "OBJECT", ref_id: OBJ_ORDER_E }] },
  { evidence_id: EVID_ORDER_I_DUAL, source_system: "erp", source_record_id: "C-030#compare", object_id: OBJ_CUSTOMER_C030A, checksum: fakeChecksum(0x18f6), snapshot: { records: ["C-030", "C-030-B"], field: "客户名称", conflict: true }, captured_at: hoursBefore(44), links: [{ ref_type: "OBJECT", ref_id: OBJ_ORDER_I }] },
  { evidence_id: EVID_S030_DISCONTINUE, source_system: "erp", source_record_id: "S-030#notice", object_id: OBJ_SUPPLIER_S030, checksum: fakeChecksum(0x64d9), snapshot: { supplier_code: "S-030", discontinuation: true, effective_date: "2026-11-01" }, captured_at: hoursBefore(12), links: [{ ref_type: "OBJECT", ref_id: OBJ_ORDER_J }] },
  { evidence_id: EVID_ORDER_A_SNAPSHOT, source_system: "erp", source_record_id: "SO-2026-00122#v1", object_id: OBJ_ORDER_A, checksum: fakeChecksum(0x22aa), snapshot: { order_no: "SO-2026-00122", amount: 86000, status: "已确认" }, captured_at: hoursBefore(26), links: [{ ref_type: "OBJECT", ref_id: OBJ_ORDER_A }] },
  ...[OBJ_ORDER_C, OBJ_ORDER_E, OBJ_ORDER_G, OBJ_ORDER_H, OBJ_ORDER_I, OBJ_ORDER_J, OBJ_ORDER_B, OBJ_ORDER_A, OBJ_ORDER_R1, OBJ_ORDER_R2].map(
    (objectId, i) =>
      ({
        evidence_id: mockUuid(611 + i),
        source_system: "erp",
        source_record_id: `SNAPSHOT#routine-${i + 1}`,
        object_id: objectId,
        checksum: fakeChecksum(0x7000 + i),
        snapshot: { note: "例行快照", seq: i + 1 },
        captured_at: hoursBefore(10 + i * 3),
        links: [{ ref_type: "OBJECT", ref_id: objectId }],
      }) satisfies EvidenceRecord,
  ),
];

export function findEvidence(id: string): EvidenceRecord | undefined {
  return evidence.find((e) => e.evidence_id === id);
}
