import { defineConfig } from "@playwright/test";

/**
 * EDP E2E 基座（W6 T10，EDP-602；T11 加 visual project，EDP-603）。
 *
 * - baseURL：被测 web 入口（本地真栈 = vite preview 4173；可用 E2E_BASE_URL 覆盖）；
 *   前端调 API 的地址由构建期 VITE_API_BASE 决定（本地 18000 / CI 8000），
 *   与本配置解耦——见 e2e/README.md 复跑手册；
 * - 凭据经 E2E_* 环境变量注入，缺省取平台种子账号（迁移 0005_seed：
 *   admin / manager1 / analyst1，密码 Admin@123!——demo dataset 本身无账号，
 *   字面量出处 backend/migrations/versions/platform/0005_seed.py）；
 * - 双 project：e2e（真栈功能，T10）+ visual（视觉回归基线，T11）——
 *   `pnpm e2e` 显式跑 e2e project；visual 需先 build-storybook + seed 固定锚
 *   （复跑手册见 e2e/README.md「视觉回归」段）；workers 2（两 spec 文件
 *   各占一 worker 并行；文件内 fullyParallel 关闭保持串行）；
 * - timezoneId 固定 Asia/Shanghai：页面时间全按本地时区渲染（fmtDateTime），
 *   本地（UTC+8）与 CI（UTC）须一致，否则跨环境时间文本错位。
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  fullyParallel: false,
  retries: 0,
  workers: 2,
  expect: { timeout: 10_000 },
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:4173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
  },
  reporter: [["list"], ["html", { open: "never" }]],
  outputDir: "./test-results",
  projects: [
    {
      name: "e2e",
      testMatch: /.*\.spec\.ts/,
      testIgnore: "visual/**",
    },
    {
      name: "visual",
      testDir: "./e2e/visual",
      use: {
        viewport: { width: 1440, height: 900 },
        contextOptions: { reducedMotion: "reduce" },
      },
      expect: {
        toHaveScreenshot: {
          animations: "disabled",
          caret: "hide",
          // 容差（EDP-603）：同环境两轮实跑应像素一致（时钟冻结 + 动态区 mask）；
          // 0.2% 仅吸收亚像素抗锯齿噪声（1440×900 视口 ≈ 2.6k px、fullPage 按高度放大）
          maxDiffPixelRatio: 0.002,
        },
      },
      // 基线入库路径（.gitignore 已留白勿忽略）：按 spec 文件分目录、平台后缀隔离
      // （win32 本地 / linux CI 字体栈不同，各自持有基线；详见 e2e/README.md）
      snapshotPathTemplate:
        "e2e/__screenshots__/{testFileDir}/{testFileName}/{arg}{-platform}{ext}",
    },
  ],
});
