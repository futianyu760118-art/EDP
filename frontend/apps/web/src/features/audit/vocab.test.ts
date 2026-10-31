import { describe, expect, it } from "vitest";
import {
  ACTION_LABELS,
  deriveActionLabel,
  resolveResourceType,
  severityOfAction,
} from "./vocab";

describe("审计词表：显式常量全集（aspect.py 实测 + ratelimit 两常量）", () => {
  it("record_explicit 显式枚举逐字命中", () => {
    expect(ACTION_LABELS["RATE_LIMITED"]).toBe("限流拒绝");
    expect(deriveActionLabel("RATE_LIMITED")).toBe("限流拒绝");
    expect(deriveActionLabel("RATE_LIMIT_WARNING")).toBe("限流预警");
    expect(deriveActionLabel("GUARD_DENIED")).toBe("越权拦截");
    expect(deriveActionLabel("EVIDENCE_VERIFY_FAILED")).toBe("证据校验失败");
    expect(deriveActionLabel("TRACE_CREATE")).toBe("链路创建");
    expect(deriveActionLabel("EVENT_CREATE")).toBe("事件创建");
    expect(deriveActionLabel("LOGIN")).toBe("登录");
  });

  it("{PREFIX}_{VERB} 前缀派生：前缀字典 + 动词直出", () => {
    expect(deriveActionLabel("CASE_CREATE")).toBe("案例创建");
    expect(deriveActionLabel("EVIDENCE_UPDATE")).toBe("证据更新");
    expect(deriveActionLabel("OBJECT_DELETE")).toBe("对象删除");
    expect(deriveActionLabel("ACTION_UPDATE")).toBe("行动更新");
    expect(deriveActionLabel("POLICY_CREATE")).toBe("策略创建");
    expect(deriveActionLabel("POLICY_UPDATE")).toBe("策略更新");
    expect(deriveActionLabel("OBJECT_UPSERT")).toBe("对象写入");
    // 裸动词变体（CASE_CREATED）与复合动词（SYNC_FAILED）同归一词
    expect(deriveActionLabel("CASE_CREATED")).toBe("案例创建");
    expect(deriveActionLabel("ADAPTER_SYNC_FAILED")).toBe("适配器同步失败");
    expect(deriveActionLabel("EVENT_BATCH_INGEST")).toBe("事件批量写入");
  });

  it("未命中回退原文（词表不臆造）", () => {
    expect(deriveActionLabel("MYSTERY_ACTION")).toBe("MYSTERY_ACTION");
  });
});

describe("resolveResourceType：裸名 → 全名（W3-13 records 歧义收口）", () => {
  it("fullname（含点）原样返回", () => {
    expect(resolveResourceType("evidence.records", "CASE_CREATE")).toBe("evidence.records");
    expect(resolveResourceType("decision.records", "EVIDENCE_CREATE")).toBe("decision.records");
    expect(resolveResourceType("adapters.sync")).toBe("adapters.sync");
  });

  it("records 裸名按 action 前缀消歧：EVIDENCE_* vs DECISION_*/CASE_*", () => {
    expect(resolveResourceType("records", "EVIDENCE_CREATE")).toBe("evidence.records");
    expect(resolveResourceType("records", "CASE_CREATE")).toBe("decision.records");
    expect(resolveResourceType("records", "DECISION_UPDATE")).toBe("decision.records");
    // 缺省回退 EVIDENCE（与 aspect 裸名回退一致）
    expect(resolveResourceType("records")).toBe("evidence.records");
  });

  it("其余裸名查 RESOURCE_LABELS，未命中回退原文", () => {
    expect(resolveResourceType("events", "EVENT_CREATE")).toBe("event.events");
    expect(resolveResourceType("business_objects")).toBe("master.business_objects");
    expect(resolveResourceType("cases")).toBe("decision.cases");
    expect(resolveResourceType("actions")).toBe("action.actions");
    expect(resolveResourceType("unknown_table")).toBe("unknown_table");
  });
});

describe("severityOfAction：GUARD 高亮 / 级别列共用三档", () => {
  it("拒绝（error）/ 预警（warning）/ 成功（success）", () => {
    expect(severityOfAction("GUARD_DENIED")).toBe("error");
    expect(severityOfAction("RATE_LIMITED")).toBe("error");
    expect(severityOfAction("EVIDENCE_VERIFY_FAILED")).toBe("error");
    expect(severityOfAction("RATE_LIMIT_WARNING")).toBe("warning");
    expect(severityOfAction("LOGIN")).toBe("success");
    expect(severityOfAction("EVENT_CREATE")).toBe("success");
  });
});
