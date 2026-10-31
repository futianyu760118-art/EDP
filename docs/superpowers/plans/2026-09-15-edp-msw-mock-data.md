# EDP 控制台 MSW 模拟数据 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 EDP 控制台 W2+W3 六页交付完整 MSW 数据层（fixtures + 27 个 handler + 测试），数据故事对齐 AEOS §10 十类评估场景。

**Architecture:** `apps/web/src/mocks/` 下分层：`data/`（纯常量 fixtures，固定 UUID + DEMO_NOW 时间锚）→ `handlers/`（按域拆分，游标分页/筛选/写语义/场景注入）→ `handlers.ts` 聚合。browser worker 与 vitest node server 共用同一组 handler。

**Tech Stack:** MSW 2.6、TypeScript（strict）、Vitest（jsdom）、现有 `@edp/api-sdk` 生成类型。

**Spec:** `docs/superpowers/specs/2026-09-15-edp-msw-mock-data-design.md`（端点清单、数据故事、一致性约束以此为准）。

## Global Constraints

- 不改动 `contracts/` 冻结物、后端代码、`browser.ts`/`server.ts`/`msw-setup.ts`；
- 已冻结契约接口的响应形状必须对齐 `@edp/api-sdk` 生成类型（`ObjectResponse`/`EventResponse` 等）；未冻结接口类型定义在 `mocks/types.ts` 并逐个标注 B.x 出处；
- 全部数据确定性：禁止随机数与 `Date.now()`；日期一律由 `DEMO_NOW = 2026-09-28T08:30:00Z` 相对偏移；UUID 一律 `mockUuid(n)`（`crypto.randomUUID` 仅用于 POST 新建对象这一处）；
- 固定 UUID 序号段：对象 101~399、事件 400~411（具名）/500~599（生成）、证据 601~620、案例 901、sync 910；
- 列表响应包裹 `{items, next_cursor, total}`——`total` 为 mock 扩展字段（契约偏差，spec §5.2）；
- 风险等级只用 P0/P1/P2/P3（L 系映射：L3→P1、L2→P2、L1→P3，见 shared enums）；
- 错误响应结构：`{"error":{code, message, request_id}}`（附录 B.0）；
- 每个 task 完成即跑验证命令并 commit（风格 `feat(w2):`/`test(w2):`/`refactor(w2):`；只 add 本 task 涉及文件，工作区有他人未提交改动）；
- 不使用 `any`（eslint）；纯类型导入用 `import type`。

---

## Task 1: 基线验证

**做什么**：确认 frontend 现有测试全绿。工作区当前有与本工作无关的未提交改动（设计文档/Sidebar/permissions 等），不要碰、不要一起提交。

```powershell
cd frontend; pnpm -r test
```

**预期**：api-sdk、shared、web 三包 vitest 全部通过。若失败，停止并报告，不得继续。

## Task 2: lib 基础设施（cursor / demo-time / http / scenario）

**新建** `apps/web/src/mocks/lib/cursor.ts`：

```ts
/** 游标分页助手：cursor = base64("offset:N")（spec §5.2）。 */
export interface PageResult<T> {
  items: T[];
  next_cursor: string | null;
  /** mock 扩展：冻结契约 Page envelope 无 total；设计 13.7 模式 14 "共 N 条" 需要，后端落地后对齐。 */
  total: number;
}

export function encodeCursor(offset: number): string {
  return btoa(`offset:${offset}`);
}

export function decodeCursor(cursor: string | null | undefined): number {
  if (!cursor) return 0;
  try {
    const m = /^offset:(\d+)$/.exec(atob(cursor));
    return m ? Number(m[1]) : 0;
  } catch {
    return 0;
  }
}

export function clampLimit(raw: string | null, fallback = 20, max = 100): number {
  const n = Number(raw ?? fallback);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(Math.max(Math.trunc(n), 1), max);
}

export function paginate<T>(all: T[], limit: number, cursor: string | null): PageResult<T> {
  const offset = decodeCursor(cursor);
  const items = all.slice(offset, offset + limit);
  return {
    items,
    next_cursor: offset + limit < all.length ? encodeCursor(offset + limit) : null,
    total: all.length,
  };
}
```

**新建** `apps/web/src/mocks/lib/demo-time.ts`：

```ts
/** 演示时间锚（附录 B 示例日期）：全部 fixture 日期由锚相对偏移，保证可复现（spec §4）。 */
export const DEMO_NOW = new Date("2026-09-28T08:30:00.000Z");

const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

export function msBefore(ms: number): string {
  return new Date(DEMO_NOW.getTime() - ms).toISOString();
}

export const minutesBefore = (n: number): string => msBefore(n * MIN);
export const hoursBefore = (n: number): string => msBefore(n * HOUR);
export const daysBefore = (n: number): string => msBefore(n * DAY);
export const iso = (s: string): string => new Date(s).toISOString();
```

**新建** `apps/web/src/mocks/lib/http.ts`：

```ts
import { HttpResponse } from "msw";

/** 附录 B.0 错误结构。extra 用于 409 附 current_revision 等字段。 */
export function errorOf(
  code: string,
  message: string,
  status: number,
  extra?: Record<string, unknown>,
): HttpResponse {
  return HttpResponse.json(
    { error: { code, message, request_id: "mock-request-id", ...(extra ?? {}) } },
    { status },
  );
}
```

**新建** `apps/web/src/mocks/lib/scenario.ts`：

```ts
import { HttpResponse } from "msw";
import { errorOf } from "./http";

/** X-Mock-Scenario 注入（spec §5.2）：仅显式携带请求头时生效，驱动 EDP-201 拦截器链联调。 */
export function scenarioResponse(request: Request): HttpResponse | null {
  const s = request.headers.get("X-Mock-Scenario");
  if (!s) return null;
  if (s === "429") {
    return HttpResponse.json(
      { error: { code: "RATE_LIMITED", message: "请求过于频繁，请稍后重试", request_id: "mock-scenario" } },
      { status: 429, headers: { "Retry-After": "1" } },
    );
  }
  if (s === "503") {
    return errorOf("UPSTREAM_UNAVAILABLE", "源系统暂不可达，稍后重试", 503);
  }
  if (s === "suspended") {
    return errorOf("TENANT_SUSPENDED", "当前租户已暂停，请联系平台管理员", 403);
  }
  return null;
}
```

**新建** `apps/web/src/mocks/lib/cursor.test.ts`：

```ts
import { describe, expect, it } from "vitest";
import { clampLimit, decodeCursor, encodeCursor, paginate } from "./cursor";

describe("cursor", () => {
  it("encode/decode 往返", () => {
    expect(decodeCursor(encodeCursor(40))).toBe(40);
  });

  it("非法 cursor 归零", () => {
    expect(decodeCursor("!!!not-base64")).toBe(0);
    expect(decodeCursor(btoa("garbage"))).toBe(0);
    expect(decodeCursor(null)).toBe(0);
  });

  it("paginate 整页→有 next_cursor；末页→null", () => {
    const all = [1, 2, 3, 4, 5];
    const p1 = paginate(all, 2, null);
    expect(p1).toEqual({ items: [1, 2], next_cursor: encodeCursor(2), total: 5 });
    const p3 = paginate(all, 2, encodeCursor(4));
    expect(p3).toEqual({ items: [5], next_cursor: null, total: 5 });
  });

  it("offset 越界→空列表", () => {
    expect(paginate([1], 5, encodeCursor(9)).items).toEqual([]);
  });

  it("clampLimit 夹取 1..100，非法回退", () => {
    expect(clampLimit(null)).toBe(20);
    expect(clampLimit("0")).toBe(1);
    expect(clampLimit("500")).toBe(100);
    expect(clampLimit("abc")).toBe(20);
  });
});
```

**新建** `apps/web/src/mocks/lib/scenario.test.ts`：

```ts
import { describe, expect, it } from "vitest";
import { scenarioResponse } from "./scenario";

const req = (scenario: string | null): Request =>
  new Request("http://mock.test/api/v1/objects", {
    headers: scenario ? { "X-Mock-Scenario": scenario } : {},
  });

describe("scenarioResponse", () => {
  it("无头→null（正常路径零影响）", () => {
    expect(scenarioResponse(req(null))).toBeNull();
  });

  it("429 → RATE_LIMITED + Retry-After", async () => {
    const resp = scenarioResponse(req("429"))!;
    expect(resp.status).toBe(429);
    expect(resp.headers.get("Retry-After")).toBe("1");
    expect(await resp.json()).toMatchObject({ error: { code: "RATE_LIMITED" } });
  });

  it("503 → UPSTREAM_UNAVAILABLE", async () => {
    const resp = scenarioResponse(req("503"))!;
    expect(resp.status).toBe(503);
    expect(await resp.json()).toMatchObject({ error: { code: "UPSTREAM_UNAVAILABLE" } });
  });

  it("suspended → 403 TENANT_SUSPENDED", async () => {
    const resp = scenarioResponse(req("suspended"))!;
    expect(resp.status).toBe(403);
    expect(await resp.json()).toMatchObject({ error: { code: "TENANT_SUSPENDED" } });
  });
});
```

**验证**：

```powershell
cd frontend; pnpm --filter web test src/mocks/lib
```

**Commit**: `feat(w2): mocks lib 基础（游标/时间锚/场景注入/错误结构）`

## Task 3: 未冻结契约类型 types.ts

**新建** `apps/web/src/mocks/types.ts`：

```ts
import type { components } from "@edp/api-sdk";

export type Schemas = components["schemas"];
export type ObjectResponse = Schemas["ObjectResponse"];
export type EventResponse = Schemas["EventResponse"];

/** 列表包裹：items/next_cursor 对齐 B.0 分页约定；total 为 mock 扩展（spec §5.2 契约偏差）。 */
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

/** B.13 GET /admin/quality/reports。kpi/dimensions 为 mock 扩展（质量页 KPI 与左栏维度评分，EDP-030 落地后替换）。 */
export interface ReconciliationRow {
  source_system: string;
  object_type: string;
  source_count: number;
  edp_count: number;
  deviation_pct: number;
  ok: boolean;
}

export interface QualityReport {
  date: string;
  reconciliation: ReconciliationRow[];
  coverage: { overall_pct: number; by_type: { object_type: string; coverage_pct: number }[] };
  orphans: { event_orphans: number; evidence_orphans: number };
  checksum_sampling: { sampled: number; failed: number };
  kpi: {
    overall_pct: number;
    sla_pct: number;
    completeness_pct: number;
    pending_exceptions: number;
    high_priority: number;
  };
  dimensions: { domain: string; label: string; score_pct: number }[];
}

/** B.13 GET /api/v1/health；backup 与 ops_metrics 为 mock 扩展（备份卡/总览与事件流 KPI 带，spec §3.2/§5.2）。 */
export interface HealthResponse {
  status: string;
  db: string;
  db_ha: { role: string; replication_lag_mb: number; replicas: number };
  outbox_pending: number;
  last_sync: Record<string, string>;
  version: string;
  backup?: { last_full_at: string; wal_archive_at: string; last_restore_verify: string };
  ops_metrics?: {
    events_24h: number;
    ingest_peak_24h: number;
    p95_latency_ms: number;
    idempotency_hit_rate: number;
    dlq: number;
    audit_events_7d: number;
    policy_hits_today: number;
    adapters_success_rate: number;
    evidence_count: number;
    evidence_valid_rate: number;
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

/** mock 自有端点（EDP-030 落地后替换）：重校验/重索引任务与任务日志抽屉。 */
export interface QualityTask {
  task_id: string;
  task_type: string;
  status: string;
  started_at: string;
  logs: { ts: string; level: "INFO" | "WARN" | "ERROR"; message: string }[];
}
```

**验证**：`cd frontend; pnpm --filter web build`（tsc noEmit 通过即类型引用正确）。

**Commit**: `feat(w2): mocks 未冻结契约类型（B.4/B.6/B.9/B.12/B.13 + mock 扩展）`

## Task 4: data/ids.ts + data/objects.ts

**新建** `apps/web/src/mocks/data/ids.ts`：

```ts
/** 固定 UUID 表（spec §4）：跨文件共享，保证跨页引用一致。 */
export const TENANT_ID = "00000000-0000-4000-8000-000000000001";

export function mockUuid(n: number): string {
  return `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
}

// ---- 订单（SO-2026-00122~00131；AEOS §10 场景输入侧） ----
export const OBJ_ORDER_A = mockUuid(101); // 场景1 正常订单
export const OBJ_ORDER_B = mockUuid(102); // 场景2 关键料缺失（M4 主线）
export const OBJ_ORDER_C = mockUuid(103); // 场景3 供应商延迟通知
export const OBJ_ORDER_R1 = mockUuid(104); // 常规填充订单
export const OBJ_ORDER_E = mockUuid(105); // 场景5 高值低库存
export const OBJ_ORDER_R2 = mockUuid(106); // 常规填充订单
export const OBJ_ORDER_G = mockUuid(107); // 场景6 VIP 客户订单
export const OBJ_ORDER_H = mockUuid(108); // 场景7 多条件组合风险
export const OBJ_ORDER_I = mockUuid(109); // 场景8 数据不一致
export const OBJ_ORDER_J = mockUuid(110); // 场景9 供应商交叉风险

// ---- 客户 / 物料 / 产品（master） ----
export const OBJ_CUSTOMER_C008 = mockUuid(201); // VIP
export const OBJ_CUSTOMER_C030A = mockUuid(202); // 场景8 ERP 双记录 A
export const OBJ_CUSTOMER_C030B = mockUuid(203); // 场景8 ERP 双记录 B
export const OBJ_MATERIAL_X100 = mockUuid(301);
export const OBJ_MATERIAL_Y200 = mockUuid(302);
export const OBJ_PRODUCT_PF = mockUuid(311);
export const OBJ_PRODUCT_PD = mockUuid(312); // 新品（场景4）

// ---- 供应商 / 采购 / 研发 ----
export const OBJ_SUPPLIER_S021 = mockUuid(321); // 交期 10 天
export const OBJ_SUPPLIER_S118 = mockUuid(322); // 延迟 14 天（场景3）
export const OBJ_SUPPLIER_S030 = mockUuid(323); // 即将停产（场景9）
export const OBJ_PO_00771 = mockUuid(331); // X-100 在途 2000 件
export const OBJ_PO_00785 = mockUuid(332); // Y-200 推迟 2 周
export const OBJ_PROJECT_PRJD = mockUuid(341); // 产品 D 研发项目（场景4）

// ---- 关键事件（4xx 具名） ----
export const EVT_ORDER_A_RISK = mockUuid(401);
export const EVT_ORDER_B_RISK = mockUuid(402);
export const EVT_ORDER_C_RISK = mockUuid(403);
export const EVT_PRJD_READINESS = mockUuid(404);
export const EVT_ORDER_E_RISK = mockUuid(405);
export const EVT_ORDER_G_RISK = mockUuid(406);
export const EVT_ORDER_H_RISK = mockUuid(407);
export const EVT_ORDER_I_DQ = mockUuid(408);
export const EVT_ORDER_J_RISK = mockUuid(409);
export const EVT_ADAPTER_PLM_FAILED = mockUuid(410);
export const EVT_CASE_B_CREATED = mockUuid(411);

// ---- 证据（6xx 具名；611+ 为常规快照生成段） ----
export const EVID_ORDER_B_SNAPSHOT = mockUuid(601);
export const EVID_ORDER_B_INVENTORY = mockUuid(602);
export const EVID_ORDER_B_PO = mockUuid(603);
export const EVID_ORDER_B_LEADTIME = mockUuid(604);
export const EVID_ORDER_C_PO_DELAY = mockUuid(605);
export const EVID_PRJD_READINESS = mockUuid(606);
export const EVID_ORDER_E_INVENTORY = mockUuid(607);
export const EVID_ORDER_I_DUAL = mockUuid(608);
export const EVID_S030_DISCONTINUE = mockUuid(609);
export const EVID_ORDER_A_SNAPSHOT = mockUuid(610);

// ---- 案例前向引用（W4 页面数据不在本 spec 范围，仅作 ref 存在，B.5 示例编号） ----
export const CASE_ORDER_B = mockUuid(901);
export const SYNC_ID = mockUuid(910);
```

**新建** `apps/web/src/mocks/data/objects.ts`：

```ts
import type { ObjectResponse } from "../types";
import { daysBefore, hoursBefore } from "../lib/demo-time";
import {
  OBJ_CUSTOMER_C008, OBJ_CUSTOMER_C030A, OBJ_CUSTOMER_C030B, OBJ_MATERIAL_X100, OBJ_MATERIAL_Y200,
  OBJ_ORDER_A, OBJ_ORDER_B, OBJ_ORDER_C, OBJ_ORDER_E, OBJ_ORDER_G, OBJ_ORDER_H, OBJ_ORDER_I,
  OBJ_ORDER_J, OBJ_ORDER_R1, OBJ_ORDER_R2, OBJ_PO_00771, OBJ_PO_00785, OBJ_PRODUCT_PD,
  OBJ_PRODUCT_PF, OBJ_PROJECT_PRJD, OBJ_SUPPLIER_S021, OBJ_SUPPLIER_S118, OBJ_SUPPLIER_S030,
  TENANT_ID,
} from "./ids";

interface ObjectSeed {
  id: string;
  type: string;
  domain: string;
  source?: string;
  sourceId: string;
  name: string;
  revision?: number;
  attrs?: Record<string, unknown>;
  updatedHoursAgo?: number;
}

function obj(seed: ObjectSeed): ObjectResponse {
  return {
    object_id: seed.id,
    tenant_id: TENANT_ID,
    object_type: seed.type,
    owner_domain: seed.domain,
    source_system: seed.source ?? "erp",
    source_id: seed.sourceId,
    revision: seed.revision ?? 1,
    status: "ACTIVE",
    merged_into: null,
    attributes: { name: seed.name, ...(seed.attrs ?? {}) },
    created_at: daysBefore(21),
    updated_at: hoursBefore(seed.updatedHoursAgo ?? 6),
  };
}

/** 23 个业务对象：订单 10（场景 1~9 输入侧 + 2 常规）+ 客户/物料/产品/供应商/PO/研发项目（spec §4）。 */
export const objects: ObjectResponse[] = [
  obj({ id: OBJ_ORDER_A, type: "ORDER", domain: "sales", sourceId: "SO-2026-00122", name: "订单 A · 常规", revision: 2, attrs: { customer_code: "C-012", amount: 86000, currency: "CNY", status: "已确认", delivery_date: "2026-10-15" } }),
  obj({ id: OBJ_ORDER_B, type: "ORDER", domain: "sales", sourceId: "SO-2026-00123", name: "订单 B · 关键料缺失", revision: 7, updatedHoursAgo: 2, attrs: { customer_code: "C-008", amount: 120000, currency: "CNY", status: "已确认", delivery_date: "2026-10-15", risk_note: "物料X缺口1000" } }),
  obj({ id: OBJ_ORDER_C, type: "ORDER", domain: "sales", sourceId: "SO-2026-00124", name: "订单 C · 供应商延迟", revision: 3, attrs: { customer_code: "C-015", amount: 64000, currency: "CNY", status: "已确认", delivery_date: "2026-10-18" } }),
  obj({ id: OBJ_ORDER_R1, type: "ORDER", domain: "sales", sourceId: "SO-2026-00125", name: "订单 · 常规", attrs: { customer_code: "C-021", amount: 38000, currency: "CNY", status: "已确认", delivery_date: "2026-10-22" } }),
  obj({ id: OBJ_ORDER_E, type: "ORDER", domain: "sales", sourceId: "SO-2026-00126", name: "订单 E · 高值低库存", revision: 4, updatedHoursAgo: 3, attrs: { customer_code: "C-012", amount: 980000, currency: "CNY", status: "已确认", delivery_date: "2026-10-10", product: "P-F" } }),
  obj({ id: OBJ_ORDER_R2, type: "ORDER", domain: "sales", sourceId: "SO-2026-00127", name: "订单 · 常规", attrs: { customer_code: "C-033", amount: 51000, currency: "CNY", status: "已确认", delivery_date: "2026-10-25" } }),
  obj({ id: OBJ_ORDER_G, type: "ORDER", domain: "sales", sourceId: "SO-2026-00128", name: "订单 G · VIP 客户", revision: 2, attrs: { customer_code: "C-008", amount: 260000, currency: "CNY", status: "已确认", delivery_date: "2026-10-08", condition: "交付窗口严格" } }),
  obj({ id: OBJ_ORDER_H, type: "ORDER", domain: "sales", sourceId: "SO-2026-00129", name: "订单 H · 组合风险", revision: 5, updatedHoursAgo: 4, attrs: { customer_code: "C-015", amount: 450000, currency: "CNY", status: "已确认", delivery_date: "2026-10-12", risk_note: "部分物料短缺+产能紧张" } }),
  obj({ id: OBJ_ORDER_I, type: "ORDER", domain: "sales", sourceId: "SO-2026-00130", name: "订单 I · 数据不一致", revision: 2, attrs: { customer_code: "C-030", amount: 72000, currency: "CNY", status: "已确认", delivery_date: "2026-10-20" } }),
  obj({ id: OBJ_ORDER_J, type: "ORDER", domain: "sales", sourceId: "SO-2026-00131", name: "订单 J · 供应商交叉", revision: 3, attrs: { customer_code: "C-021", amount: 155000, currency: "CNY", status: "已确认", delivery_date: "2026-11-05", suppliers: ["S-021", "S-030"] } }),
  obj({ id: OBJ_CUSTOMER_C008, type: "CUSTOMER", domain: "master", source: "mdm", sourceId: "C-008", name: "某客户", attrs: { level: "VIP" } }),
  obj({ id: OBJ_CUSTOMER_C030A, type: "CUSTOMER", domain: "master", sourceId: "C-030", name: "宏达精密", attrs: { level: "普通" } }),
  obj({ id: OBJ_CUSTOMER_C030B, type: "CUSTOMER", domain: "master", sourceId: "C-030-B", name: "宏达精密", attrs: { level: "普通", note: "ERP 双记录（场景 8）" } }),
  obj({ id: OBJ_MATERIAL_X100, type: "MATERIAL", domain: "master", sourceId: "X-100", name: "物料 X-100", revision: 3, attrs: { total_available: 3200, reserved: 800, unit: "件" } }),
  obj({ id: OBJ_MATERIAL_Y200, type: "MATERIAL", domain: "master", sourceId: "Y-200", name: "物料 Y-200", revision: 2, attrs: { total_available: 5400, reserved: 400, unit: "件" } }),
  obj({ id: OBJ_PRODUCT_PF, type: "PRODUCT", domain: "master", source: "plm", sourceId: "P-F", name: "产品 F", attrs: { stage: "量产", available: 38 } }),
  obj({ id: OBJ_PRODUCT_PD, type: "PRODUCT", domain: "master", source: "plm", sourceId: "P-D", name: "产品 D（新品）", attrs: { stage: "验证中" } }),
  obj({ id: OBJ_SUPPLIER_S021, type: "SUPPLIER", domain: "procurement", sourceId: "S-021", name: "供应商 S-021", attrs: { lead_time_days: 10 } }),
  obj({ id: OBJ_SUPPLIER_S118, type: "SUPPLIER", domain: "procurement", sourceId: "S-118", name: "供应商 S-118", revision: 2, attrs: { lead_time_days: 14, note: "预计交期延迟 14 天" } }),
  obj({ id: OBJ_SUPPLIER_S030, type: "SUPPLIER", domain: "procurement", sourceId: "S-030", name: "供应商 S-030", revision: 2, attrs: { status: "即将停产", effective_date: "2026-11-01" } }),
  obj({ id: OBJ_PO_00771, type: "PURCHASE_ORDER", domain: "procurement", sourceId: "PO-2026-00771", name: "在途采购 · X-100×2000", revision: 2, attrs: { supplier_code: "S-021", material_code: "X-100", quantity: 2000, expected_date: "2026-10-20", status: "在途" } }),
  obj({ id: OBJ_PO_00785, type: "PURCHASE_ORDER", domain: "procurement", sourceId: "PO-2026-00785", name: "在途采购 · Y-200×1500", revision: 3, attrs: { supplier_code: "S-118", material_code: "Y-200", quantity: 1500, expected_date: "2026-10-12", status: "在途（推迟 2 周）" } }),
  obj({ id: OBJ_PROJECT_PRJD, type: "PROJECT", domain: "rd", source: "plm", sourceId: "PRJ-D", name: "产品 D 研发项目", revision: 4, attrs: { status: "验证中", product: "P-D" } }),
];

export function findObject(id: string): ObjectResponse | undefined {
  return objects.find((o) => o.object_id === id);
}
```

**验证**：`cd frontend; pnpm --filter web build`

**Commit**: `feat(w2): mocks fixtures —— 固定 UUID 表与 23 个业务对象（十类场景输入侧）`

## Task 5: data/events.ts（55 条）

**新建** `apps/web/src/mocks/data/events.ts`：

```ts
import type { EventResponse } from "../types";
import { daysBefore, hoursBefore, minutesBefore } from "../lib/demo-time";
import {
  EVT_ADAPTER_PLM_FAILED, EVT_CASE_B_CREATED, EVT_ORDER_A_RISK, EVT_ORDER_B_RISK, EVT_ORDER_C_RISK,
  EVT_ORDER_E_RISK, EVT_ORDER_G_RISK, EVT_ORDER_H_RISK, EVT_ORDER_I_DQ, EVT_ORDER_J_RISK,
  EVT_PRJD_READINESS, OBJ_ORDER_A, OBJ_ORDER_B, OBJ_ORDER_C, OBJ_ORDER_E, OBJ_ORDER_G, OBJ_ORDER_H,
  OBJ_ORDER_I, OBJ_ORDER_J, OBJ_ORDER_R1, OBJ_ORDER_R2, OBJ_PROJECT_PRJD, TENANT_ID, mockUuid,
} from "./ids";

type RiskLevel = "P0" | "P1" | "P2" | "P3" | null;

interface EventSeed {
  id: string;
  type: string;
  objectId: string;
  source: string;
  occurredAt: string;
  actorType?: "HUMAN" | "SERVICE" | "AI";
  actorId?: string;
  resultType?: string | null;
  risk?: RiskLevel;
  score?: number | null;
  data?: Record<string, unknown>;
}

function evt(seed: EventSeed): EventResponse {
  return {
    event_id: seed.id,
    tenant_id: TENANT_ID,
    event_type: seed.type,
    object_id: seed.objectId,
    source_system: seed.source,
    occurred_at: seed.occurredAt,
    actor_type: seed.actorType ?? "SERVICE",
    actor_id: seed.actorId ?? "adapter:erp",
    result_type: seed.resultType ?? null,
    risk_level: seed.risk ?? null,
    score: seed.score ?? null,
    data: seed.data ?? {},
    idempotency_key: null,
    created_at: seed.occurredAt,
  };
}

/** 订单例行事件（10 创建 + 5 确认 + 10 更新 + 3 交期变更），确定性生成。 */
const orderIds = [OBJ_ORDER_A, OBJ_ORDER_B, OBJ_ORDER_C, OBJ_ORDER_R1, OBJ_ORDER_E, OBJ_ORDER_R2, OBJ_ORDER_G, OBJ_ORDER_H, OBJ_ORDER_I, OBJ_ORDER_J];

const orderRoutineEvents: EventResponse[] = orderIds.flatMap((id, i) => {
  const rows: EventResponse[] = [
    evt({ id: mockUuid(500 + i * 4), type: "order.created", objectId: id, source: "erp", occurredAt: daysBefore(14 - i), actorId: "adapter:erp", data: { note: "订单创建" } }),
    evt({ id: mockUuid(501 + i * 4), type: "order.updated", objectId: id, source: "erp", occurredAt: daysBefore(9 - i * 0.8), actorId: "adapter:erp", data: { note: "主数据刷新" } }),
  ];
  if (i % 2 === 0) {
    rows.push(evt({ id: mockUuid(502 + i * 4), type: "order.confirmed", objectId: id, source: "erp", occurredAt: daysBefore(12 - i), actorType: "HUMAN", actorId: "user:sales_li", data: { note: "订单确认" } }));
  }
  if (i === 2 || i === 4 || i === 7) {
    rows.push(evt({ id: mockUuid(503 + i * 4), type: "order.delivery_date_changed", objectId: id, source: "erp", occurredAt: hoursBefore(30 - i), actorId: "adapter:erp", data: { note: "交期变更" } }));
  }
  return rows;
});

/** 库存例行事件 16 条（可用 8 + 占用 8）。 */
const inventoryRoutineEvents: EventResponse[] = Array.from({ length: 16 }, (_, i) =>
  evt({
    id: mockUuid(560 + i),
    type: "inventory.changed",
    objectId: i % 2 === 0 ? OBJ_ORDER_B : OBJ_ORDER_E,
    source: "erp",
    occurredAt: hoursBefore(1 + i * 0.5),
    actorId: "adapter:erp",
    data: { kind: i < 8 ? "available" : "reserved", delta: -(i % 3) * 50 - 20 },
  }),
);

/** 能力结果回流 + 场景关键事件（B.3 形状；L 系映射 P 系，shared enums）。 */
const capabilityEvents: EventResponse[] = [
  evt({ id: EVT_ORDER_A_RISK, type: "capability.result.order_risk", objectId: OBJ_ORDER_A, source: "agent-hub", occurredAt: hoursBefore(26), actorType: "AI", actorId: "agent:delivery-order-risk", resultType: "ORDER_RISK", risk: "P3", score: 0.08, data: { reason: "物料充足", recommendation: "无（正常）" } }),
  evt({ id: EVT_ORDER_B_RISK, type: "capability.result.order_risk", objectId: OBJ_ORDER_B, source: "agent-hub", occurredAt: hoursBefore(5), actorType: "AI", actorId: "agent:delivery-order-risk", resultType: "ORDER_RISK", risk: "P1", score: 0.86, data: { reason: "物料X缺口1000", recommendation: "加急采购/替代料", expected_delay_days: 5 } }),
  evt({ id: EVT_ORDER_C_RISK, type: "capability.result.order_risk", objectId: OBJ_ORDER_C, source: "agent-hub", occurredAt: hoursBefore(20), actorType: "AI", actorId: "agent:delivery-order-risk", resultType: "ORDER_RISK", risk: "P2", score: 0.64, data: { reason: "PO 预计到货推迟 2 周", recommendation: "确认交期，调整生产计划" } }),
  evt({ id: EVT_PRJD_READINESS, type: "capability.result.product_readiness", objectId: OBJ_PROJECT_PRJD, source: "agent-hub", occurredAt: hoursBefore(32), actorType: "AI", actorId: "agent:rd-product-readiness", resultType: "PRODUCT_READINESS", risk: "P2", score: 0.55, data: { readiness: "未达产", blocking: "完成验证与测试" } }),
  evt({ id: EVT_ORDER_E_RISK, type: "capability.result.order_quality", objectId: OBJ_ORDER_E, source: "agent-hub", occurredAt: hoursBefore(8), actorType: "AI", actorId: "agent:sales-order-quality", resultType: "ORDER_QUALITY", risk: "P1", score: 0.81, data: { reason: "产品F库存不足（仅剩 38）", recommendation: "补料/通知客户" } }),
  evt({ id: EVT_ORDER_G_RISK, type: "capability.result.order_quality", objectId: OBJ_ORDER_G, source: "agent-hub", occurredAt: hoursBefore(28), actorType: "AI", actorId: "agent:sales-order-quality", resultType: "ORDER_QUALITY", risk: "P3", score: 0.12, data: { reason: "重要客户，策略加权后无风险", recommendation: "正常交付" } }),
  evt({ id: EVT_ORDER_H_RISK, type: "capability.result.order_risk", objectId: OBJ_ORDER_H, source: "agent-hub", occurredAt: hoursBefore(3), actorType: "AI", actorId: "agent:delivery-order-risk", resultType: "ORDER_RISK", risk: "P0", score: 0.93, data: { reason: "部分物料短缺+产能紧张", recommendation: "组合方案：分批交付+产能协调+替代料" } }),
  evt({ id: EVT_ORDER_I_DQ, type: "capability.result.dq_check", objectId: OBJ_ORDER_I, source: "agent-hub", occurredAt: hoursBefore(44), actorType: "AI", actorId: "agent:dq-checker", resultType: "DATA_QUALITY", risk: "P2", score: 0.58, data: { reason: "客户ID在ERP中有两处不同记录", recommendation: "人工确认主记录" } }),
  evt({ id: EVT_ORDER_J_RISK, type: "capability.result.order_risk", objectId: OBJ_ORDER_J, source: "agent-hub", occurredAt: hoursBefore(12), actorType: "AI", actorId: "agent:delivery-order-risk", resultType: "ORDER_RISK", risk: "P1", score: 0.88, data: { reason: "供应商 S-030 即将停产，多源依赖", recommendation: "寻找替代供应商或修改BOM" } }),
  evt({ id: EVT_CASE_B_CREATED, type: "decision.case_created", objectId: OBJ_ORDER_B, source: "agent-hub", occurredAt: hoursBefore(4), actorType: "AI", actorId: "agent:delivery-order-risk", data: { case_no: "DC-20260928-007", question: "订单 SO-2026-00123 存在缺料风险，是否加急采购物料X？" } }),
  evt({ id: EVT_ADAPTER_PLM_FAILED, type: "adapter.sync.failed", objectId: OBJ_PROJECT_PRJD, source: "edp-adapter", occurredAt: minutesBefore(18), actorType: "SERVICE", actorId: "adapter:plm", risk: "P2", score: 0.5, resultType: "ADAPTER", data: { adapter: "plm", reason: "UPSTREAM_UNAVAILABLE", note: "场景 10：工具调用失败，已转人工跟进" } }),
];

export const events: EventResponse[] = [...orderRoutineEvents, ...inventoryRoutineEvents, ...capabilityEvents];

export function findEvent(id: string): EventResponse | undefined {
  return events.find((e) => e.event_id === id);
}
```

**验证**：`cd frontend; pnpm --filter web build`

**Commit**: `feat(w2): mocks fixtures —— 事件流（例行 + 能力结果回流，M4 主线 P1）`

## Task 6: data/evidence.ts + data/ebms.ts

**新建** `apps/web/src/mocks/data/evidence.ts`：

```ts
import type { EvidenceRecord } from "../types";
import { hoursBefore } from "../lib/demo-time";
import {
  CASE_ORDER_B, EVID_ORDER_A_SNAPSHOT, EVID_ORDER_B_INVENTORY, EVID_ORDER_B_LEADTIME, EVID_ORDER_B_PO,
  EVID_ORDER_B_SNAPSHOT, EVID_ORDER_C_PO_DELAY, EVID_ORDER_E_INVENTORY, EVID_ORDER_I_DUAL,
  EVID_PRJD_READINESS, EVID_S030_DISCONTINUE, OBJ_CUSTOMER_C030A, OBJ_MATERIAL_X100, OBJ_ORDER_A,
  OBJ_ORDER_B, OBJ_ORDER_C, OBJ_ORDER_E, OBJ_ORDER_G, OBJ_ORDER_H, OBJ_ORDER_I, OBJ_ORDER_J,
  OBJ_PO_00771, OBJ_PO_00785, OBJ_PRODUCT_PF, OBJ_PROJECT_PRJD, OBJ_SUPPLIER_S021, OBJ_SUPPLIER_S030,
  OBJ_ORDER_R1, OBJ_ORDER_R2,
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
```

（注：routine 数组里重复 OBJ_ORDER_B/OBJ_ORDER_A 与具名共存是刻意的——列表/链图数据更饱满；一致性测试只验引用存在。）

**新建** `apps/web/src/mocks/data/ebms.ts`：

```ts
import type { ExceptionItem } from "../types";
import { hoursBefore, minutesBefore } from "../lib/demo-time";
import {
  CASE_ORDER_B, EVT_ADAPTER_PLM_FAILED, EVT_ORDER_B_RISK, EVT_ORDER_C_RISK, EVT_ORDER_E_RISK,
  EVT_ORDER_H_RISK, EVT_ORDER_I_DQ, EVT_ORDER_J_RISK, EVT_PRJD_READINESS, OBJ_ORDER_B, OBJ_ORDER_C,
  OBJ_ORDER_E, OBJ_ORDER_H, OBJ_ORDER_I, OBJ_ORDER_J, OBJ_PROJECT_PRJD,
} from "./ids";

/**
 * B.9 异常列表（8 条 = P0×1 + P1×3 + P2×4）。
 * status 语义由 handler 实现：B.9 无 status 字段——mock 约定最后一行（场景 8 数据不一致）
 * 为 RESOLVED（人工已确认），`?status=RESOLVED` 只返回它，默认/OPEN 返回其余 7 条。
 */
export const exceptions: ExceptionItem[] = [
  { event_id: EVT_ORDER_H_RISK, result_type: "ORDER_RISK", risk_level: "P0", object_id: OBJ_ORDER_H, order_no: "SO-2026-00129", summary: "部分物料短缺+产能紧张，综合高风险", occurred_at: hoursBefore(3), case_id: null },
  { event_id: EVT_ORDER_B_RISK, result_type: "ORDER_RISK", risk_level: "P1", object_id: OBJ_ORDER_B, order_no: "SO-2026-00123", summary: "物料X缺口1000，预计延误5天", occurred_at: hoursBefore(5), case_id: CASE_ORDER_B },
  { event_id: EVT_ORDER_E_RISK, result_type: "ORDER_QUALITY", risk_level: "P1", object_id: OBJ_ORDER_E, order_no: "SO-2026-00126", summary: "产品F库存不足（仅剩38），大额订单交付风险", occurred_at: hoursBefore(8), case_id: null },
  { event_id: EVT_ORDER_J_RISK, result_type: "ORDER_RISK", risk_level: "P1", object_id: OBJ_ORDER_J, order_no: "SO-2026-00131", summary: "供应商S-030即将停产，多源依赖需替代方案", occurred_at: hoursBefore(12), case_id: null },
  { event_id: EVT_ORDER_C_RISK, result_type: "ORDER_RISK", risk_level: "P2", object_id: OBJ_ORDER_C, order_no: "SO-2026-00124", summary: "PO-2026-00785 预计到货推迟 2 周", occurred_at: hoursBefore(20), case_id: null },
  { event_id: EVT_PRJD_READINESS, result_type: "PRODUCT_READINESS", risk_level: "P2", object_id: OBJ_PROJECT_PRJD, order_no: "PRJ-D", summary: "新品D项目验证中，未达量产就绪", occurred_at: hoursBefore(32), case_id: null },
  { event_id: EVT_ADAPTER_PLM_FAILED, result_type: "ADAPTER", risk_level: "P2", object_id: OBJ_PROJECT_PRJD, order_no: "PLM", summary: "PLM 同步失败（工具调用故障），里程碑数据待更新", occurred_at: minutesBefore(18), case_id: null },
  { event_id: EVT_ORDER_I_DQ, result_type: "DATA_QUALITY", risk_level: "P2", object_id: OBJ_ORDER_I, order_no: "SO-2026-00130", summary: "客户ID在ERP存在双记录，需人工确认", occurred_at: hoursBefore(44), case_id: null },
];
```

**验证**：`cd frontend; pnpm --filter web build`

**Commit**: `feat(w2): mocks fixtures —— 证据链（20 条）与 EBMS 异常（8 条）`

## Task 7: data/quality.ts + data/health.ts + data/adapters.ts + data/audit.ts

**新建** `apps/web/src/mocks/data/quality.ts`：

```ts
import type { QualityReport } from "../types";

/** B.13 示例数值 + mock 扩展（kpi/dimensions）。pending=OPEN 异常数（7）、high=P0/P1 数（4），一致性测试断言。 */
export const qualityReport: QualityReport = {
  date: "2026-09-28",
  reconciliation: [
    { source_system: "erp", object_type: "ORDER", source_count: 1200, edp_count: 1180, deviation_pct: 1.67, ok: true },
    { source_system: "erp", object_type: "INVENTORY", source_count: 860, edp_count: 858, deviation_pct: 0.23, ok: true },
    { source_system: "plm", object_type: "PROJECT", source_count: 42, edp_count: 41, deviation_pct: 2.38, ok: true },
    { source_system: "mdm", object_type: "CUSTOMER", source_count: 640, edp_count: 639, deviation_pct: 0.16, ok: true },
    { source_system: "erp", object_type: "PURCHASE_ORDER", source_count: 310, edp_count: 309, deviation_pct: 0.32, ok: true },
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
  checksum_sampling: { sampled: 120, failed: 0 },
  kpi: { overall_pct: 97.8, sla_pct: 99.2, completeness_pct: 98.7, pending_exceptions: 7, high_priority: 4 },
  dimensions: [
    { domain: "sales", label: "ERP·订单", score_pct: 99.1 },
    { domain: "delivery", label: "WMS·库存", score_pct: 98.4 },
    { domain: "rd", label: "PLM·产品就绪度", score_pct: 94.2 },
    { domain: "master", label: "MDM·客户", score_pct: 97.6 },
    { domain: "procurement", label: "PROCURE·采购", score_pct: 96.3 },
  ],
};

export const coverageReport = qualityReport.coverage;
```

**新建** `apps/web/src/mocks/data/health.ts`：

```ts
import type { HealthResponse, OutboxStatus } from "../types";
import { hoursBefore, minutesBefore } from "../lib/demo-time";
import { evidence } from "./evidence";

/** B.13 示例 + mock 扩展（backup 备份卡 / ops_metrics 总览与事件流 KPI 带，spec §3.2）。 */
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
    idempotency_hit_rate: 99.4,
    dlq: 6,
    audit_events_7d: 15230,
    policy_hits_today: 39,
    adapters_success_rate: 99.5,
    evidence_count: evidence.length,
    evidence_valid_rate: 100,
  },
};

export const outboxStatus: OutboxStatus = {
  pending: 3,
  failed: 0,
  oldest_pending_at: minutesBefore(18),
  published_last_hour: 1240,
};
```

**新建** `apps/web/src/mocks/data/adapters.ts`：

```ts
import type { AdapterSummary } from "../types";
import { hoursBefore, minutesBefore } from "../lib/demo-time";

/** B.12 + 13.6 适配器页 7 列。plm=降级（呼应场景 10）；mode=mock（Mock 适配器为基线交付）。 */
export const adapters: AdapterSummary[] = [
  { adapter: "erp", mode: "mock", access: "REST 拉取", team: "数据平台组", last_sync: minutesBefore(12), health: "OK", health_pct: 99.9, status: "运行中", isolation: "租户级" },
  { adapter: "mes", mode: "mock", access: "REST 拉取", team: "制造运营组", last_sync: minutesBefore(26), health: "OK", health_pct: 99.7, status: "运行中", isolation: "租户级" },
  { adapter: "plm", mode: "mock", access: "REST 拉取", team: "研发效能组", last_sync: hoursBefore(3), health: "DEGRADED", health_pct: 96.2, status: "降级", isolation: "租户级" },
  { adapter: "mdm", mode: "mock", access: "DB 拉取", team: "数据平台组", last_sync: minutesBefore(40), health: "OK", health_pct: 99.9, status: "运行中", isolation: "租户级" },
  { adapter: "crm", mode: "mock", access: "REST 推送", team: "销售运营组", last_sync: hoursBefore(1), health: "OK", health_pct: 99.8, status: "运行中", isolation: "租户级" },
];
```

**新建** `apps/web/src/mocks/data/audit.ts`：

```ts
import type { AuditLogItem } from "../types";
import { daysBefore, hoursBefore, minutesBefore } from "../lib/demo-time";
import { CASE_ORDER_B, OBJ_ORDER_B, TENANT_ID } from "./ids";

/** B.6 审计条目（12 条）：含 2 条 GUARD_DENIED（AI 越权可视化举证，总览审计动态用）。 */
export const auditLogs: AuditLogItem[] = [
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
```

**验证**：`cd frontend; pnpm --filter web build`

**Commit**: `feat(w2): mocks fixtures —— 质量/健康/适配器/审计`

## Task 8: handlers/auth.ts + handlers/registry.ts + 聚合改造

**新建** `apps/web/src/mocks/handlers/auth.ts`（迁移 W1 login 并补 me/refresh，使 MSW 模式下路由守卫流程可用）：

```ts
import { http, HttpResponse } from "msw";
import { TENANT_ID, mockUuid } from "../data/ids";

/** B.1 TokenResponse 形状的演示会话（自 W1 handlers.ts 迁移；user_id 仅对 ascii 用户名合法，与 W1 行为一致）。 */
function sessionOf(username: string, roles: string[], isPlatformAdmin: boolean) {
  return {
    access_token: `mock-access-${username}`,
    refresh_token: `mock-refresh-${username}`,
    expires_in: 7200,
    tenant: {
      tenant_id: TENANT_ID,
      slug: "default",
      name: "默认租户",
      status: "ACTIVE",
    },
    user: {
      user_id: `00000000-0000-0000-0000-${username.padStart(12, "0")}`,
      username,
      roles,
      is_platform_admin: isPlatformAdmin,
    },
  };
}

export function unauthorized(): HttpResponse {
  return HttpResponse.json(
    { error: { code: "UNAUTHENTICATED", message: "用户名或密码错误", request_id: "mock-request-id" } },
    { status: 401 },
  );
}

export const authHandlers = [
  http.post("*/api/v1/auth/login", async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as { username?: string; password?: string };
    const username = body.username ?? "";
    const password = body.password ?? "";
    if (username === "manager1") return HttpResponse.json(sessionOf("manager1", ["MANAGER"], false));
    if (username === "analyst1") return HttpResponse.json(sessionOf("analyst1", ["ANALYST"], false));
    if (username === "admin") {
      if (password === "Admin@123!") return HttpResponse.json(sessionOf("admin", ["ADMIN"], true));
      return unauthorized();
    }
    return unauthorized();
  }),

  // B.1 GET /auth/me：MSW 模式默认 manager1 会话（user_id 用固定 UUID，username 不入 UUID）。
  http.get("*/api/v1/auth/me", () =>
    HttpResponse.json({
      user_id: mockUuid(2),
      username: "manager1",
      org_id: null,
      tenant_id: TENANT_ID,
      is_platform_admin: false,
      roles: ["MANAGER"],
      permissions: ["objects:read", "objects:write", "events:read", "evidence:read", "quality:read", "audit:read"],
    }),
  ),

  // B.1 POST /auth/refresh
  http.post("*/api/v1/auth/refresh", () =>
    HttpResponse.json({ access_token: "mock-access-refreshed", expires_in: 7200 }),
  ),
];
```

**新建** `apps/web/src/mocks/handlers/registry.ts`：

```ts
import { http, HttpResponse } from "msw";
import type { ObjectResponse } from "../types";
import { clampLimit, paginate } from "../lib/cursor";
import { errorOf } from "../lib/http";
import { scenarioResponse } from "../lib/scenario";
import { objects } from "../data/objects";
import { TENANT_ID } from "../data/ids";
import { msBefore } from "../lib/demo-time";

/** 写语义（spec §5.2）：会话内可变 Map，刷新即复位。 */
const store = new Map<string, ObjectResponse>(objects.map((o) => [o.object_id, { ...o }]));

function sortedAll(): ObjectResponse[] {
  return [...store.values()].sort((a, b) =>
    b.updated_at.localeCompare(a.updated_at) || b.object_id.localeCompare(a.object_id),
  );
}

interface UpsertBody {
  object_type?: string;
  owner_domain?: string;
  source_system?: string;
  source_id?: string;
  idempotency?: { expected_revision?: number | null };
  attributes?: Record<string, unknown>;
}

export const registryHandlers = [
  // B.2 GET /objects：组合键过滤 + 游标分页
  http.get("*/api/v1/objects", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const q = new URL(request.url).searchParams;
    const filtered = sortedAll().filter((o) => {
      if (q.get("object_type") && o.object_type !== q.get("object_type")) return false;
      if (q.get("source_system") && o.source_system !== q.get("source_system")) return false;
      if (q.get("source_id") && o.source_id !== q.get("source_id")) return false;
      if (q.get("owner_domain") && o.owner_domain !== q.get("owner_domain")) return false;
      if (q.get("status") && o.status !== q.get("status")) return false;
      return true;
    });
    return HttpResponse.json(paginate(filtered, clampLimit(q.get("limit")), q.get("cursor")));
  }),

  // B.2 GET /objects/{id}：跨租户/不存在统一 404
  http.get("*/api/v1/objects/:objectId", ({ params }) => {
    const found = store.get(String(params.objectId));
    if (!found) return errorOf("NOT_FOUND", "资源不存在", 404);
    return HttpResponse.json(found);
  }),

  // B.2 POST /objects：首次 201 / upsert 200（revision+1）；乐观锁 409 + current_revision
  http.post("*/api/v1/objects", async ({ request }) => {
    const body = (await request.json().catch(() => null)) as UpsertBody | null;
    if (!body?.object_type || !body.owner_domain || !body.source_system || !body.source_id) {
      return errorOf("VALIDATION_ERROR", "object_type/owner_domain/source_system/source_id 均为必填", 400);
    }
    const existing = sortedAll().find(
      (o) =>
        o.object_type === body.object_type &&
        o.source_system === body.source_system &&
        o.source_id === body.source_id,
    );
    const expected = body.idempotency?.expected_revision ?? null;
    if (existing && expected !== null && expected !== existing.revision) {
      return errorOf("CONFLICT", "版本冲突：对象已被修改", 409, { current_revision: existing.revision });
    }
    const now = msBefore(0);
    if (existing) {
      existing.revision += 1;
      existing.attributes = { ...(body.attributes ?? existing.attributes) };
      existing.updated_at = now;
      return HttpResponse.json({
        object_id: existing.object_id,
        revision: existing.revision,
        status: existing.status,
        created_at: existing.created_at,
      });
    }
    const object_id = crypto.randomUUID();
    const record: ObjectResponse = {
      object_id,
      tenant_id: TENANT_ID,
      object_type: body.object_type,
      owner_domain: body.owner_domain,
      source_system: body.source_system,
      source_id: body.source_id,
      revision: 1,
      status: "ACTIVE",
      merged_into: null,
      attributes: body.attributes ?? {},
      created_at: now,
      updated_at: now,
    };
    store.set(object_id, record);
    return HttpResponse.json({ object_id, revision: 1, status: "ACTIVE", created_at: now }, { status: 201 });
  }),

  // B.2 GET /objects/{id}/history：revision 轨迹（mock 按 revision 数生成）
  http.get("*/api/v1/objects/:objectId/history", ({ params }) => {
    const found = store.get(String(params.objectId));
    if (!found) return errorOf("NOT_FOUND", "资源不存在", 404);
    const revisions = Array.from({ length: found.revision }, (_, i) => ({
      revision: i + 1,
      action: "OBJECT_UPSERT",
      actor_id: `adapter:${found.source_system}`,
      occurred_at: msBefore((found.revision - i) * 6 * 60 * 60 * 1000),
    }));
    return HttpResponse.json({ object_id: found.object_id, revisions });
  }),
];
```

**改写** `apps/web/src/mocks/handlers.ts`（聚合入口；W1 login 逻辑已迁 handlers/auth.ts，导出名不变）：

```ts
import { authHandlers } from "./handlers/auth";
import { registryHandlers } from "./handlers/registry";

export const handlers = [...authHandlers, ...registryHandlers];
```

**新建** `apps/web/src/mocks/handlers/registry.test.ts`：

```ts
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { setupServer } from "msw/node";
import { handlers } from "../handlers";
import { OBJ_ORDER_B } from "../data/ids";

const server = setupServer(...handlers);
const BASE = "http://mock.test";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("registry handlers", () => {
  it("列表：object_type=ORDER 过滤 + total=10 + 分页", async () => {
    const resp = await fetch(`${BASE}/api/v1/objects?object_type=ORDER&limit=3`);
    const body = (await resp.json()) as { items: { object_type: string }[]; next_cursor: string | null; total: number };
    expect(resp.status).toBe(200);
    expect(body.total).toBe(10);
    expect(body.items).toHaveLength(3);
    expect(body.next_cursor).toBeTruthy();
    expect(body.items.every((i) => i.object_type === "ORDER")).toBe(true);
  });

  it("组合键查询：erp/SO-2026-00123 → 订单 B rev7", async () => {
    const resp = await fetch(`${BASE}/api/v1/objects?source_system=erp&source_id=SO-2026-00123`);
    const body = (await resp.json()) as { items: { revision: number }[]; total: number };
    expect(body.total).toBe(1);
    expect(body.items[0].revision).toBe(7);
  });

  it("点查 404（不泄露存在性）", async () => {
    const resp = await fetch(`${BASE}/api/v1/objects/00000000-0000-4000-8000-00000000dead`);
    expect(resp.status).toBe(404);
    expect(await resp.json()).toMatchObject({ error: { code: "NOT_FOUND" } });
  });

  it("新建 201 → 同键再提交 200 且 revision+1", async () => {
    const payload = {
      object_type: "ORDER",
      owner_domain: "sales",
      source_system: "erp",
      source_id: "SO-2026-00999",
      attributes: { name: "测试订单" },
    };
    const r1 = await fetch(`${BASE}/api/v1/objects`, { method: "POST", body: JSON.stringify(payload) });
    expect(r1.status).toBe(201);
    expect(((await r1.json()) as { revision: number }).revision).toBe(1);
    const r2 = await fetch(`${BASE}/api/v1/objects`, {
      method: "POST",
      body: JSON.stringify({ ...payload, idempotency: { expected_revision: 1 } }),
    });
    expect(r2.status).toBe(200);
    expect(((await r2.json()) as { revision: number }).revision).toBe(2);
  });

  it("乐观锁冲突：expected_revision 不符 → 409 + current_revision=7", async () => {
    const resp = await fetch(`${BASE}/api/v1/objects`, {
      method: "POST",
      body: JSON.stringify({
        object_type: "ORDER",
        owner_domain: "sales",
        source_system: "erp",
        source_id: "SO-2026-00123",
        idempotency: { expected_revision: 3 },
      }),
    });
    expect(resp.status).toBe(409);
    expect(await resp.json()).toMatchObject({ error: { code: "CONFLICT", current_revision: 7 } });
  });

  it("history：订单 B → 7 条 OBJECT_UPSERT 轨迹", async () => {
    const resp = await fetch(`${BASE}/api/v1/objects/${OBJ_ORDER_B}/history`);
    const body = (await resp.json()) as { revisions: { revision: number; action: string }[] };
    expect(body.revisions).toHaveLength(7);
    expect(body.revisions.at(-1)).toMatchObject({ revision: 7, action: "OBJECT_UPSERT" });
  });

  it("场景注入：X-Mock-Scenario=429 → RATE_LIMITED + Retry-After", async () => {
    const resp = await fetch(`${BASE}/api/v1/objects`, { headers: { "X-Mock-Scenario": "429" } });
    expect(resp.status).toBe(429);
    expect(resp.headers.get("Retry-After")).toBe("1");
  });
});
```

（注：handler store 是模块级可变 Map，测试文件间相互隔离（vitest 独立 worker）；409 用例不产生写入，"新建→再提交"用独立 source_id，无顺序依赖。）

**验证**：

```powershell
cd frontend; pnpm --filter web test src/mocks
```

**Commit**: `refactor(w2): mocks handlers 按域拆分——auth（补 me/refresh）与 registry`

## Task 9: handlers/events.ts

**新建** `apps/web/src/mocks/handlers/events.ts`：

```ts
import { http, HttpResponse } from "msw";
import type { EventResponse } from "../types";
import { clampLimit, paginate } from "../lib/cursor";
import { errorOf } from "../lib/http";
import { scenarioResponse } from "../lib/scenario";
import { events } from "../data/events";
import { TENANT_ID, mockUuid } from "../data/ids";
import { iso } from "../lib/demo-time";

/** 写语义：会话内追加 + Idempotency-Key 档案（B.3），刷新即复位。 */
const store: EventResponse[] = events.map((e) => ({ ...e }));
const batchArchive = new Map<string, { accepted: number; duplicated: number; rejected: number }>();
let syntheticSeq = 1000; // batch 写入生成段（mockUuid 1000+）

function sortedAll(): EventResponse[] {
  return [...store].sort((a, b) =>
    b.occurred_at.localeCompare(a.occurred_at) || b.event_id.localeCompare(a.event_id),
  );
}

interface EventInBody {
  events?: {
    event_id?: string;
    event_type?: string;
    object_id?: string;
    source_system?: string;
    occurred_at?: string;
    actor_type?: "HUMAN" | "SERVICE" | "AI";
    actor_id?: string | null;
    result_type?: string | null;
    risk_level?: "P0" | "P1" | "P2" | "P3" | null;
    score?: number | null;
    data?: Record<string, unknown>;
  }[];
}

export const eventHandlers = [
  // B.3 GET /events：过滤（object_id/event_type/risk_level/since/until 闭区间）+ 游标分页（occurred_at DESC）
  http.get("*/api/v1/events", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const q = new URL(request.url).searchParams;
    const filtered = sortedAll().filter((e) => {
      if (q.get("object_id") && e.object_id !== q.get("object_id")) return false;
      if (q.get("event_type") && e.event_type !== q.get("event_type")) return false;
      if (q.get("risk_level") && e.risk_level !== q.get("risk_level")) return false;
      if (q.get("since") && e.occurred_at < q.get("since")!) return false;
      if (q.get("until") && e.occurred_at > q.get("until")!) return false;
      return true;
    });
    return HttpResponse.json(paginate(filtered, clampLimit(q.get("limit")), q.get("cursor")));
  }),

  // B.3 GET /events/{id}：404 统一
  http.get("*/api/v1/events/:eventId", ({ params }) => {
    const found = store.find((e) => e.event_id === String(params.eventId));
    if (!found) return errorOf("NOT_FOUND", "资源不存在", 404);
    return HttpResponse.json(found);
  }),

  // B.3 POST /events/batch：Idempotency-Key 必填；重放返回存档 + deduplicated=true
  http.post("*/api/v1/events/batch", async ({ request }) => {
    const key = request.headers.get("Idempotency-Key");
    if (!key) return errorOf("VALIDATION_ERROR", "缺少 Idempotency-Key 头", 400);
    const archived = batchArchive.get(key);
    if (archived) {
      return HttpResponse.json({ ...archived, deduplicated: true });
    }
    const body = (await request.json().catch(() => null)) as EventInBody | null;
    if (!body?.events?.length) return errorOf("VALIDATION_ERROR", "events 不能为空", 400);
    let accepted = 0;
    for (const item of body.events) {
      if (!item.event_type || !item.object_id || !item.source_system || !item.occurred_at) {
        continue; // 字段不全 → rejected（mock 简化）
      }
      accepted += 1;
      syntheticSeq += 1;
      store.push({
        event_id: item.event_id ?? mockUuid(syntheticSeq),
        tenant_id: TENANT_ID,
        event_type: item.event_type,
        object_id: item.object_id,
        source_system: item.source_system,
        occurred_at: item.occurred_at,
        actor_type: item.actor_type ?? "SERVICE",
        actor_id: item.actor_id ?? "service:mock",
        result_type: item.result_type ?? null,
        risk_level: item.risk_level ?? null,
        score: item.score ?? null,
        data: item.data ?? {},
        idempotency_key: key,
        created_at: iso("2026-09-28T08:30:00Z"),
      });
    }
    const rejected = body.events.length - accepted;
    const result = { accepted, duplicated: 0, rejected };
    batchArchive.set(key, result);
    return HttpResponse.json({ ...result, deduplicated: false });
  }),
];
```

**handlers.ts 聚合追加** `eventHandlers`（import + 数组展开）。

**新建** `apps/web/src/mocks/handlers/events.test.ts`：

```ts
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { setupServer } from "msw/node";
import { handlers } from "../handlers";
import { OBJ_ORDER_B } from "../data/ids";

const server = setupServer(...handlers);
const BASE = "http://mock.test";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("events handlers", () => {
  it("risk_level=P1 过滤：total=3（B/E/J）", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/events?risk_level=P1`)).json()) as {
      items: { risk_level: string }[];
      total: number;
    };
    expect(body.total).toBe(3);
    expect(body.items.every((e) => e.risk_level === "P1")).toBe(true);
  });

  it("occurred_at DESC 排序", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/events?limit=10`)).json()) as { items: { occurred_at: string }[] };
    const times = body.items.map((e) => e.occurred_at);
    expect([...times].sort().reverse()).toEqual(times);
  });

  it("batch：缺 Idempotency-Key → 400；入库 accepted；重放 deduplicated=true", async () => {
    const noKey = await fetch(`${BASE}/api/v1/events/batch`, {
      method: "POST",
      body: JSON.stringify({ events: [] }),
    });
    expect(noKey.status).toBe(400);

    const payload = {
      events: [
        {
          event_type: "capability.result.order_risk",
          object_id: OBJ_ORDER_B,
          source_system: "agent-hub",
          occurred_at: "2026-09-28T08:00:00.000Z",
          actor_type: "AI" as const,
          actor_id: "agent:test",
          risk_level: "P2" as const,
          score: 0.5,
          data: { reason: "batch 写入测试" },
        },
      ],
    };
    const r1 = await fetch(`${BASE}/api/v1/events/batch`, {
      method: "POST",
      headers: { "Idempotency-Key": "test-key-1" },
      body: JSON.stringify(payload),
    });
    expect(await r1.json()).toMatchObject({ accepted: 1, duplicated: 0, rejected: 0, deduplicated: false });

    const r2 = await fetch(`${BASE}/api/v1/events/batch`, {
      method: "POST",
      headers: { "Idempotency-Key": "test-key-1" },
      body: JSON.stringify(payload),
    });
    expect(await r2.json()).toMatchObject({ accepted: 1, deduplicated: true });

    // 入库后 P2 计数 4 → 5
    const list = (await (await fetch(`${BASE}/api/v1/events?risk_level=P2`)).json()) as { total: number };
    expect(list.total).toBe(5);
  });

  it("since 闭区间过滤", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/events?since=2026-09-28T05:00:00.000Z`)).json()) as {
      items: { occurred_at: string }[];
    };
    expect(body.items.every((e) => e.occurred_at >= "2026-09-28T05:00:00.000Z")).toBe(true);
  });
});
```

（P2 基线 = C 延迟、PRJD 就绪、I 双记录、PLM 失败 = 4 条。）

**验证**：`cd frontend; pnpm --filter web test src/mocks`

**Commit**: `feat(w2): mocks events handlers（过滤/分页/批量幂等）`

## Task 10: handlers/evidence.ts

**新建** `apps/web/src/mocks/handlers/evidence.ts`：

```ts
import { http, HttpResponse } from "msw";
import { clampLimit, paginate } from "../lib/cursor";
import { errorOf } from "../lib/http";
import { scenarioResponse } from "../lib/scenario";
import { evidence } from "../data/evidence";
import { SYNC_ID } from "../data/ids";
import { iso } from "../lib/demo-time";

function sortedAll() {
  return [...evidence].sort((a, b) => b.captured_at.localeCompare(a.captured_at));
}

export const evidenceHandlers = [
  // B.4 GET /evidence：object_id / ref_type+ref_id（links 命中，逆向追溯链图）过滤
  http.get("*/api/v1/evidence", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const q = new URL(request.url).searchParams;
    const refType = q.get("ref_type");
    const refId = q.get("ref_id");
    const objectId = q.get("object_id");
    const filtered = sortedAll().filter((e) => {
      if (objectId && e.object_id !== objectId) return false;
      if (refType && refId && !(e.links ?? []).some((l) => l.ref_type === refType && l.ref_id === refId)) return false;
      return true;
    });
    return HttpResponse.json(paginate(filtered, clampLimit(q.get("limit")), q.get("cursor")));
  }),

  // B.4 GET /evidence/{id}
  http.get("*/api/v1/evidence/:evidenceId", ({ params }) => {
    const found = evidence.find((e) => e.evidence_id === String(params.evidenceId));
    if (!found) return errorOf("NOT_FOUND", "资源不存在", 404);
    return HttpResponse.json(found);
  }),

  // B.4 GET /evidence/{id}/verify：mock 恒 valid=true（篡改检测由后端 EDP-008 实现）
  http.get("*/api/v1/evidence/:evidenceId/verify", ({ params }) => {
    const found = evidence.find((e) => e.evidence_id === String(params.evidenceId));
    if (!found) return errorOf("NOT_FOUND", "资源不存在", 404);
    return HttpResponse.json({ evidence_id: found.evidence_id, valid: true, verified_at: iso("2026-09-28T08:30:00Z") });
  }),

  // mock 自有（EDP-030 落地后替换）：重索引三步向导执行
  http.post("*/api/v1/admin/evidence/reindex", () =>
    HttpResponse.json({ sync_id: SYNC_ID, status: "RUNNING", started_at: iso("2026-09-28T08:30:00Z") }, { status: 202 }),
  ),
];
```

**handlers.ts 聚合追加** `evidenceHandlers`。

**新建** `apps/web/src/mocks/handlers/evidence.test.ts`：

```ts
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { setupServer } from "msw/node";
import { handlers } from "../handlers";
import { CASE_ORDER_B, EVID_ORDER_B_SNAPSHOT } from "../data/ids";

const server = setupServer(...handlers);
const BASE = "http://mock.test";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("evidence handlers", () => {
  it("总量 20（KPI 证据数量数据源）", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/evidence?limit=1`)).json()) as { total: number };
    expect(body.total).toBe(20);
  });

  it("ref_type=CASE&ref_id=订单B案例 → 4 份链上证据（订单/库存/PO/交期）", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/evidence?ref_type=CASE&ref_id=${CASE_ORDER_B}`)).json()) as { total: number };
    expect(body.total).toBe(4);
  });

  it("verify → valid=true", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/evidence/${EVID_ORDER_B_SNAPSHOT}/verify`)).json()) as { valid: boolean };
    expect(body.valid).toBe(true);
  });

  it("reindex → 202 RUNNING", async () => {
    const resp = await fetch(`${BASE}/api/v1/admin/evidence/reindex`, { method: "POST", body: JSON.stringify({ scope: "ALL" }) });
    expect(resp.status).toBe(202);
    expect(await resp.json()).toMatchObject({ status: "RUNNING" });
  });
});
```

**验证**：`cd frontend; pnpm --filter web test src/mocks`

**Commit**: `feat(w2): mocks evidence handlers（链图追溯/verify/重索引）`

## Task 11: handlers/quality.ts

**新建** `apps/web/src/mocks/handlers/quality.ts`：

```ts
import { http, HttpResponse } from "msw";
import { errorOf } from "../lib/http";
import { scenarioResponse } from "../lib/scenario";
import { coverageReport, qualityReport } from "../data/quality";
import type { QualityTask } from "../types";
import { minutesBefore } from "../lib/demo-time";

/** mock 自有：任务存储（会话内）。 */
const tasks = new Map<string, QualityTask>();

function newTask(taskType: string): QualityTask {
  const task: QualityTask = {
    task_id: `TASK-20260928-${String(tasks.size + 1).padStart(4, "0")}`,
    task_type: taskType,
    status: "RUNNING",
    started_at: minutesBefore(2),
    logs: [
      { ts: minutesBefore(2), level: "INFO", message: "任务启动：重校验（完整性/一致性/时效性/唯一性）" },
      { ts: minutesBefore(1), level: "INFO", message: "完整性校验通过：ORDER 1180/1180" },
      { ts: minutesBefore(1), level: "WARN", message: "一致性告警：CUSTOMER 双记录 1 处（宏达精密 C-030）" },
    ],
  };
  tasks.set(task.task_id, task);
  return task;
}

export const qualityHandlers = [
  // B.13 GET /admin/quality/reports（?date= 缺省用报告日期）
  http.get("*/api/v1/admin/quality/reports", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const date = new URL(request.url).searchParams.get("date");
    return HttpResponse.json(date ? { ...qualityReport, date } : qualityReport);
  }),

  // B.13 GET /admin/quality/coverage（Go/No-Go 周报简报）
  http.get("*/api/v1/admin/quality/coverage", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    return HttpResponse.json(coverageReport);
  }),

  // mock 自有（EDP-030 落地后替换）：重校验弹窗提交
  http.post("*/api/v1/admin/quality/rechecks", async ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const body = (await request.json().catch(() => ({}))) as { scope?: string };
    const task = newTask(`quality-recheck:${body.scope ?? "ALL"}`);
    return HttpResponse.json({ task_id: task.task_id, status: task.status, started_at: task.started_at }, { status: 202 });
  }),

  // mock 自有：任务详情（任务日志抽屉）
  http.get("*/api/v1/admin/quality/tasks/:taskId", ({ params }) => {
    const task = tasks.get(String(params.taskId));
    if (!task) return errorOf("NOT_FOUND", "任务不存在", 404);
    return HttpResponse.json(task);
  }),
];
```

**handlers.ts 聚合追加** `qualityHandlers`。

**新建** `apps/web/src/mocks/handlers/quality.test.ts`：

```ts
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { setupServer } from "msw/node";
import { handlers } from "../handlers";

const server = setupServer(...handlers);
const BASE = "http://mock.test";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("quality handlers", () => {
  it("reports：overall 96.8、对账 5 行、维度 5 组、KPI 待处理 7", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/admin/quality/reports`)).json()) as {
      coverage: { overall_pct: number };
      reconciliation: unknown[];
      dimensions: unknown[];
      kpi: { pending_exceptions: number; high_priority: number };
    };
    expect(body.coverage.overall_pct).toBe(96.8);
    expect(body.reconciliation).toHaveLength(5);
    expect(body.dimensions).toHaveLength(5);
    expect(body.kpi.pending_exceptions).toBe(7);
    expect(body.kpi.high_priority).toBe(4);
  });

  it("coverage 简报结构", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/admin/quality/coverage`)).json()) as { overall_pct: number; by_type: unknown[] };
    expect(body.overall_pct).toBe(96.8);
    expect(body.by_type.length).toBeGreaterThanOrEqual(6);
  });

  it("重校验 → 202 + 任务详情可查（日志含 WARN 行）", async () => {
    const resp = await fetch(`${BASE}/api/v1/admin/quality/rechecks`, {
      method: "POST",
      body: JSON.stringify({ dimensions: ["完整性", "一致性"], scope: "ALL" }),
    });
    expect(resp.status).toBe(202);
    const { task_id } = (await resp.json()) as { task_id: string };
    expect(task_id).toMatch(/^TASK-20260928-\d{4}$/);

    const detail = (await (await fetch(`${BASE}/api/v1/admin/quality/tasks/${task_id}`)).json()) as {
      status: string;
      logs: { level: string }[];
    };
    expect(detail.status).toBe("RUNNING");
    expect(detail.logs.some((l) => l.level === "WARN")).toBe(true);
  });

  it("任务 404", async () => {
    const resp = await fetch(`${BASE}/api/v1/admin/quality/tasks/TASK-20260928-9999`);
    expect(resp.status).toBe(404);
  });
});
```

**验证**：`cd frontend; pnpm --filter web test src/mocks`

**Commit**: `feat(w2): mocks quality handlers（报告/覆盖率/重校验/任务日志）`

## Task 12: handlers/health.ts + handlers/adapters.ts

**新建** `apps/web/src/mocks/handlers/health.ts`：

```ts
import { http, HttpResponse } from "msw";
import { scenarioResponse } from "../lib/scenario";
import { health, outboxStatus } from "../data/health";

export const healthHandlers = [
  // B.13 GET /api/v1/health（deep 字段始终返回；?deep=true 的 ADMIN 鉴权由后端实现，mock 不校验）
  http.get("*/api/v1/health", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    return HttpResponse.json(health);
  }),

  // B.13 GET /admin/outbox/status
  http.get("*/api/v1/admin/outbox/status", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    return HttpResponse.json(outboxStatus);
  }),
];
```

**新建** `apps/web/src/mocks/handlers/adapters.ts`：

```ts
import { http, HttpResponse } from "msw";
import { errorOf } from "../lib/http";
import { scenarioResponse } from "../lib/scenario";
import { adapters } from "../data/adapters";
import { SYNC_ID } from "../data/ids";
import { iso } from "../lib/demo-time";

const SYNC_MODES = new Set(["incremental", "full", "replay"]);

export const adapterHandlers = [
  // B.12 GET /admin/adapters：全部适配器清单与运行状态
  http.get("*/api/v1/admin/adapters", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    return HttpResponse.json({ items: adapters, next_cursor: null, total: adapters.length });
  }),

  // B.12 GET /admin/adapters/{name}/status（404 未知适配器）
  http.get("*/api/v1/admin/adapters/:adapterName/status", ({ params, request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const found = adapters.find((a) => a.adapter === String(params.adapterName));
    if (!found) return errorOf("NOT_FOUND", "适配器不存在", 404);
    return HttpResponse.json({
      adapter: found.adapter,
      mode: found.mode,
      last_sync: {
        sync_id: SYNC_ID,
        finished_at: found.last_sync,
        stats: { fetched: 1200, registered: 1180, duplicated: 20, failed: found.health === "DEGRADED" ? 3 : 0 },
      },
      health: found.health,
    });
  }),

  // B.12 POST /admin/adapters/{name}/sync（mode 含 replay——事件回放向导承载，13.6.2）→ 202
  http.post("*/api/v1/admin/adapters/:adapterName/sync", async ({ params, request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const found = adapters.find((a) => a.adapter === String(params.adapterName));
    if (!found) return errorOf("NOT_FOUND", "适配器不存在", 404);
    const body = (await request.json().catch(() => ({}))) as { mode?: string };
    if (!body.mode || !SYNC_MODES.has(body.mode)) {
      return errorOf("VALIDATION_ERROR", "mode 必须为 incremental/full/replay", 400);
    }
    return HttpResponse.json({ sync_id: SYNC_ID, status: "RUNNING", started_at: iso("2026-09-28T08:30:00Z") }, { status: 202 });
  }),
];
```

**handlers.ts 聚合追加** `healthHandlers` 与 `adapterHandlers`。

**新建** `apps/web/src/mocks/handlers/health.test.ts`：

```ts
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { setupServer } from "msw/node";
import { handlers } from "../handlers";
import { SYNC_ID } from "../data/ids";

const server = setupServer(...handlers);
const BASE = "http://mock.test";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("health & adapters handlers", () => {
  it("health：HA 角色 primary + 备份恢复验证 PASSED + ops_metrics", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/health?deep=true`)).json()) as {
      db_ha: { role: string };
      backup?: { last_restore_verify: string };
      ops_metrics?: { p95_latency_ms: number; evidence_count: number };
    };
    expect(body.db_ha.role).toBe("primary");
    expect(body.backup?.last_restore_verify).toBe("PASSED");
    expect(body.ops_metrics?.evidence_count).toBe(20);
    expect(body.ops_metrics?.p95_latency_ms).toBeLessThan(2000);
  });

  it("outbox status：pending=3 failed=0", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/admin/outbox/status`)).json()) as { pending: number; failed: number };
    expect(body).toMatchObject({ pending: 3, failed: 0 });
  });

  it("adapters 清单：5 个，plm 降级", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/admin/adapters`)).json()) as {
      items: { adapter: string; health: string }[];
      total: number;
    };
    expect(body.total).toBe(5);
    expect(body.items.find((a) => a.adapter === "plm")?.health).toBe("DEGRADED");
  });

  it("sync：replay 模式 202 RUNNING；非法 mode 400；未知适配器 404", async () => {
    const ok = await fetch(`${BASE}/api/v1/admin/adapters/erp/sync`, {
      method: "POST",
      body: JSON.stringify({ mode: "replay", since: "2026-09-28T00:00:00Z" }),
    });
    expect(ok.status).toBe(202);
    expect(await ok.json()).toMatchObject({ sync_id: SYNC_ID, status: "RUNNING" });

    const bad = await fetch(`${BASE}/api/v1/admin/adapters/erp/sync`, {
      method: "POST",
      body: JSON.stringify({ mode: "whatever" }),
    });
    expect(bad.status).toBe(400);

    const missing = await fetch(`${BASE}/api/v1/admin/adapters/nope/sync`, {
      method: "POST",
      body: JSON.stringify({ mode: "full" }),
    });
    expect(missing.status).toBe(404);
  });
});
```

**验证**：`cd frontend; pnpm --filter web test src/mocks`

**Commit**: `feat(w2): mocks health/adapters handlers（deep 健康/Outbox/同步触发）`

## Task 13: handlers/ebms.ts + handlers/audit.ts

**新建** `apps/web/src/mocks/handlers/ebms.ts`：

```ts
import { http, HttpResponse } from "msw";
import { clampLimit, paginate } from "../lib/cursor";
import { scenarioResponse } from "../lib/scenario";
import { exceptions } from "../data/ebms";
import { EVT_ORDER_I_DQ } from "../data/ids";

/** B.9 mock 约定（data/ebms.ts 注释）：EVT_ORDER_I_DQ = RESOLVED，其余 OPEN。 */
const RESOLVED_EVENT = EVT_ORDER_I_DQ;

function isOpen(item: { event_id: string }): boolean {
  return item.event_id !== RESOLVED_EVENT;
}

export const ebmsHandlers = [
  // B.9 GET /ebms/exceptions：severity/status 过滤 + 分页（occurred_at DESC）
  http.get("*/api/v1/ebms/exceptions", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const q = new URL(request.url).searchParams;
    const status = q.get("status") ?? "OPEN";
    const filtered = [...exceptions]
      .sort((a, b) => b.occurred_at.localeCompare(a.occurred_at))
      .filter((e) => {
        if (q.get("severity") && e.risk_level !== q.get("severity")) return false;
        if (status === "OPEN" && !isOpen(e)) return false;
        if (status === "RESOLVED" && isOpen(e)) return false;
        return true;
      });
    return HttpResponse.json(paginate(filtered, clampLimit(q.get("limit"), 20, 100), q.get("cursor")));
  }),
];
```

**新建** `apps/web/src/mocks/handlers/audit.ts`：

```ts
import { http, HttpResponse } from "msw";
import { clampLimit, paginate } from "../lib/cursor";
import { errorOf } from "../lib/http";
import { scenarioResponse } from "../lib/scenario";
import { auditLogs } from "../data/audit";

export const auditHandlers = [
  // B.6 GET /audit-logs：actor_id/resource_type/action/since/until 过滤（对齐导出弹窗字段）+ 分页
  http.get("*/api/v1/audit-logs", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    const q = new URL(request.url).searchParams;
    const filtered = [...auditLogs]
      .sort((a, b) => b.occurred_at.localeCompare(a.occurred_at) || b.audit_id - a.audit_id)
      .filter((a) => {
        if (q.get("actor_id") && a.actor_id !== q.get("actor_id")) return false;
        if (q.get("resource_type") && a.resource_type !== q.get("resource_type")) return false;
        if (q.get("action") && a.action !== q.get("action")) return false;
        if (q.get("since") && a.occurred_at < q.get("since")!) return false;
        if (q.get("until") && a.occurred_at > q.get("until")!) return false;
        return true;
      });
    return HttpResponse.json(paginate(filtered, clampLimit(q.get("limit")), q.get("cursor")));
  }),

  // B.6 GET /audit-logs/{audit_id}
  http.get("*/api/v1/audit-logs/:auditId", ({ params }) => {
    const id = Number(params.auditId);
    const found = auditLogs.find((a) => a.audit_id === id);
    if (!found) return errorOf("NOT_FOUND", "审计条目不存在", 404);
    return HttpResponse.json(found);
  }),
];
```

**handlers.ts 聚合最终形态**：

```ts
import { adapterHandlers } from "./handlers/adapters";
import { auditHandlers } from "./handlers/audit";
import { authHandlers } from "./handlers/auth";
import { ebmsHandlers } from "./handlers/ebms";
import { eventHandlers } from "./handlers/events";
import { evidenceHandlers } from "./handlers/evidence";
import { healthHandlers } from "./handlers/health";
import { qualityHandlers } from "./handlers/quality";
import { registryHandlers } from "./handlers/registry";
import { tenantHandlers } from "./handlers/tenant";

/** W2+W3 六页 MSW 数据层聚合（spec §3 端点清单：27 个 handler，含 T13-fix 补充的 tenants/current）。 */
export const handlers = [
  ...authHandlers,
  ...tenantHandlers,
  ...registryHandlers,
  ...eventHandlers,
  ...evidenceHandlers,
  ...qualityHandlers,
  ...healthHandlers,
  ...adapterHandlers,
  ...ebmsHandlers,
  ...auditHandlers,
];
```

**新建** `apps/web/src/mocks/handlers/ebms.test.ts`：

```ts
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { setupServer } from "msw/node";
import { handlers } from "../handlers";

const server = setupServer(...handlers);
const BASE = "http://mock.test";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("ebms & audit handlers", () => {
  it("异常默认 OPEN：7 条；P1 过滤：3 条", async () => {
    const open = (await (await fetch(`${BASE}/api/v1/ebms/exceptions`)).json()) as { total: number };
    expect(open.total).toBe(7);
    const p1 = (await (await fetch(`${BASE}/api/v1/ebms/exceptions?severity=P1`)).json()) as { total: number };
    expect(p1.total).toBe(3);
  });

  it("status=RESOLVED：仅场景 8（数据不一致）1 条", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/ebms/exceptions?status=RESOLVED`)).json()) as {
      items: { result_type: string }[];
      total: number;
    };
    expect(body.total).toBe(1);
    expect(body.items[0].result_type).toBe("DATA_QUALITY");
  });

  it("P1 前 3 条用于总览风险列表（limit=3）", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/ebms/exceptions?severity=P1&limit=3`)).json()) as {
      items: { risk_level: string }[];
    };
    expect(body.items).toHaveLength(3);
    expect(body.items.every((i) => i.risk_level === "P1")).toBe(true);
  });

  it("audit-logs：action=GUARD_DENIED → 2 条（越权举证）", async () => {
    const body = (await (await fetch(`${BASE}/api/v1/audit-logs?action=GUARD_DENIED`)).json()) as { total: number };
    expect(body.total).toBe(2);
  });

  it("audit-logs 点查与 404", async () => {
    const found = await fetch(`${BASE}/api/v1/audit-logs/10230`);
    expect(found.status).toBe(200);
    const missing = await fetch(`${BASE}/api/v1/audit-logs/99999`);
    expect(missing.status).toBe(404);
  });
});
```

**验证**：`cd frontend; pnpm --filter web test src/mocks`

**Commit**: `feat(w2): mocks ebms/audit handlers（异常过滤/审计追溯）并完成聚合`

## Task 14: 跨页一致性测试

**新建** `apps/web/src/mocks/data/consistency.test.ts`：

```ts
import { describe, expect, it } from "vitest";
import { auditLogs } from "./audit";
import { adapters } from "./adapters";
import { evidence } from "./evidence";
import { events } from "./events";
import { exceptions } from "./ebms";
import { health } from "./health";
import { objects } from "./objects";
import { qualityReport } from "./quality";
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
});
```

**验证**：`cd frontend; pnpm --filter web test src/mocks`

**Commit**: `test(w2): mocks fixtures 跨页一致性断言`

## Task 15: 全量验证与 MSW 模式冒烟

1. **全量门禁**（对齐 Makefile verify-all 的前端部分）：

```powershell
cd frontend; pnpm -r lint; pnpm -r test; pnpm --filter web build
```

全部通过；`apps/web/public/mockServiceWorker.js` 已由 msw 生成（W1 已有，不重建）。

2. **浏览器冒烟**（人工，验证后记录结果）：

```powershell
cd frontend\apps\web; $env:VITE_USE_MSW=1; pnpm dev
```

- 登录 `manager1`（任意密码）→ 进入壳层；
- 页面控制台执行 `fetch('/api/v1/events?risk_level=P1').then(r=>r.json()).then(console.log)` 应返回 3 条 P1 事件（worker 拦截生效）。

3. **还原现场**：清环境变量；确认 `git status` 中本工作系列文件均已提交，未误提交他人改动（设计文档/Sidebar/permissions/.idea 仍保持未提交）。

**Commit**（如有收尾修正）: `chore(w2): mocks 全量验证收尾`

---

## 附录：任务 → spec 条款对照

| Task | spec 条款 |
|---|---|
| 2-3 | §5.1 目录结构、§3 端点清单（类型） |
| 4-7 | §4 数据故事（十类场景 → fixtures） |
| 8 | §3.1 冻结契约 registry/auth |
| 9 | §3.1 冻结契约 events（幂等语义 §5.2） |
| 10-11 | §3.2 未冻结契约 B.4/B.13 + §3.3 mock 自有端点 |
| 12-13 | §3.2 未冻结契约 B.12/B.13/B.9/B.6 |
| 14 | §4 跨页一致性约束（测试断言清单） |
| 15 | §5.3 测试与 mode 切换验证 |
