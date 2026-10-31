import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { setupServer } from "msw/node";
import { handlers } from "../handlers";
import { TENANT_ID } from "../data/ids";
import {
  TENANT_ACME_ID,
  platformUsers,
  tenantMembers,
  tenantRows,
  USER_MANAGER1,
} from "../data/tenants";

const server = setupServer(...handlers);
const BASE = "http://mock.test";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("tenant handlers", () => {
  it("current：200 冻结契约形状（plan=STANDARD / status=ACTIVE）", async () => {
    const resp = await fetch(`${BASE}/api/v1/tenants/current`);
    expect(resp.status).toBe(200);
    expect(await resp.json()).toMatchObject({
      tenant_id: TENANT_ID,
      slug: "default",
      name: "默认租户",
      plan: "STANDARD",
      status: "ACTIVE",
    });
  });

  it("与 auth login 一致：tenant_id 相同", async () => {
    const login = await fetch(`${BASE}/api/v1/auth/login`, {
      method: "POST",
      body: JSON.stringify({ username: "manager1", password: "x" }),
    });
    const session = (await login.json()) as { tenant: { tenant_id: string } };
    const current = (await (await fetch(`${BASE}/api/v1/tenants/current`)).json()) as { tenant_id: string };
    expect(current.tenant_id).toBe(session.tenant.tenant_id);
  });

  it("场景注入：X-Mock-Scenario=503 → UPSTREAM_UNAVAILABLE", async () => {
    const resp = await fetch(`${BASE}/api/v1/tenants/current`, { headers: { "X-Mock-Scenario": "503" } });
    expect(resp.status).toBe(503);
    expect(await resp.json()).toMatchObject({ error: { code: "UPSTREAM_UNAVAILABLE" } });
  });
});

describe("tenant handlers（W5 平台面 EDP-501）", () => {
  it("列表：status/plan 过滤 + 游标分页 + usage mock 扩展", async () => {
    const all = (await (
      await fetch(`${BASE}/api/v1/tenants?limit=100`)
    ).json()) as { items: { tenant_id: string; usage?: unknown }[]; total: number; next_cursor: string | null };
    expect(all.total).toBe(tenantRows.length);
    expect(all.items[0].tenant_id).toBe(TENANT_ID); // created_at DESC 首行 default
    expect(all.items.find((t) => t.tenant_id === TENANT_ACME_ID)?.usage).toEqual({
      storage_used_gb: 684,
      events_this_month: 18_421,
    });

    const suspended = (await (
      await fetch(`${BASE}/api/v1/tenants?status=SUSPENDED&plan=TRIAL`)
    ).json()) as { items: { slug: string }[] };
    expect(suspended.items.map((t) => t.slug)).toEqual(["mfg-pilot"]);

    const page1 = (await (
      await fetch(`${BASE}/api/v1/tenants?limit=8`)
    ).json()) as { items: unknown[]; next_cursor: string };
    expect(page1.items).toHaveLength(8);
    const page2 = (await (
      await fetch(`${BASE}/api/v1/tenants?limit=8&cursor=${encodeURIComponent(page1.next_cursor)}`)
    ).json()) as { items: unknown[]; next_cursor: string | null };
    expect(page2.items).toHaveLength(2);
    expect(page2.next_cursor).toBeNull();
  });

  it("开通：未携带口令 → 201 自动生成编码 + 临时口令回传一次；缺 name → 400", async () => {
    const ok = await fetch(`${BASE}/api/v1/tenants`, {
      method: "POST",
      body: JSON.stringify({
        name: "试点租户",
        plan: "TRIAL",
        admin: { username: "padmin", email: "p@example.com", display_name: "试点管理员" },
      }),
    });
    expect(ok.status).toBe(201);
    const body = (await ok.json()) as { slug: string; temporary_password: string };
    // 编码由服务端自动生成 ten-YYYY-NNNN（请求体不携带 slug）
    expect(body.slug).toMatch(/^ten-\d{4}-\d{4,}$/);
    expect(body.temporary_password).toEqual(expect.any(String));

    const missing = await fetch(`${BASE}/api/v1/tenants`, {
      method: "POST",
      body: JSON.stringify({
        plan: "TRIAL",
        admin: { username: "a", email: "a@example.com", display_name: "A", password: "Secret@123" },
      }),
    });
    expect(missing.status).toBe(400);
    expect(await missing.json()).toMatchObject({ error: { code: "VALIDATION_ERROR" } });
  });

  it("详情/配额：acme 提额覆盖（storage 3000）；PATCH quotas reason 缺失 → 422", async () => {
    const detail = (await (await fetch(`${BASE}/api/v1/tenants/${TENANT_ACME_ID}`)).json()) as {
      quotas: { storage_gb: number };
      usage: { events_this_month: number } | null;
    };
    expect(detail.quotas.storage_gb).toBe(3_000);
    expect(detail.usage?.events_this_month).toBe(18_421);

    const missing = await fetch(`${BASE}/api/v1/tenants/${TENANT_ACME_ID}/quotas`, {
      method: "PATCH",
      body: JSON.stringify({ storage_gb: 9000 }),
    });
    expect(missing.status).toBe(422);

    const ok = await fetch(`${BASE}/api/v1/tenants/${TENANT_ACME_ID}/quotas`, {
      method: "PATCH",
      body: JSON.stringify({ storage_gb: 9000, reason: "大促临时提额" }),
    });
    expect(ok.status).toBe(200);
    expect(await ok.json()).toMatchObject({ storage_gb: 9000, api_rate_limit: 1_500 });
  });

  it("成员：清单分页形状；已在册 409；角色空 422；PATCH 改角色 200", async () => {
    const list = (await (await fetch(`${BASE}/api/v1/tenants/${TENANT_ACME_ID}/members`)).json()) as {
      items: { member_id: string }[];
      total: number;
    };
    expect(list.total).toBe(tenantMembers[TENANT_ACME_ID].length);

    const conflict = await fetch(`${BASE}/api/v1/tenants/${TENANT_ACME_ID}/members`, {
      method: "POST",
      body: JSON.stringify({ user_id: USER_MANAGER1, member_roles: ["ANALYST"] }),
    });
    expect(conflict.status).toBe(409);

    const emptyRoles = await fetch(`${BASE}/api/v1/tenants/${TENANT_ACME_ID}/members`, {
      method: "POST",
      body: JSON.stringify({ user_id: platformUsers[3].user_id, member_roles: [] }),
    });
    expect(emptyRoles.status).toBe(422);

    const patched = await fetch(
      `${BASE}/api/v1/tenants/${TENANT_ACME_ID}/members/${list.items[1].member_id}`,
      {
        method: "PATCH",
        body: JSON.stringify({ member_roles: ["ADMIN"] }),
      },
    );
    expect(patched.status).toBe(200);
    expect(await patched.json()).toMatchObject({ member_roles: ["ADMIN"] });
  });

  it("context：200 回发 access_token；暂停态租户 403 TENANT_SUSPENDED", async () => {
    const ok = (await (await fetch(`${BASE}/api/v1/tenants/${TENANT_ACME_ID}/context`, { method: "POST" })).json()) as {
      access_token: string;
      tenant_id: string;
    };
    expect(ok.access_token).toBe("mock-access-ctx-acme");
    expect(ok.tenant_id).toBe(TENANT_ACME_ID);

    const suspended = tenantRows.find((t) => t.status === "SUSPENDED")!;
    const resp = await fetch(`${BASE}/api/v1/tenants/${suspended.tenant_id}/context`, { method: "POST" });
    expect(resp.status).toBe(403);
    expect(await resp.json()).toMatchObject({ error: { code: "TENANT_SUSPENDED" } });
  });

  it("生命周期：cancel 缺 confirm/reason → 400；齐备 → 202；suspend/resume 202", async () => {
    const bad = await fetch(`${BASE}/api/v1/tenants/${TENANT_ACME_ID}/cancel`, {
      method: "POST",
      body: JSON.stringify({ confirm: true, reason: "  " }),
    });
    expect(bad.status).toBe(400);

    const ok = await fetch(`${BASE}/api/v1/tenants/${TENANT_ACME_ID}/cancel`, {
      method: "POST",
      body: JSON.stringify({ confirm: true, reason: "合同到期" }),
    });
    expect(ok.status).toBe(202);
    expect(await ok.json()).toMatchObject({ operation: "cancel", status: "CANCELLED" });

    expect(
      (await fetch(`${BASE}/api/v1/tenants/${TENANT_ACME_ID}/suspend`, { method: "POST" })).status,
    ).toBe(202);
    const suspendedTenant = tenantRows.find((t) => t.status === "SUSPENDED")!;
    expect(
      (await fetch(`${BASE}/api/v1/tenants/${suspendedTenant.tenant_id}/resume`, { method: "POST" })).status,
    ).toBe(202);
  });

  it("current/usage 与 /admin/users（真契约 Page 信封，W6-08）形状", async () => {
    const usage = (await (await fetch(`${BASE}/api/v1/tenants/current/usage`)).json()) as {
      items: { usage_date: string }[];
    };
    expect(usage.items.length).toBeGreaterThan(0);

    const users = (await (await fetch(`${BASE}/api/v1/admin/users`)).json()) as {
      items: { user_id: string; username: string; display_name: string | null }[];
      next_cursor: string | null;
      total: number;
    };
    expect(users.items).toHaveLength(platformUsers.length);
    expect(users.total).toBe(platformUsers.length);
    expect(users.next_cursor).toBeNull();
    // username ASC 口径：目录项按 username 升序
    const usernames = users.items.map((u) => u.username);
    expect([...usernames].sort((a, b) => a.localeCompare(b))).toEqual(usernames);
  });
});
