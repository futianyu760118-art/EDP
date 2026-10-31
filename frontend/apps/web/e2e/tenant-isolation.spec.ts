import { expect, test } from "@playwright/test";
import {
  ADMIN_PASS,
  ADMIN_USER,
  ANALYST_PASS,
  ANALYST_USER,
  API_V1,
  TENANT_B_PASS,
  TENANT_B_SLUG,
  TENANT_B_USER,
  bearerHeaders,
  loginViaAPI,
  loginViaUI,
} from "./helpers";

/**
 * 多租户隔离 E2E（W6 T10，EDP-602）：A（default 种子租户）× B（隔离对照），
 * API 矩阵（request fixture 直调，≥4 断言）+ UI 对照（搜索页不渲染 A 数据）。
 *
 * B 租户构造（dataset 实况的最小实现）：0005 种子仅 default 单租户、无 B 租户
 * 账号——脚本内经平台 ADMIN（admin is_platform_admin）POST /tenants 开通
 * tenant-b（STANDARD，初始管理员携带确定性口令，E2E_TENANT_B_* 可覆盖）；
 * 重跑命中 409（slug 已存在）即复用，凭据不变即可登录。RLS 兜底语义：
 * 跨租户点查统一 404（不泄露存在性）、列表过滤恒空。
 *
 * A 侧资源取 seed 场景 2 主线对象（订单 SO-2026-00123 的 object/event）；
 * 正向对照 = A 只读 analyst1 可读同资源（证明「空」是隔离而非资源缺失）。
 */

const API_BASE = process.env.E2E_API_BASE ?? "http://localhost:18000";
const ORDER_NO = "SO-2026-00123";

test("租户隔离：B 租户对 A 资源点查 404 / 列表空 + UI 搜索不渲染 A 数据", async ({
  page,
  request,
}) => {
  // ---- 准备（API）：A 侧资源定位 + B 租户开通 ----
  const adminToken = await loginViaAPI(request, API_BASE, ADMIN_USER, ADMIN_PASS);
  const admin = bearerHeaders(adminToken);

  const eventsResp = await request.get(
    `${API_BASE}${API_V1}/events?event_type=capability.result.order_risk&limit=20`,
    { headers: admin },
  );
  expect(eventsResp.ok(), "A 侧事件列表不可达：seed 是否已跑？").toBeTruthy();
  const events = (await eventsResp.json()).items as Array<{
    event_id: string;
    object_id: string;
  }>;
  const orderEvent = events[0];
  expect(orderEvent, `未见订单结果事件：请先 demo.cli seed --reset`).toBeDefined();

  const createResp = await request.post(`${API_BASE}${API_V1}/tenants`, {
    headers: admin,
    data: {
      slug: TENANT_B_SLUG,
      name: "B 租户（E2E 隔离对照）",
      plan: "STANDARD",
      admin: {
        username: TENANT_B_USER,
        email: `${TENANT_B_USER}@tenant-b.local`,
        display_name: "B 租户管理员",
        password: TENANT_B_PASS,
      },
    },
  });
  expect([201, 409], `开通 B 租户失败：${await createResp.text()}`).toContain(createResp.status());

  const analystToken = await loginViaAPI(request, API_BASE, ANALYST_USER, ANALYST_PASS);
  const bToken = await loginViaAPI(
    request,
    API_BASE,
    TENANT_B_USER,
    TENANT_B_PASS,
    TENANT_B_SLUG,
  );
  const analyst = bearerHeaders(analystToken);
  const tenantB = bearerHeaders(bToken);

  // ---- 正向对照：A 只读 analyst 可读同资源（「空」是隔离而非缺失）----
  const aRead = await request.get(`${API_BASE}${API_V1}/events/${orderEvent.event_id}`, {
    headers: analyst,
  });
  expect(aRead.status(), "A 侧正向对照读失败").toBe(200);

  // ---- 隔离矩阵（≥4 断言）：B 对 A 资源点查 404 / 列表空 ----
  // 1. 对象点查：GET /objects/{A object_id} → 404（RLS 跨租户 = 不存在）
  const bObject = await request.get(`${API_BASE}${API_V1}/objects/${orderEvent.object_id}`, {
    headers: tenantB,
  });
  expect(bObject.status(), "B 租户对象点查应 404").toBe(404);

  // 2. 事件点查：GET /events/{A event_id} → 404
  const bEvent = await request.get(`${API_BASE}${API_V1}/events/${orderEvent.event_id}`, {
    headers: tenantB,
  });
  expect(bEvent.status(), "B 租户事件点查应 404").toBe(404);

  // 3. 事件列表：GET /events?object_id={A object_id} → 200 且恒空
  const bEvents = await request.get(
    `${API_BASE}${API_V1}/events?object_id=${orderEvent.object_id}&limit=10`,
    { headers: tenantB },
  );
  expect(bEvents.ok()).toBeTruthy();
  expect((await bEvents.json()).items, "B 租户按 A 对象过滤事件应恒空").toHaveLength(0);

  // 4. 证据列表：GET /evidence?object_id={A object_id} → 200 且恒空
  const bEvidence = await request.get(
    `${API_BASE}${API_V1}/evidence?object_id=${orderEvent.object_id}&limit=10`,
    { headers: tenantB },
  );
  expect(bEvidence.ok()).toBeTruthy();
  expect((await bEvidence.json()).items, "B 租户按 A 对象过滤证据应恒空").toHaveLength(0);

  // 5. 案例列表：GET /decisions/cases → 200 且恒空（seed 案例仅 A 可见）
  const bCases = await request.get(`${API_BASE}${API_V1}/decisions/cases`, { headers: tenantB });
  expect(bCases.ok()).toBeTruthy();
  expect((await bCases.json()).items, "B 租户案例列表应恒空").toHaveLength(0);

  // ---- UI 对照：B 登录 → 全局搜索 A 的 source_id → 零命中空态 ----
  await loginViaUI(page, TENANT_B_USER, TENANT_B_PASS, TENANT_B_SLUG);
  await page.locator('[data-dom-id="global-search"]').fill(ORDER_NO);
  await page.locator('[data-dom-id="global-search"]').press("Enter");
  await expect(page.locator('[data-dom-id="search-page"]')).toBeVisible();
  await expect(page.locator('[data-dom-id="search-summary"]')).toContainText("共 0 条结果");
  await expect(page.locator('[data-dom-id="search-empty"]')).toBeVisible();
  // 搜索结果区不渲染 A 的 source_id 命中行（对象/事件/证据三组行计数为 0）
  await expect(page.locator('[data-dom-id="search-object-row"]')).toHaveCount(0);
  await expect(page.locator('[data-dom-id="search-event-row"]')).toHaveCount(0);
  await expect(page.locator('[data-dom-id="search-evidence-row"]')).toHaveCount(0);
});
