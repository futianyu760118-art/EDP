/**
 * 13.4.4 枚举统一锁定测试（刻意硬编码期望值，防止与后端种子/设计文档漂移）。
 */
import { describe, expect, it } from "vitest";
import {
  PLAN_LABELS,
  RISK_LEVEL_LABELS,
  ROLE_LABELS,
  TENANT_STATUS_LABELS,
  planLabel,
  roleLabel,
} from "./index";

describe("ROLE_LABELS 五角色中文（13.4.4，与 0005 种子一致）", () => {
  it("五角色齐全且无多余键", () => {
    expect(ROLE_LABELS).toEqual({
      PLATFORM_ADMIN: "平台运营",
      ADMIN: "工作空间管理员",
      MANAGER: "数据管理员·业务负责人",
      ANALYST: "审计员·操作员",
      SERVICE: "服务主体",
    });
  });

  it("roleLabel：已知角色 → 中文名；未知回显原码；空 → 空串", () => {
    expect(roleLabel("MANAGER")).toBe("数据管理员·业务负责人");
    expect(roleLabel("GHOST_ROLE")).toBe("GHOST_ROLE");
    expect(roleLabel(undefined)).toBe("");
  });
});

describe("TENANT_STATUS_LABELS 租户状态四值 + tone", () => {
  it("与迁移 0001 CHECK 约束的四状态一一对应", () => {
    expect(Object.keys(TENANT_STATUS_LABELS).sort()).toEqual([
      "ACTIVE",
      "CANCELLED",
      "PROVISIONING",
      "SUSPENDED",
    ]);
  });

  it("语义色：正常=success、已暂停=warning、开通中=info、已注销=muted", () => {
    expect(TENANT_STATUS_LABELS.ACTIVE).toEqual({ label: "正常", tone: "success" });
    expect(TENANT_STATUS_LABELS.SUSPENDED.tone).toBe("warning");
    expect(TENANT_STATUS_LABELS.PROVISIONING.tone).toBe("info");
    expect(TENANT_STATUS_LABELS.CANCELLED.tone).toBe("muted");
  });
});

describe("RISK_LEVEL_LABELS 风险等级 P 系 + tone", () => {
  it("P0~P3 齐全且紧急度递减映射 error→warning→info", () => {
    expect(Object.keys(RISK_LEVEL_LABELS)).toEqual(["P0", "P1", "P2", "P3"]);
    expect(RISK_LEVEL_LABELS.P0).toEqual({ label: "P0 · 紧急", tone: "error" });
    expect(RISK_LEVEL_LABELS.P1.tone).toBe("error");
    expect(RISK_LEVEL_LABELS.P2.tone).toBe("warning");
    expect(RISK_LEVEL_LABELS.P3.tone).toBe("info");
  });
});

describe("PLAN_LABELS 套餐四档（13.4.4）", () => {
  it("TRIAL/STANDARD/PREMIUM/DEDICATED → 体验/基础/专业/企业版", () => {
    expect(PLAN_LABELS).toEqual({
      TRIAL: "体验版",
      STANDARD: "基础版",
      PREMIUM: "专业版",
      DEDICATED: "企业版",
    });
  });

  it("planLabel：未知回显原码；空 → 基础版缺省", () => {
    expect(planLabel("PREMIUM")).toBe("专业版");
    expect(planLabel("CUSTOM")).toBe("CUSTOM");
    expect(planLabel(undefined)).toBe("基础版");
  });
});
