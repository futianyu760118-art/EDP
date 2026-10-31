# E2E 本地复跑手册（W6 T10，EDP-602）

Playwright 真栈 E2E：`closed-loop.spec.ts`（M4 闭环叙事 + 追溯率断言）+
`tenant-isolation.spec.ts`（多租户隔离矩阵）。选择器全 `data-dom-id`。

## 架构要点（CORS）

后端无 CORS 中间件（web 容器形态由 nginx `/api` 反代解决跨域）。E2E 复用同一
手法：前端以**同源相对路径**构建（`vite build --mode e2e` → `.env.e2e` 置空
`VITE_API_BASE`——Windows 无法设空字符串环境变量，`$env:X=""` 等于删除，故用
mode 文件承载），`vite preview` 经 `vite.config.ts` 的 `preview.proxy` 把
`/api` 转发到真栈 api（目标 = `E2E_API_BASE`）。脚本内 API 直调
（request fixture）不走浏览器，无 CORS 问题。

## 前置

- Node 22+ / pnpm 10 / Docker（dev compose 栈）/ backend uv 环境；
- Playwright 浏览器：`npx playwright install chromium`（首次；CDN 不通时
  `$env:PLAYWRIGHT_DOWNLOAD_HOST = "https://npmmirror.com/mirrors/playwright"`）。

## 1. 起真栈（api:18000 / db:15432）

宿主 5432/8000 被占时带 override（W5 惯例；若宿主空闲可用 8000/5432 并把
下文 18000 换成 8000）：

```powershell
docker compose -f deploy/docker-compose.dev.yml -f deploy/docker-compose.dev.override.yml up -d --build
docker compose -f deploy/docker-compose.dev.yml -f deploy/docker-compose.dev.override.yml ps   # 核对 api→18000
```

注意：dev compose 的 api 是**构建进镜像**的代码（无源码挂载）——后端代码更新后
必须 `up -d --build api`（worker 同理）重建，否则容器跑旧镜像。

## 2. seed 重置基线（场景数据干净）

`make seed-demo RESET=1` 的等效命令（容器内执行）：

```powershell
docker compose -f deploy/docker-compose.dev.yml -f deploy/docker-compose.dev.override.yml exec -T api python -m edp_api.modules.demo.cli seed --reset
```

## 3. 同源构建 + preview 前端（4173 → 反代 API 18000）

```powershell
cd frontend
pnpm install
pnpm --filter web build --mode e2e        # .env.e2e：VITE_API_BASE=（同源相对路径）
pnpm --filter web preview --port 4173 --strictPort   # 另开终端常驻；proxy → E2E_API_BASE（缺省 18000）
```

api 在 8000（宿主空闲）时：`$env:E2E_API_BASE = "http://localhost:8000"` 后再
起 preview（proxy 目标运行期读取）。

## 4. 跑 E2E

```powershell
cd frontend/apps/web
npx playwright install chromium        # 首次
pnpm e2e                               # = playwright test（config 在 apps/web 根）
```

env 开关（均可缺省；E2E_API_BASE 同时驱动 preview 反代与脚本 API 直调）：

| env | 缺省 | 说明 |
| --- | --- | --- |
| `E2E_BASE_URL` | `http://localhost:4173` | 被测 web 入口（preview 端口） |
| `E2E_API_BASE` | `http://localhost:18000` | 直调 API（request fixture）+ preview 反代目标 |
| `E2E_ADMIN_USER/PASS` | `admin` / `Admin@123!` | A 租户平台管理员（闭环主线） |
| `E2E_ANALYST_USER/PASS` | `analyst1` / `Admin@123!` | A 租户只读（隔离正向对照） |
| `E2E_TENANT_B_USER/PASS/SLUG` | `b-admin` / `TenantB@123!` / `tenant-b` | B 租户（脚本开通，重跑 409 复用） |

## 5. 视觉回归（EDP-603，visual project）

双层基线：组件层 34 story（Storybook 静态产物逐 story）+ 页面层 18 业务路由
（真栈整页）——合计 52 关键状态 ≥ 26 稿口径（映射表 T14 归档 README）。
基线按平台后缀各持一份：本地 `*-win32.png`、CI `*-linux.png`（字体栈不同，
不可互用；`.gitignore` 不忽略 `e2e/__screenshots__/`）。

确定性三件套（详见两个 spec 文件头）：固定锚 seed + 时钟冻结（`page.clock.
setFixedTime`，不伪造定时器）+ 动态区 mask。

```powershell
# 前置（在 step 1~3 真栈就绪之上）：固定锚重置 seed + storybook 构建
docker compose -f deploy/docker-compose.dev.yml -f deploy/docker-compose.dev.override.yml exec -T api python -m edp_api.modules.demo.cli seed --reset --anchor 2026-08-01T00:00:00+00:00
cd frontend
pnpm --filter web build-storybook

# 跑基线比对
cd apps/web
pnpm e2e:visual                         # = playwright test --project=visual

# 基线更新（偏差经 PR 评审后执行；win32 本地基线由本命令生成）
pnpm e2e:visual -- --update-snapshots
```

**linux 基线生成**（本机无法直接产出 linux 基线时，用与 CI 同源的
Playwright 官方镜像在容器内跑，输出落回宿主 `__screenshots__/`）：

```powershell
# 前置：preview 须绑 0.0.0.0（vite preview --host 0.0.0.0），
# vite.config.ts 已放行 host.docker.internal（preview.allowedHosts）
docker run --rm `
  -v "<临时目录含 playwright.config.ts 与 e2e/ 副本>:/work" `
  -v "<仓库>/frontend/apps/web/e2e/__screenshots__:/work/e2e/__screenshots__" `
  -v "<仓库>/frontend/apps/web/storybook-static:/work/storybook-static:ro" `
  -e E2E_BASE_URL="http://host.docker.internal:4173" `
  -e E2E_API_BASE="http://host.docker.internal:18000" `
  -e E2E_SEED_ANCHOR="2026-08-01T00:00:00.000Z" `
  -w /work mcr.microsoft.com/playwright:v1.63.0-noble `
  bash -lc "npm i @playwright/test@1.63.0 --no-save --silent && npx playwright test --project=visual --update-snapshots"
```

（临时目录需 `{"type":"module"}` 的 package.json——spec 用了 `import.meta`；
组件 spec 的 storybook-static 由 `WEB_ROOT` 相对定位，故镜像内 `/work` 下需
同时有 `playwright.config.ts`、`e2e/`、`storybook-static/`。）

CI（e2e.yml）：功能 e2e 之后以固定锚重置 seed → `build-storybook` →
`pnpm e2e:visual`；linux 基线随仓库入库（与 CI ubuntu-24.04 同源镜像生成）。

## 注意事项

- **端口占用**：4173 被 vite preview `--strictPort` 硬占则直接失败（换端口需
  同步 `E2E_BASE_URL`）；18000/15432 是 dev override 的既定映射；
- **重跑顺序**：closed-loop 会消费场景 2 案例的 OPEN 状态（审批后不可逆）——
  复跑前先 step 2 重置 seed；tenant-isolation 的 B 租户为控制面数据
  （`--reset` 不清 tenants）重跑自动复用（409 → 凭据复验登录）；
- **失败排查**：trace/screenshot 仅失败保留（`retain-on-failure` /
  `only-on-failure`），报告在 `playwright-report/`、产物在 `test-results/`
  （两者均已 gitignore；`e2e/__screenshots__/` 是 T11 visual 基线，不忽略）；
- CI（`.github/workflows/e2e.yml`）：service postgres + alembic + seed +
  uvicorn(8000)/worker + 同源构建（`--mode e2e`）+ preview(4173，反代 8000)，
  与本地唯一差异是 API 端口（`E2E_API_BASE` 注入，全流程一致）。
