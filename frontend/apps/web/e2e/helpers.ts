import { expect, type APIRequestContext, type Page } from "@playwright/test";

/**
 * E2E 共享助手（W6 T10）：凭据 env 缺省值 + UI/API 双登录。
 *
 * 账号出处：demo dataset 无用户段——演示账号来自平台种子迁移
 * backend/migrations/versions/platform/0005_seed.py（admin / manager1 /
 * analyst1，密码 Admin@123!，ENV EDP_ADMIN_INITIAL_PASSWORD / EDP_SEED_PASSWORD
 * 可覆盖）。B 租户无种子（0005 仅 default 单租户）：tenant-isolation 脚本内经
 * 平台 ADMIN 开通（POST /tenants 携带确定性口令），env E2E_TENANT_B_* 覆盖。
 *
 * 角色说明：闭环主线用 admin（HUMAN + is_platform_admin → 13.8 智能闭环导航
 * 仅 PLATFORM_ADMIN/ADMIN 可见，且 ADMIN 角色持 decision:decide +
 * action:execute）；manager1（MANAGER）虽有 decide/execute 权限但无闭环导航
 * 入口；analyst1（ANALYST）只读，作租户隔离 A 侧读对照。
 */

/** 默认租户（A）平台管理员（is_platform_admin=true）：闭环主线操作人 + B 租户开通。 */
export const ADMIN_USER = process.env.E2E_ADMIN_USER ?? "admin";
export const ADMIN_PASS = process.env.E2E_ADMIN_PASS ?? "Admin@123!";

/** 默认租户（A）只读审计员：隔离断言的 A 侧正向对照。 */
export const ANALYST_USER = process.env.E2E_ANALYST_USER ?? "analyst1";
export const ANALYST_PASS = process.env.E2E_ANALYST_PASS ?? "Admin@123!";

/** B 租户（隔离对照）：开通时确定性凭据（见 tenant-isolation.spec.ts）。 */
export const TENANT_B_SLUG = process.env.E2E_TENANT_B_SLUG ?? "tenant-b";
export const TENANT_B_USER = process.env.E2E_TENANT_B_USER ?? "b-admin";
export const TENANT_B_PASS = process.env.E2E_TENANT_B_PASS ?? "TenantB@123!";

export const API_V1 = "/api/v1";

/** API 登录（Playwright request fixture 直调）→ access_token。 */
export async function loginViaAPI(
  request: APIRequestContext,
  apiBase: string,
  username: string,
  password: string,
  tenantSlug?: string,
): Promise<string> {
  const resp = await request.post(`${apiBase}${API_V1}/auth/login`, {
    data: { username, password, ...(tenantSlug ? { tenant_slug: tenantSlug } : {}) },
  });
  expect(resp.ok(), `登录失败 ${username}: ${await resp.text()}`).toBeTruthy();
  return (await resp.json()).access_token as string;
}

/** 带 Bearer 的请求头。 */
export function bearerHeaders(token: string, extra: Record<string, string> = {}): Record<string, string> {
  return { Authorization: `Bearer ${token}`, ...extra };
}

/**
 * UI 登录（登录页表单，data-dom-id 锚点）：填租户（可选）+ 用户名 + 密码 → 提交
 * → 断言进入总览（默认跳转 /admin/overview）。会话落 localStorage（edp-session）；
 * 复跑前调用方负责清 storage（本基座两脚本各自独立 context，无串扰）。
 */
export async function loginViaUI(
  page: Page,
  username: string,
  password: string,
  tenantSlug?: string,
): Promise<void> {
  await page.goto("/login");
  if (tenantSlug) {
    await page.locator('[data-dom-id="login-tenant"]').fill(tenantSlug);
  }
  await page.locator('[data-dom-id="login-username"]').fill(username);
  await page.locator('[data-dom-id="login-password"]').fill(password);
  await page.locator('[data-dom-id="login-submit"]').click();
  await expect(page.locator('[data-dom-id="overview-page"]')).toBeVisible();
}
