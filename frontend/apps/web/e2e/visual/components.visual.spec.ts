import { createServer, type Server } from "node:http";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";

/**
 * 组件层视觉基线（W6 T11，EDP-603）——Storybook 静态产物逐 story 截图。
 *
 * 数据源：`storybook-static/index.json`（SB8 构建产物，entries 键 = story id，
 * canvas 根节点 #storybook-root）。当前 11 个 story 文件（web 3 +
 * @edp/shared 8）共 34 个 story entry——覆盖口径：组件 34 story + 页面
 * 18 路由 = 52 关键状态 ≥ 26 稿口径（正式映射表 T14 归档 README）。
 * story 增删由 index.json 自动跟随（无需改本文件）。
 *
 * 静态服务：spec 内 node:http 进程内直出 storybook-static（不引新依赖，
 * 本地/CI 同款；vite preview 不适用于任意目录 + http-server 是新 devDep，
 * 裁定留痕见 e2e/README.md「视觉回归」段）。前置：`pnpm --filter web
 * build-storybook`。
 *
 * 时钟冻结于固定演示锚 +3h（与 pages.visual 同锚，杜绝相对时间文本漂移；
 * setFixedTime 只冻结 Date 不碰定时器）；弹窗类 story（ModalForm/
 * DangerConfirm）先点「打开弹窗」再截。
 */

const WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const SB_STATIC_DIR = path.join(WEB_ROOT, "storybook-static");
const SB_PORT = Number(process.env.E2E_SB_PORT ?? 6006);
const SB_BASE = process.env.E2E_SB_BASE ?? `http://localhost:${SB_PORT}`;

/** 与 seed --anchor 一致的固定演示锚（E2E_SEED_ANCHOR 覆盖须同步 seed 命令）。 */
export const SEED_ANCHOR = process.env.E2E_SEED_ANCHOR ?? "2026-08-01T00:00:00.000Z";
/** 冻结时钟 = 锚 + 3h（relTime / 24H 窗口由此派生，跨轮次逐字节一致）。 */
export const FROZEN_NOW = new Date(new Date(SEED_ANCHOR).getTime() + 3 * 3_600_000);

/** 需要先点「打开弹窗」的 story 前缀（截图须含弹窗本体；按钮文案 story 内固定）。 */
const OPEN_MODAL_PREFIXES = ["components-modalform--", "components-dangerconfirm--"];

const MIME: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
};

let server: Server | null = null;

/** storybook-static 静态服务器（进程内；无 SPA fallback——iframe.html 为实体文件）。 */
async function startStaticServer(root: string, port: number): Promise<void> {
  server = createServer(async (req, res) => {
    try {
      const urlPath = decodeURIComponent(new URL(req.url ?? "/", "http://x").pathname);
      const filePath = path.join(root, urlPath === "/" ? "index.html" : urlPath);
      if (!filePath.startsWith(root)) {
        res.writeHead(403).end();
        return;
      }
      const body = await readFile(filePath);
      res.writeHead(200, {
        "content-type": MIME[path.extname(filePath)] ?? "application/octet-stream",
        "cache-control": "no-store",
      });
      res.end(body);
    } catch {
      res.writeHead(404).end("not found");
    }
  });
  await new Promise<void>((resolve) => server!.listen(port, "127.0.0.1", resolve));
}

/** index.json entries → 井序 story id 列表（构建产物为权威源）。 */
async function readStoryIds(): Promise<string[]> {
  const raw = await readFile(path.join(SB_STATIC_DIR, "index.json"), "utf8");
  const index = JSON.parse(raw) as {
    entries: Record<string, { type: string; tags: string[] }>;
  };
  return Object.entries(index.entries)
    .filter(([, entry]) => entry.type === "story" && entry.tags.includes("test"))
    .map(([id]) => id)
    .sort();
}

/** 逐 story：iframe 画布 → 冻结时钟/禁动效 → 等渲染与字体 →（弹窗类先点开）→ 截图。 */
async function screenshotStory(page: Page, storyId: string): Promise<void> {
  await page.goto(`${SB_BASE}/iframe.html?id=${storyId}&viewMode=story`);
  // 只冻结 Date 不伪造定时器（pauseAt 会卡死依赖 setTimeout 的渲染管线）
  await page.clock.setFixedTime(FROZEN_NOW);
  await page.addStyleTag({
    content:
      "*,*::before,*::after{transition:none!important;animation:none!important;caret-color:transparent!important}",
  });
  const root = page.locator("#storybook-root");
  await expect(root).toBeAttached();
  await expect(root).not.toBeEmpty();
  await page.evaluate(() => document.fonts.ready);
  if (OPEN_MODAL_PREFIXES.some((prefix) => storyId.startsWith(prefix))) {
    await page.getByRole("button", { name: "打开弹窗" }).click();
    await page.locator('[role="dialog"]').waitFor({ state: "visible" });
  }
  await expect(page).toHaveScreenshot(`story-${storyId}.png`, {
    fullPage: true,
    animations: "disabled",
    caret: "hide",
  });
}

test.use({ viewport: { width: 1000, height: 700 } });

test.beforeAll(async () => {
  try {
    await readFile(path.join(SB_STATIC_DIR, "index.json"));
  } catch {
    throw new Error(
      `缺少 ${SB_STATIC_DIR}/index.json——先执行 pnpm --filter web build-storybook（e2e/README.md「视觉回归」）`,
    );
  }
  await startStaticServer(SB_STATIC_DIR, SB_PORT);
});

test.afterAll(async () => {
  await new Promise<void>((resolve) => server?.close(() => resolve()) ?? resolve());
});

const storyIds = await readStoryIds();

test(`组件 story 视觉基线 ×${storyIds.length}`, async ({ page }) => {
  test.setTimeout(15_000 * storyIds.length);
  for (const storyId of storyIds) {
    await test.step(storyId, async () => {
      await screenshotStory(page, storyId);
    });
  }
});
