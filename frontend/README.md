# EDP 控制台前端交接文档（EDP-604，W6 归档）

> 范围：`frontend/apps/web`（EDP 控制台）+ `packages/{shared,api-sdk}`。运行/复跑手册见 `e2e/README.md`。

## 1. 技术栈与结构

React 18 + Ant Design 5（Token 主题）+ TanStack Query v5 + React Router 6 + Vite 6 + Tailwind 4；
pnpm workspace：`apps/web`（应用）、`packages/shared`（组件/枚举/错误码）、`packages/api-sdk`（契约生成 SDK）。

```
apps/web/src/
  app/         路由（router.tsx）/ 守卫（guards.tsx）/ providers
  shell/       壳层（AppLayout/Topbar/Sidebar/NotificationBell/TenantSwitchModal）
  features/    18 业务域（api.ts + hooks.ts + 页面 + 测试）
  mocks/       MSW handlers（66+ handler，17 域）
  e2e/         Playwright（功能 + visual 视觉回归）
```

## 2. 组件清单（shared 9 核心 + 应用级）

| 组件 | 用途 |
|---|---|
| StatusPill | 状态药丸（tone: success/warning/error/info/muted） |
| FilterChips | Chip 过滤器（单选/多选/清空） |
| KpiCard | KPI 数字卡（三 tone） |
| VerticalTimeline | 垂直时间线 |
| ModalForm | 模态表单（app 级，`components/ModalForm.tsx`） |
| EmptyState | 空态三件套（icon+标题+描述+双动作） |
| DangerConfirm | 危险确认（强确认=输入解锁） |
| MonoId | Mono 短 ID（可复制） |
| CursorPagination | 游标分页条 |
| RiskDrawer | 风险抽屉（shared/components/RiskDrawer） |

Storybook：11 story 文件 / 34 story entry（`pnpm --filter web storybook`）。

## 3. 路由表（18 业务路由 + 全局）

| 路径 | 页面 | 守卫角色 |
|---|---|---|
| `/login` | 登录 | — |
| `/admin/overview` | 运营总览 | 登录 |
| `/admin/registry` | 业务对象 | 登录 |
| `/admin/events` | 事件流 | 登录 |
| `/admin/evidence` | 证据库 | 登录 |
| `/admin/quality` | 数据质量 | 登录 |
| `/admin/audit` | 审计日志 | 登录 |
| `/admin/adapters` | 适配器管理 | 登录 |
| `/admin/systems` | 系统健康 | 登录 |
| `/tenants`、`/tenants/:id` | 租户管理 | PLATFORM_ADMIN |
| `/cases`、`/cases/:id` | 闭环案例 | 登录 |
| `/decisions` | 决策 | 登录 |
| `/actions` | 行动 | 登录 |
| `/admin/tools`、`/admin/traces`、`/admin/memory` | Agent 三页 | 登录 |
| `/admin/drills` | 演练回放 | ADMIN+（对齐后端 quality:run 收紧） |
| `/search?q=` | 全局搜索 | 登录 |
| 403/404/500 | 错误页 | 全局（errorElement） |

守卫实现：`app/guards.tsx`（`RequireAuth` / `RequireRoles` + `ROUTE_ROLE_GUARDS` 表）。

## 4. 枚举字典（`packages/shared/src/enums/index.ts`）

角色（5）：PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST/SERVICE；
租户状态（4）：PROVISIONING/ACTIVE/SUSPENDED/CANCELLED；
风险等级（4）：P0~P3；套餐（4）：TRIAL/STANDARD/PREMIUM/DEDICATED。
**改枚举值必须与后端迁移/种子两侧同步过测试**（文件头约定）。

## 5. 错误码走查表（13 码 + NETWORK_ERROR，`packages/shared/src/errors/index.ts`）

| 码 | 触发路径 | 呈现 |
|---|---|---|
| VALIDATION_ERROR | 表单/查询参数校验（后端 400） | inline 行内 |
| UNAUTHENTICATED | token 过期/缺失（401） | 跳登录 |
| FORBIDDEN | 无权限（403） | 403 页 |
| TENANT_FORBIDDEN | 跨租户访问（403） | 403 页 |
| TENANT_SUSPENDED | 租户暂停（403） | 常驻横幅 |
| GUARD_POLICY_DENIED | Human-Only 守卫（AI 提交决策 403） | toast |
| NOT_FOUND | 资源不存在/跨租户 404 | toast |
| METHOD_NOT_ALLOWED | 非 GET 工具接口（405） | toast |
| CONFLICT | 乐观锁冲突/任务互斥（409） | toast（刷新） |
| INVALID_TRANSITION | 状态机非法转移（422→400） | rerender（allowed_to 重渲染） |
| RATE_LIMITED | 配额/限流（429） | toast |
| UPSTREAM_UNAVAILABLE | 源系统不可达（502） | toast |
| INTERNAL | 未归类（5xx） | toast |
| NETWORK_ERROR | 网络层异常 | toast |

分发：`app/main.tsx`（banner/login/page403 不弹 toast，其余全局 toast）。

## 6. MSW / 真模式切换

- 默认 MSW（`mocks/handlers` 17 域）；真模式 `VITE_USE_MSW=0`（`msw-setup.ts` 仅 `VITE_USE_MSW=1` 启 worker）；
- E2E 走真栈同源构建（`.env.e2e` 置空 `VITE_API_BASE` + `vite preview` 反代，见 `e2e/README.md`）。

## 7. E2E 与视觉回归维护

- 选择器**只用 `data-dom-id`**（禁 text/role 定位；断言文本可用 `toContainText`）；
- 功能：`pnpm --filter web e2e`（closed-loop + tenant-isolation）；
- 视觉：`pnpm --filter web e2e:visual`（组件 34 story + 页面 18 路由双层；win32/linux 基线各持，linux 生成法见 e2e/README.md）；
- 偏差处理：`--update-snapshots` 后走 PR 评审。

## 8. Memory 评审流转（中枢接管对接说明，EDP-014）

EDP 侧保持既有端点不变：`POST /memories`（候选创建）、`GET /memories`（查询）、
`PATCH /memories/{id}/review`（Human-Only 评审）；W6 起**评审流转业务由 Agent 中枢接管**
（界面/工作流在中枢侧），EDP 控制台记忆页维持只读展示口径（docstring/空态文案留痕）。

## 9. 常见坑

- 前端测试 flake：宿主满载用 `--maxWorkers=2 --testTimeout=60000`（Makefile 已固化）；
- `pnpm --filter web test -- --xxx` 的 `--` 会被当文件过滤器透传——用 `exec vitest run`（W5 教训）；
- 契约：改后端端点须 `make contract-export` + api-sdk regen + `make contract-gate`（EDP-007 门禁）。
