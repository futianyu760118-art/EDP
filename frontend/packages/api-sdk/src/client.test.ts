import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { createClient, EdpApiError } from "./client";

const BASE = "http://api.test";
const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function errorBody(code: string, message: string) {
  return { error: { code, message, request_id: "req-123" } };
}

describe("client 基础请求", () => {
  it("成功 JSON：GET 解析响应体并携带 Bearer 头", async () => {
    let seenAuth = "";
    server.use(
      http.get(`${BASE}/api/v1/things`, ({ request }) => {
        seenAuth = request.headers.get("authorization") ?? "";
        return HttpResponse.json({ items: [1, 2] });
      }),
    );
    const client = createClient({ baseUrl: BASE, getAccessToken: () => "tok-1" });
    const data = await client.get<{ items: number[] }>("/api/v1/things");
    expect(data.items).toEqual([1, 2]);
    expect(seenAuth).toBe("Bearer tok-1");
  });

  it("POST 携带 Content-Type application/json 与 JSON 化 body", async () => {
    let captured: unknown = null;
    let contentType = "";
    server.use(
      http.post(`${BASE}/api/v1/things`, async ({ request }) => {
        contentType = request.headers.get("content-type") ?? "";
        captured = await request.json();
        return HttpResponse.json({ created: true }, { status: 201 });
      }),
    );
    const client = createClient({ baseUrl: BASE });
    const data = await client.post("/api/v1/things", { name: "x" });
    expect(data.created).toBe(true);
    expect(contentType).toBe("application/json");
    expect(captured).toEqual({ name: "x" });
  });

  it("login 便捷方法：POST /api/v1/auth/login（可带 tenant_slug）", async () => {
    const captured: unknown[] = [];
    server.use(
      http.post(`${BASE}/api/v1/auth/login`, async ({ request }) => {
        captured.push(await request.json());
        return HttpResponse.json({
          access_token: "a",
          refresh_token: "r",
          expires_in: 7200,
          tenant: { tenant_id: "t1", slug: "default", name: "默认租户", status: "ACTIVE" },
          user: {
            user_id: "u1",
            username: "admin",
            roles: ["ADMIN"],
            is_platform_admin: true,
          },
        });
      }),
    );
    const client = createClient({ baseUrl: BASE });
    const resp = await client.login("admin", "Admin@123!", "default");
    expect(resp.access_token).toBe("a");
    await client.login("admin", "Admin@123!");
    expect(captured).toEqual([
      { username: "admin", password: "Admin@123!", tenant_slug: "default" },
      { username: "admin", password: "Admin@123!" },
    ]);
  });
});

describe("client 错误结构解析（附录 B.0）", () => {
  it("非 2xx：抛 EdpApiError{status, code, message, requestId}", async () => {
    server.use(
      http.get(`${BASE}/api/v1/objects/not-exist`, () =>
        HttpResponse.json(errorBody("NOT_FOUND", "对象不存在"), { status: 404 }),
      ),
    );
    const client = createClient({ baseUrl: BASE });
    const err = await client.get("/api/v1/objects/not-exist").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(EdpApiError);
    const apiErr = err as EdpApiError;
    expect(apiErr.status).toBe(404);
    expect(apiErr.code).toBe("NOT_FOUND");
    expect(apiErr.message).toBe("对象不存在");
    expect(apiErr.requestId).toBe("req-123");
  });

  it("匿名 401（登录失败）：直接抛，不触发 onUnauthorized/setTokens", async () => {
    server.use(
      http.post(`${BASE}/api/v1/auth/login`, () =>
        HttpResponse.json(errorBody("UNAUTHENTICATED", "用户名或密码错误"), { status: 401 }),
      ),
    );
    const onUnauthorized = vi.fn();
    const setTokens = vi.fn();
    const client = createClient({ baseUrl: BASE, onUnauthorized, setTokens });
    const err = await client.login("admin", "wrong").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(EdpApiError);
    expect((err as EdpApiError).status).toBe(401);
    expect((err as EdpApiError).code).toBe("UNAUTHENTICATED");
    expect(onUnauthorized).not.toHaveBeenCalled();
    expect(setTokens).not.toHaveBeenCalled();
  });

  it("403 TENANT_SUSPENDED：onTenantSuspended 回调并抛", async () => {
    server.use(
      http.get(`${BASE}/api/v1/things`, () =>
        HttpResponse.json(errorBody("TENANT_SUSPENDED", "租户已暂停"), { status: 403 }),
      ),
    );
    const onTenantSuspended = vi.fn();
    const client = createClient({ baseUrl: BASE, onTenantSuspended });
    const err = await client.get("/api/v1/things").catch((e: unknown) => e);
    expect((err as EdpApiError).status).toBe(403);
    expect((err as EdpApiError).code).toBe("TENANT_SUSPENDED");
    expect(onTenantSuspended).toHaveBeenCalledTimes(1);
  });

  it("非 JSON 错误体：保留状态码 fallback（INTERNAL）", async () => {
    server.use(
      http.get(`${BASE}/api/v1/things`, () => new HttpResponse("boom", { status: 500 })),
    );
    const client = createClient({ baseUrl: BASE });
    const err = await client.get("/api/v1/things").catch((e: unknown) => e);
    expect((err as EdpApiError).status).toBe(500);
    expect((err as EdpApiError).code).toBe("INTERNAL");
  });

  it("网络异常：抛 EdpApiError{code: NETWORK_ERROR, status: 0}", async () => {
    server.use(http.get(`${BASE}/api/v1/things`, () => HttpResponse.error()));
    const client = createClient({ baseUrl: BASE });
    const err = await client.get("/api/v1/things").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(EdpApiError);
    expect((err as EdpApiError).code).toBe("NETWORK_ERROR");
    expect((err as EdpApiError).status).toBe(0);
  });
});
