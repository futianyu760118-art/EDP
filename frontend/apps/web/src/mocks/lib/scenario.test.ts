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
