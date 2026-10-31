/**
 * 13.9.2 错误码→文案/呈现映射测试（刻意硬编码期望键集，防止与设计文档漂移）。
 */
import { describe, expect, it } from "vitest";
import { ERROR_SPECS, errorSpec } from "./index";

describe("ERROR_SPECS 14 键全集（13 错误码 + NETWORK_ERROR 扩展）", () => {
  it("键集恰为 13.9.2 列表，无多余无缺失", () => {
    expect(Object.keys(ERROR_SPECS).sort()).toEqual([
      "CONFLICT",
      "FORBIDDEN",
      "GUARD_POLICY_DENIED",
      "INTERNAL",
      "INVALID_TRANSITION",
      "METHOD_NOT_ALLOWED",
      "NETWORK_ERROR",
      "NOT_FOUND",
      "RATE_LIMITED",
      "TENANT_FORBIDDEN",
      "TENANT_SUSPENDED",
      "UNAUTHENTICATED",
      "UPSTREAM_UNAVAILABLE",
      "VALIDATION_ERROR",
    ]);
  });

  it("每个错误码 message 非空", () => {
    for (const [code, spec] of Object.entries(ERROR_SPECS)) {
      expect(spec.message.length, code).toBeGreaterThan(0);
    }
  });

  it("TENANT_SUSPENDED → banner 常驻横幅", () => {
    expect(errorSpec("TENANT_SUSPENDED").presentation).toBe("banner");
  });

  it("errorSpec 兜底：undefined/未知码 → INTERNAL", () => {
    expect(errorSpec(undefined).message).toBe(ERROR_SPECS.INTERNAL.message);
    expect(errorSpec("GHOST_CODE").message).toBe(ERROR_SPECS.INTERNAL.message);
    expect(errorSpec(null).message).toBe(ERROR_SPECS.INTERNAL.message);
  });
});
