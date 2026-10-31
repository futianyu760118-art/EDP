import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { createClient } from "./client";
import {
  backoffDelay,
  createSingleFlight,
  createTenantSuspendedHandler,
} from "./interceptors";

const BASE = "http://api.test";
const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("backoffDelay 数值断言", () => {
  it("无 Retry-After：1s * 2^attempt", () => {
    expect(backoffDelay(0)).toBe(1000);
    expect(backoffDelay(1)).toBe(2000);
    expect(backoffDelay(2)).toBe(4000);
    expect(backoffDelay(3)).toBe(8000);
  });

  it("有 Retry-After（秒）：头值优先（换算毫秒），负数截 0", () => {
    expect(backoffDelay(0, 2)).toBe(2000);
    expect(backoffDelay(3, 0)).toBe(0);
    expect(backoffDelay(1, -5)).toBe(0);
  });
});

describe("createSingleFlight 刷新单飞", () => {
  it("并发调用共享同一 promise，fn 仅执行一次", async () => {
    let calls = 0;
    const fn = createSingleFlight(async (n: number) => {
      calls += 1;
      await new Promise((resolve) => setTimeout(resolve, 30));
      return n * 10;
    });
    const results = await Promise.all([fn(1), fn(2), fn(3)]);
    expect(calls).toBe(1);
    expect(results).toEqual([10, 10, 10]);
  });

  it("落定后再次调用会重新执行", async () => {
    let calls = 0;
    const fn = createSingleFlight(async () => {
      calls += 1;
      return calls;
    });
    expect(await fn()).toBe(1);
    expect(await fn()).toBe(2);
    expect(calls).toBe(2);
  });
});

describe("createTenantSuspendedHandler 横幅判定（13.8）", () => {
  it("403 + TENANT_SUSPENDED → 触发一次并返回 true", () => {
    const onSuspended = vi.fn();
    const judge = createTenantSuspendedHandler(onSuspended);
    const hit = judge(403, {
      error: { code: "TENANT_SUSPENDED", message: "租户已暂停", request_id: "r10" },
    });
    expect(hit).toBe(true);
    expect(onSuspended).toHaveBeenCalledTimes(1);
  });

  it("其他 403（别的错误码/无 code/非 JSON body）不触发", () => {
    const onSuspended = vi.fn();
    const judge = createTenantSuspendedHandler(onSuspended);
    expect(judge(403, { error: { code: "FORBIDDEN", message: "权限不足" } })).toBe(false);
    expect(judge(403, { error: { code: "TENANT_FORBIDDEN" } })).toBe(false);
    expect(judge(403, { error: {} })).toBe(false);
    expect(judge(403, null)).toBe(false);
    expect(onSuspended).not.toHaveBeenCalled();
  });

  it("非 403 的 TENANT_SUSPENDED body 不触发（状态码必须 403）", () => {
    const onSuspended = vi.fn();
    const judge = createTenantSuspendedHandler(onSuspended);
    expect(judge(401, { error: { code: "TENANT_SUSPENDED" } })).toBe(false);
    expect(judge(200, { error: { code: "TENANT_SUSPENDED" } })).toBe(false);
    expect(onSuspended).not.toHaveBeenCalled();
  });

  it("client 接线：业务响应 403+TENANT_SUSPENDED → onTenantSuspended 恰调一次并抛 EdpApiError", async () => {
    const onTenantSuspended = vi.fn();
    server.use(
      http.get(`${BASE}/api/v1/things`, () =>
        HttpResponse.json(
          {
            error: { code: "TENANT_SUSPENDED", message: "租户已暂停", request_id: "r11" },
          },
          { status: 403 },
        ),
      ),
    );
    const client = createClient({
      baseUrl: BASE,
      getAccessToken: () => "some-access",
      onTenantSuspended,
    });
    const err = await client.get("/api/v1/things").catch((e: unknown) => e);
    expect(err).toMatchObject({ status: 403, code: "TENANT_SUSPENDED" });
    expect(onTenantSuspended).toHaveBeenCalledTimes(1);
  });
});

describe("401 刷新单飞重放（13.9.2）", () => {
  it("并发 3 个 401 请求 → refresh 恰调 1 次 → 全部重放成功", async () => {
    let refreshCalls = 0;
    server.use(
      http.post(`${BASE}/api/v1/auth/refresh`, async () => {
        refreshCalls += 1;
        await new Promise((resolve) => setTimeout(resolve, 40));
        return HttpResponse.json({ access_token: "fresh-access", expires_in: 7200 });
      }),
      http.get(`${BASE}/api/v1/things`, ({ request }) => {
        if (request.headers.get("authorization") === "Bearer fresh-access") {
          return HttpResponse.json({ ok: true });
        }
        return HttpResponse.json(
          { error: { code: "UNAUTHENTICATED", message: "token 过期", request_id: "r1" } },
          { status: 401 },
        );
      }),
    );
    const setTokens = vi.fn();
    let currentAccessToken = "stale-access";
    const client = createClient({
      baseUrl: BASE,
      getAccessToken: () => currentAccessToken,
      getRefreshToken: () => "stale-refresh",
      setTokens: (tokens) => {
        setTokens(tokens);
        if (tokens) currentAccessToken = tokens.accessToken;
      },
    });
    const results = await Promise.all([
      client.get<{ ok: boolean }>("/api/v1/things"),
      client.get<{ ok: boolean }>("/api/v1/things"),
      client.get<{ ok: boolean }>("/api/v1/things"),
    ]);
    expect(refreshCalls).toBe(1);
    expect(results.map((r) => r.ok)).toEqual([true, true, true]);
    // RefreshResponse 不含 refresh_token（W1 契约无轮换）→ 沿用旧 refresh token
    expect(setTokens).toHaveBeenCalledWith({ accessToken: "fresh-access", refreshToken: "stale-refresh" });
  });

  it("refresh 失败 → setTokens(null) + onUnauthorized，原请求抛 401", async () => {
    server.use(
      http.post(`${BASE}/api/v1/auth/refresh`, () =>
        HttpResponse.json(
          { error: { code: "UNAUTHENTICATED", message: "刷新令牌无效", request_id: "r2" } },
          { status: 401 },
        ),
      ),
      http.get(`${BASE}/api/v1/things`, () =>
        HttpResponse.json(
          { error: { code: "UNAUTHENTICATED", message: "token 过期", request_id: "r3" } },
          { status: 401 },
        ),
      ),
    );
    const onUnauthorized = vi.fn();
    const setTokens = vi.fn();
    const client = createClient({
      baseUrl: BASE,
      getAccessToken: () => "stale-access",
      getRefreshToken: () => "stale-refresh",
      setTokens,
      onUnauthorized,
    });
    const err = await client.get("/api/v1/things").catch((e: unknown) => e);
    expect(err).toMatchObject({ status: 401, code: "UNAUTHENTICATED" });
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    expect(setTokens).toHaveBeenCalledWith(null);
  });

  it("重放仍 401 → 清会话 + onUnauthorized 并抛（不无限循环）", async () => {
    server.use(
      http.post(`${BASE}/api/v1/auth/refresh`, () =>
        HttpResponse.json({ access_token: "fresh-access", expires_in: 7200 }),
      ),
      http.get(`${BASE}/api/v1/things`, () =>
        HttpResponse.json(
          { error: { code: "UNAUTHENTICATED", message: "token 过期", request_id: "r4" } },
          { status: 401 },
        ),
      ),
    );
    const onUnauthorized = vi.fn();
    const setTokens = vi.fn();
    const client = createClient({
      baseUrl: BASE,
      getAccessToken: () => "stale-access",
      getRefreshToken: () => "stale-refresh",
      setTokens,
      onUnauthorized,
    });
    const err = await client.get("/api/v1/things").catch((e: unknown) => e);
    expect(err).toMatchObject({ status: 401, code: "UNAUTHENTICATED" });
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    expect(setTokens).toHaveBeenLastCalledWith(null);
  });
});

describe("429 Retry-After 退避（≤3 次）", () => {
  it("429 带 Retry-After=0 → 立即重试成功", async () => {
    let calls = 0;
    server.use(
      http.get(`${BASE}/api/v1/things`, () => {
        calls += 1;
        if (calls === 1) {
          return new HttpResponse(null, { status: 429, headers: { "Retry-After": "0" } });
        }
        return HttpResponse.json({ ok: true });
      }),
    );
    const client = createClient({ baseUrl: BASE });
    const data = await client.get<{ ok: boolean }>("/api/v1/things");
    expect(data.ok).toBe(true);
    expect(calls).toBe(2);
  });

  it("429 带 Retry-After=2 → 按头值退避后重试成功", async () => {
    let calls = 0;
    const sleeps: number[] = [];
    server.use(
      http.get(`${BASE}/api/v1/things`, () => {
        calls += 1;
        if (calls === 1) {
          return new HttpResponse(null, { status: 429, headers: { "Retry-After": "2" } });
        }
        return HttpResponse.json({ ok: true });
      }),
    );
    const client = createClient({
      baseUrl: BASE,
      sleep: async (ms) => {
        sleeps.push(ms);
      },
    });
    const data = await client.get<{ ok: boolean }>("/api/v1/things");
    expect(data.ok).toBe(true);
    expect(calls).toBe(2);
    expect(sleeps).toEqual([2000]);
  });

  it("429 连续 3 次重试仍失败 → 第 4 次请求后放弃并抛（无头退避 1s/2s/4s）", async () => {
    let calls = 0;
    const sleeps: number[] = [];
    server.use(
      http.get(`${BASE}/api/v1/things`, () => {
        calls += 1;
        return HttpResponse.json(
          { error: { code: "RATE_LIMITED", message: "请求过于频繁", request_id: "r9" } },
          { status: 429 },
        );
      }),
    );
    const client = createClient({
      baseUrl: BASE,
      sleep: async (ms) => {
        sleeps.push(ms);
      },
    });
    const err = await client.get("/api/v1/things").catch((e: unknown) => e);
    expect(err).toMatchObject({ status: 429, code: "RATE_LIMITED" });
    // 初始 1 次 + 重试 3 次
    expect(calls).toBe(4);
    expect(sleeps).toEqual([1000, 2000, 4000]);
  });
});
