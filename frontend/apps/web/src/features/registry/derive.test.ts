import { describe, expect, it } from "vitest";
import { DERIVED_TONE, deriveStatus, riskScore } from "./derive";

describe("deriveStatus 六分支（13.6.2 优先级序）", () => {
  it("P0 → Blocking；P1 → At Risk（先于 DQ/延迟）", () => {
    expect(deriveStatus({ riskLevel: "P0" })).toBe("Blocking");
    expect(deriveStatus({ riskLevel: "P1" })).toBe("At Risk");
    expect(deriveStatus({ riskLevel: "P1", hasDqException: true, syncLagHours: 100 })).toBe("At Risk");
  });

  it("无 P0/P1 时 DQ 异常 → DQ Exception（先于延迟/Watch）", () => {
    expect(deriveStatus({ hasDqException: true })).toBe("DQ Exception");
    expect(deriveStatus({ riskLevel: "P2", hasDqException: true })).toBe("DQ Exception");
    expect(deriveStatus({ hasDqException: true, syncLagHours: 100 })).toBe("DQ Exception");
  });

  it("同步滞后 >48h → Delayed；恰好 48h 不触发", () => {
    expect(deriveStatus({ syncLagHours: 48.01 })).toBe("Delayed");
    expect(deriveStatus({ syncLagHours: 72, riskLevel: "P2" })).toBe("Delayed");
    expect(deriveStatus({ syncLagHours: 48 })).toBe("Healthy");
  });

  it("P2/P3 → Watch；无任何信号 → Healthy", () => {
    expect(deriveStatus({ riskLevel: "P2" })).toBe("Watch");
    expect(deriveStatus({ riskLevel: "P3" })).toBe("Watch");
    expect(deriveStatus({})).toBe("Healthy");
    expect(deriveStatus({ riskLevel: null, hasDqException: false, syncLagHours: 0 })).toBe("Healthy");
  });

  it("DERIVED_TONE 六态全覆盖且映射符合语义", () => {
    expect(DERIVED_TONE.Healthy).toBe("success");
    expect(DERIVED_TONE.Watch).toBe("info");
    expect(DERIVED_TONE["At Risk"]).toBe("warning");
    expect(DERIVED_TONE.Blocking).toBe("error");
    expect(DERIVED_TONE["DQ Exception"]).toBe("warning");
    expect(DERIVED_TONE.Delayed).toBe("warning");
  });
});

describe("riskScore 档位（卡片进度条）", () => {
  it("P0=95 / P1=80 / P2=55 / P3=30 / 无=8", () => {
    expect(riskScore("P0")).toBe(95);
    expect(riskScore("P1")).toBe(80);
    expect(riskScore("P2")).toBe(55);
    expect(riskScore("P3")).toBe(30);
    expect(riskScore(undefined)).toBe(8);
    expect(riskScore(null)).toBe(8);
    expect(riskScore("PX")).toBe(8);
  });
});
