import { expect, test, type Locator, type Page } from "@playwright/test";
import { API_V1, ADMIN_PASS, ADMIN_USER } from "../helpers";

/**
 * 页面层视觉基线（W6 T11，EDP-603）——真栈 18 业务路由整页截图。
 *
 * 覆盖口径（与 components.visual 的 34 story 合计 52 关键状态 ≥ 26 稿；
 * 正式映射表 T14 归档 README）：router.tsx 全量业务路由 = overview/registry/
 * events/evidence/quality/audit/adapters/systems/tenants/tenants:id/cases/
 * cases:id/decisions/actions/tools/traces/memory/drills（/login、/search、
 * 403/404 占位页不含；暗色模式留缺口登记——快照翻倍暂不做）。
 *
 * 确定性三件套：
 * 1. seed 固定锚（README：`seed --reset --anchor 2026-08-01T00:00:00+00:00`）
 *    ——全部业务时间文本（fmtDateTime / relTime 超 30 天回退绝对日期）确定；
 * 2. 时钟冻结（page.clock.setFixedTime 锚+3h）——relTime/「24H」窗口由冻结
 *    时刻派生，跨轮次一致。注意不能用 pauseAt/install（暂停/伪造定时器会
 *    卡死 @tanstack/react-query 的 setTimeout 通知管线——页面停留骨架态）；
 *    setFixedTime 只冻结 Date 不碰定时器，轮询照常（30s 间隔远大于截图窗口）；
 * 3. 动态区 mask——真实墙钟写入的数据（审计 occurred_at=seed 真实时刻、
 *    worker 周期回填的 last_sync、案例 uuid4 id）与页面版本无关，清单见
 *    globalMasks / ROUTE_MASKS。
 *
 * 会话：beforeAll API 登录一次 → zustand persist 快照经 addInitScript 注入
 * localStorage（edp-session），每路由只读导航（无点击，不耗场景状态）。
 */

const API_BASE = process.env.E2E_API_BASE ?? "http://localhost:18000";

/** 与 seed --anchor 一致（覆盖须同步 seed 命令；见 components.visual.spec.ts）。 */
const SEED_ANCHOR = process.env.E2E_SEED_ANCHOR ?? "2026-08-01T00:00:00.000Z";
const FROZEN_NOW = new Date(new Date(SEED_ANCHOR).getTime() + 3 * 3_600_000);

/** 冻结动效/光标/滚动条（滚动条宽度跨平台不一，隐藏保证版式可比）。 */
const FREEZE_CSS =
  "*,*::before,*::after{transition:none!important;animation:none!important;caret-color:transparent!important}" +
  "::-webkit-scrollbar{display:none!important}";

interface RouteShot {
  name: string;
  path: string;
  /** 数据就绪锚点（骨架屏消失后的稳定元素）。 */
  ready: string;
  /** 路由级动态区 mask（与全局 mask 合并；选择器依据见 DYNAMIC_MASKS 注释）。 */
  masks?: (page: Page) => Locator[];
}

/** 18 业务路由（path 模板在 beforeAll 解析真实 id）。 */
const ROUTES: RouteShot[] = [
  { name: "overview", path: "/admin/overview", ready: '[data-dom-id="overview-bottom"]' },
  { name: "registry", path: "/admin/registry", ready: '[data-dom-id="objects-page"]' },
  { name: "events", path: "/admin/events", ready: '[data-dom-id="events-page"]' },
  { name: "evidence", path: "/admin/evidence", ready: '[data-dom-id="evidence-page"]' },
  { name: "quality", path: "/admin/quality", ready: '[data-dom-id="quality-page"]' },
  { name: "audit", path: "/admin/audit", ready: '[data-dom-id="audit-page"]' },
  { name: "adapters", path: "/admin/adapters", ready: '[data-dom-id="adapters-page"]' },
  { name: "systems", path: "/admin/systems", ready: '[data-dom-id="health-cards"]' },
  { name: "tenants", path: "/tenants", ready: '[data-dom-id="tenants-page"]' },
  { name: "tenant-detail", path: "/tenants/{tenantId}", ready: '[data-dom-id="tenant-basic"]' },
  { name: "cases", path: "/cases", ready: '[data-dom-id="cases-page"]' },
  { name: "case-detail", path: "/cases/{caseId}", ready: '[data-dom-id="case-detail-question"]' },
  { name: "decisions", path: "/decisions", ready: '[data-dom-id="decisions-page"]' },
  { name: "actions", path: "/actions", ready: '[data-dom-id="actions-page"]' },
  { name: "tools", path: "/admin/tools", ready: '[data-dom-id="tools-page"]' },
  { name: "traces", path: "/admin/traces", ready: '[data-dom-id="traces-page"]' },
  { name: "memory", path: "/admin/memory", ready: '[data-dom-id="memory-page"]' },
  { name: "drills", path: "/admin/drills", ready: '[data-dom-id="drills-page"]' },
];

/** 跨路由生效的动态区 mask（真实墙钟/随机 id 写入的区域）。 */
function globalMasks(page: Page): Locator[] {
  return [
    // 总览审计动态行：occurred_at = seed 真实时刻（重播即变）
    page.locator('[data-dom-id="overview-audit-row"] div.truncate'),
  ];
}

/** 各路由专属 mask（列位以对应页表头为准）。 */
const ROUTE_MASKS: Record<string, (page: Page) => Locator[]> = {
  // audit 表首列「时间」：审计 occurred_at = 写入时刻
  audit: (page) => [page.locator('[data-dom-id^="audit-row-"] > td:first-child')],
  // adapters 第 4 列「上次同步」：worker 周期同步回填真实时刻
  adapters: (page) => [page.locator('[data-dom-id^="adapter-row-"] > td:nth-child(4)')],
  // systems「最近同步」行：platform.systems.last_sync 运行期推进
  systems: (page) => [
    page.locator(
      'xpath=//div[@data-dom-id="health-outbox-card"]//span[normalize-space()="最近同步"]/..',
    ),
  ],
  // tenants 第 6 列「创建时间」：租户行由迁移/E2E 开通写入（时刻随环境）
  tenants: (page) => [page.locator('[data-dom-id^="tenants-row-"] > td:nth-child(6)')],
  // 租户详情：基本信息「创建时间」行 + 成员表第 4 列「加入时间」+ 配额「最近调整」
  "tenant-detail": (page) => [
    page.locator(
      'xpath=//div[@data-dom-id="tenant-basic-body"]//span[normalize-space()="创建时间"]/..',
    ),
    page.locator('[data-dom-id="tenant-members-table"] td:nth-child(4)'),
    page.locator('[data-dom-id="quota-updated_at"]'),
  ],
  // cases 第 5 列「创建时间」：案例行 created_at = seed 运行时刻
  cases: (page) => [page.locator('[data-dom-id^="cases-row-"] > td:nth-child(5)')],
  // 案例详情：头部 MonoId 显示 case_id（uuid4，每次 reseed 重掷）
  "case-detail": (page) => [
    page.locator('[data-dom-id="case-detail-page"] [data-dom-id="mono-id-value"]'),
  ],
  // decisions 第 4 列「创建时间」：同 cases（待决列表行 = 案例）
  decisions: (page) => [
    page.locator('[data-dom-id^="decisions-row-"] > td:nth-child(4)'),
  ],
};

/** 附录 B.1 TokenResponse 载荷（登录响应，经 addInitScript 注入会话用）。 */
interface LoginResponse {
  access_token: string;
  refresh_token: string;
  user: { username: string; display_name?: string; roles: string[]; is_platform_admin: boolean };
  tenant: { slug: string; name: string; status: string; plan?: string };
}

/** zustand persist 快照（edp-session；结构对齐 session-store partialize）。 */
function sessionSnapshot(login: LoginResponse): string {
  return JSON.stringify({
    state: {
      accessToken: login.access_token,
      refreshToken: login.refresh_token,
      user: {
        username: login.user.username,
        display_name: login.user.display_name,
        roles: login.user.roles,
        is_platform_admin: login.user.is_platform_admin,
      },
      tenant: {
        slug: login.tenant.slug,
        name: login.tenant.name,
        plan: login.tenant.plan,
        status: login.tenant.status,
      },
    },
    version: 0,
  });
}

let snapshot = "";
let resolved: Record<string, string> = {};

test.beforeAll(async ({ request }) => {
  const loginResp = await request.post(`${API_BASE}${API_V1}/auth/login`, {
    data: { username: ADMIN_USER, password: ADMIN_PASS },
  });
  expect(loginResp.ok(), "admin 登录失败：真栈是否就绪").toBeTruthy();
  const loginBody = (await loginResp.json()) as LoginResponse;
  snapshot = sessionSnapshot(loginBody);
  const headers = { Authorization: `Bearer ${loginBody.access_token}` };

  const tenantsResp = await request.get(`${API_BASE}${API_V1}/tenants`, { headers });
  expect(tenantsResp.ok(), "租户列表不可达：真栈/seed 是否就绪").toBeTruthy();
  const tenants = (await tenantsResp.json()).items as Array<{
    tenant_id: string;
    slug: string;
  }>;
  const defaultTenant = tenants.find((t) => t.slug === "default") ?? tenants[0];
  expect(defaultTenant, "缺 default 租户：先跑 seed（README 视觉回归段）").toBeDefined();

  const casesResp = await request.get(`${API_BASE}${API_V1}/decisions/cases?status=OPEN`, {
    headers,
  });
  expect(casesResp.ok(), "待决案例列表不可达").toBeTruthy();
  const openCases = (await casesResp.json()).items as Array<{
    case_id: string;
    question: string;
  }>;
  const seedCase =
    openCases.find((item) => item.question.includes("SO-2026-00123")) ?? openCases[0];
  expect(seedCase, "无 OPEN 案例：先 seed --reset --anchor（README 视觉回归段）").toBeDefined();

  resolved = { tenantId: defaultTenant.tenant_id, caseId: seedCase.case_id };
});

test.beforeEach(async ({ page }) => {
  // 只冻结 Date（不伪造定时器）：react-query 通知管线依赖 setTimeout
  await page.clock.setFixedTime(FROZEN_NOW);
  await page.addInitScript(([value]) => {
    window.localStorage.setItem("edp-session", value as string);
  }, [snapshot]);
});

test("页面路由视觉基线 ×18", async ({ page }) => {
  test.setTimeout(60_000 * ROUTES.length);
  for (const route of ROUTES) {
    await test.step(route.name, async () => {
      const path = route.path.replace("{tenantId}", resolved.tenantId).replace(
        "{caseId}",
        resolved.caseId,
      );
      await page.goto(path);
      // 就绪锚点可见 + 网络静默（时钟冻结 ⇒ 轮询定时器停摆，networkidle 可达）
      await expect(page.locator(route.ready)).toBeVisible();
      await page.waitForLoadState("networkidle");
      await page.addStyleTag({ content: FREEZE_CSS });
      await page.evaluate(() => document.fonts.ready);
      await expect(page).toHaveScreenshot(`page-${route.name}.png`, {
        fullPage: true,
        animations: "disabled",
        caret: "hide",
        mask: [...globalMasks(page), ...(ROUTE_MASKS[route.name]?.(page) ?? [])],
      });
    });
  }
});
