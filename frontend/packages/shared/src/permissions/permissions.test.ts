/**
 * 13.8 导航权限矩阵测试（设计文档 13.6.5 导航权限行 + 13.5 闭环组规则）。
 */
import { describe, expect, it } from "vitest";
import { NAV_GROUP_RULES, canSeeGroup } from "./index";

describe("NAV_GROUP_RULES 四组矩阵", () => {
  it("数据工作台/运维监控全角色；平台配置仅 PLATFORM_ADMIN；闭环组 ADMIN+", () => {
    expect(NAV_GROUP_RULES.workbench).toBe("all");
    expect(NAV_GROUP_RULES.ops_monitor).toBe("all");
    expect(NAV_GROUP_RULES.platform_config).toEqual(["PLATFORM_ADMIN"]);
    expect(NAV_GROUP_RULES.closed_loop).toEqual(["PLATFORM_ADMIN", "ADMIN"]);
  });
});

describe("canSeeGroup", () => {
  it("全角色组：任何角色（含空角色）可见", () => {
    for (const group of ["workbench", "ops_monitor"] as const) {
      expect(canSeeGroup(group, [], false)).toBe(true);
      expect(canSeeGroup(group, ["ANALYST"], false)).toBe(true);
      expect(canSeeGroup(group, ["SERVICE"], false)).toBe(true);
    }
  });

  it("平台配置：仅 PLATFORM_ADMIN 角色或 isPlatformAdmin 可见", () => {
    expect(canSeeGroup("platform_config", ["PLATFORM_ADMIN"], false)).toBe(true);
    expect(canSeeGroup("platform_config", ["ADMIN"], false)).toBe(false);
    expect(canSeeGroup("platform_config", ["ADMIN"], true)).toBe(true);
    expect(canSeeGroup("platform_config", [], false)).toBe(false);
  });

  it("智能闭环：PLATFORM_ADMIN/ADMIN 可见，MANAGER/ANALYST 不可见", () => {
    expect(canSeeGroup("closed_loop", ["ADMIN"], false)).toBe(true);
    expect(canSeeGroup("closed_loop", ["PLATFORM_ADMIN"], false)).toBe(true);
    expect(canSeeGroup("closed_loop", ["MANAGER", "ANALYST"], false)).toBe(false);
    expect(canSeeGroup("closed_loop", ["MANAGER"], true)).toBe(true);
  });

  it("多角色并集命中任一即可见", () => {
    expect(canSeeGroup("closed_loop", ["ANALYST", "ADMIN"], false)).toBe(true);
  });
});
