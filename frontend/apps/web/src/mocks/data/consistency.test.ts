import { describe, expect, it } from "vitest";
import { auditLogs } from "./audit";
import { adapters } from "./adapters";
import { evidence } from "./evidence";
import { events } from "./events";
import { exceptions } from "./ebms";
import { health } from "./health";
import { objects } from "./objects";
import { qualityReport } from "./quality";
import { platformUsers, tenantMembers, tenantRows } from "./tenants";
import { CASE_ORDER_B, EVT_ORDER_I_DQ } from "./ids";

const objectIds = new Set(objects.map((o) => o.object_id));
const eventIds = new Set(events.map((e) => e.event_id));

describe("fixtures 跨页一致性（spec §4）", () => {
  it("events.object_id ⊆ objects", () => {
    const dangling = events.filter((e) => !objectIds.has(e.object_id));
    expect(dangling).toEqual([]);
  });

  it("evidence.object_id ⊆ objects；链 ref 的 OBJECT 指向存在对象、CASE 指向已知案例", () => {
    for (const e of evidence) {
      expect(objectIds.has(e.object_id)).toBe(true);
      for (const link of e.links ?? []) {
        if (link.ref_type === "OBJECT") expect(objectIds.has(link.ref_id)).toBe(true);
        if (link.ref_type === "CASE") expect(link.ref_id).toBe(CASE_ORDER_B);
      }
    }
  });

  it("exceptions.event_id ⊆ events；每条异常的对象存在", () => {
    for (const item of exceptions) {
      expect(eventIds.has(item.event_id)).toBe(true);
      expect(objectIds.has(item.object_id)).toBe(true);
    }
  });

  it("订单 B 案例链上证据 = 4 份（订单/库存/PO/交期）", () => {
    const chain = evidence.filter((e) => (e.links ?? []).some((l) => l.ref_type === "CASE" && l.ref_id === CASE_ORDER_B));
    expect(chain).toHaveLength(4);
  });

  it("风险等级分布：P0×1、P1×3、P2×4（异常表）；四档在事件流均有样本", () => {
    const count = (lv: string) => exceptions.filter((e) => e.risk_level === lv).length;
    expect(count("P0")).toBe(1);
    expect(count("P1")).toBe(3);
    expect(count("P2")).toBe(4);
    for (const lv of ["P0", "P1", "P2", "P3"]) {
      expect(events.some((e) => e.risk_level === lv)).toBe(true);
    }
  });

  it("health.ops_metrics.evidence_count = evidence.length", () => {
    expect(health.ops_metrics?.evidence_count).toBe(evidence.length);
  });

  it("quality.kpi 与异常表一致：pending=OPEN 数、high=P0/P1 数", () => {
    const openCount = exceptions.filter((e) => e.event_id !== EVT_ORDER_I_DQ).length;
    const highCount = exceptions.filter((e) => e.risk_level === "P0" || e.risk_level === "P1").length;
    expect(qualityReport.kpi.pending_exceptions).toBe(openCount);
    expect(qualityReport.kpi.high_priority).toBe(highCount);
  });

  it("适配器 5 个且 plm 降级（呼应场景 10 与 adapters KPI）", () => {
    expect(adapters).toHaveLength(5);
    expect(adapters.find((a) => a.adapter === "plm")?.health).toBe("DEGRADED");
  });

  it("audit 含 2 条 GUARD_DENIED 且事件流存在场景 10（adapter.sync.failed）", () => {
    expect(auditLogs.filter((a) => a.action === "GUARD_DENIED")).toHaveLength(2);
    expect(events.some((e) => e.event_type === "adapter.sync.failed")).toBe(true);
  });

  it("对象类型覆盖：ORDER/CUSTOMER/MATERIAL/PRODUCT/SUPPLIER/PURCHASE_ORDER/PROJECT 齐备", () => {
    const types = new Set(objects.map((o) => o.object_type));
    for (const t of ["ORDER", "CUSTOMER", "MATERIAL", "PRODUCT", "SUPPLIER", "PURCHASE_ORDER", "PROJECT"]) {
      expect(types.has(t)).toBe(true);
    }
  });

  it("租户 fixtures：≥8 且三状态覆盖；slug 全局唯一", () => {
    expect(tenantRows.length).toBeGreaterThanOrEqual(8);
    for (const s of ["ACTIVE", "SUSPENDED", "CANCELLED"]) {
      expect(tenantRows.some((t) => t.status === s)).toBe(true);
    }
    expect(new Set(tenantRows.map((t) => t.slug)).size).toBe(tenantRows.length);
  });

  it("租户成员：user_id ⊆ 平台用户目录；每个租户至少一名 ACTIVE ADMIN", () => {
    const userIds = new Set(platformUsers.map((u) => u.user_id));
    for (const tenant of tenantRows) {
      const members = tenantMembers[tenant.tenant_id] ?? [];
      expect(members.length).toBeGreaterThan(0);
      for (const m of members) expect(userIds.has(m.user_id)).toBe(true);
      expect(members.some((m) => m.member_roles.includes("ADMIN") && m.status === "ACTIVE")).toBe(true);
    }
  });
});
