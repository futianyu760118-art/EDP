# EDP 数据平台 W1 开发设计（前后端全量）

| 项 | 内容 |
|---|---|
| 日期 | 2026-09-14 |
| 状态 | 已获用户批准（对话中逐节确认） |
| 上游依据 | 《EDP数据平台开发计划_一阶段.md》W1 任务（后端 EDP-001~007/022/023；前端 EDP-101~105）、《EDP数据平台系统设计文档_V2.0.md》第 2/3/5/6/7/8 章及附录 A/B/D、`原型设计/pages/*.html`（26 高保真原型） |
| 里程碑 | M1 契约冻结（W1 周五出口条件） |

## 1. 范围与交付物

本次交付 W1 全部 14 个任务。仓库从零开始（当前仅有文档与原型，无代码）。

### 1.1 后端（backend/，uv workspace）

| 任务 | 交付物 | 验收标准（开发计划原文） |
|---|---|---|
| EDP-001 | 双工作区脚手架、ruff、import-linter、GitHub Actions（路径过滤）、deploy/docker-compose（api/worker/db）、testcontainers 基座 | CI 一键绿：lint + 单测 + PG 容器跑迁移；依赖规则违例构建失败 |
| EDP-002 | Alembic 基线（附录 A 全 15 Schema DDL + RLS + edp_migrator 账号 + 种子数据） | `alembic upgrade head` 幂等可回滚 |
| EDP-003 | JWT(Argon2id) + API Key 双轨认证、RBAC 矩阵、login/refresh/me | 单测：密码哈希、token 过期、scope 越界拒绝 |
| EDP-004 | Registry API：POST /objects upsert（乐观锁 409）、组合键查询、history | 并发 upsert：revision 冲突返回 409 + 当前版本 |
| EDP-005 | POST /events/batch（UUIDv5 幂等、Idempotency-Key、risk 字段）+ 查询 | 重放同批次 → duplicated 计数、0 重复行 |
| EDP-006 | Outbox 写侧（同事务）+ Worker（SKIP LOCKED、指数退避、按租户循环、异常隔离） | 注入抛错订阅者 → 重试递增、超阈值 FAILED |
| EDP-007 | OpenAPI 导出 → contracts/openapi.json + sha256 + 变更模板 | M1 签署物齐备；无评审契约 diff 使 PR 检查失败（脚本） |
| EDP-022 | tenants 四表、全表 tenant_id、RLS 策略迁移 | 跨租户集成用例（A 读写 B → 0 行/403）进 CI 通过 |
| EDP-023 | 租户上下文中间件（JWT claims / API Key 绑定、SET LOCAL、租户状态校验） | 无租户上下文被拒；SUSPENDED 租户 403 |

### 1.2 前端（frontend/，pnpm workspace）

| 任务 | 交付物 | 验收标准 |
|---|---|---|
| EDP-101 | apps/web + packages/api-sdk、shared 脚手架，Vite + 路由装配 + CI 接入 | 本地 `pnpm dev` 一键起；CI lint + Vitest 绿 |
| EDP-102 | `--edp-*` 令牌 → Antd ConfigProvider 映射 + 暗色模式 + Storybook 基线 | Storybook 与原型对照；主题切换记忆生效 |
| EDP-103 | 壳层：侧边栏四组导航/顶栏/面包屑/租户切换器（静态）/登录页 | 路由守卫 + 403/404 兜底；data-dom-id 锚点齐备 |
| EDP-104 | 9 核心组件（状态 Pill/Chip 过滤器/KPI 卡/垂直时间线/模态表单/空态三件套/危险确认/Mono 短 ID/游标分页条） | 每组件至少 3 状态入 Storybook |
| EDP-105 | api-sdk 自动生成管线 + 契约双门禁 CI 脚本 | 指纹不符 → 前端 PR 失败（脚本验证一次） |

## 2. 用户已确认的决策

1. **范围**：W1 前后端全部任务；
2. **顺序**：后端先行（契约快照就绪后前端基于真实契约生成 SDK）；
3. **环境**：本地有 Docker（迁移实跑 + testcontainers + compose 全套验证）；
4. **样式**：Antd 5 + Tailwind CSS v4 工具类（原型类名 1:1 对应；不构成第二 UI 库）；
5. **CI**：GitHub Actions（backend/** / frontend/** / contracts/** 路径过滤）。

## 3. 后端设计

### 3.1 技术栈（设计文档 13.2/2.3 锁定项 + 补齐）

- Python 3.12、uv workspace（members = apps/* + packages/*）；
- FastAPI（唯一 API 进程 `apps/api/edp_api`）、SQLAlchemy 2.0 async + asyncpg、Alembic、Pydantic v2 + pydantic-settings；
- 认证：PyJWT + argon2-cffi（API Key = SHA-256 哈希比对）；
- 测试：pytest + pytest-asyncio + testcontainers-python（PostgreSQL 16 容器，兼容 15）；
- 代码质量：ruff（lint+format）、import-linter（依赖规则）、mypy 不做门禁（W1 可选）。

### 3.2 模块结构（严格遵循设计文档 2.3.2）

```
backend/
├── apps/api/edp_api/{main.py, core/, modules/}
│   ├── core/{config,db,security,pagination,errors,audit,events,ports}.py
│   └── modules/{tenantmgmt,platform,registry,events}/  # W1 四模块，各含 router/service/models/schemas/dependencies
├── apps/worker/edp_worker/{main,scheduler,outbox_dispatch}.py
├── packages/adapters/            # W1 仅骨架包（端口 + 空注册表；实现在 W2 EDP-010）
├── migrations/                   # Alembic：version_locations 按 schema 分目录
└── tests/{unit,integration}/     # integration 用 testcontainers；跨租户用例集为 CI 必跑
```

依赖规则（import-linter 强制）：modules → core 单向；模块间仅经对方 service.py；core 不 import modules。

### 3.3 数据库与迁移（EDP-002 + 022）

- **基线迁移一次性转录附录 A 全部 15 Schema**（M1 出口条件①），含：全部表、索引、CHECK、RLS 策略（`tenant_id = current_setting('app.tenant_id')::uuid`，USING 与 WITH CHECK 双向）、角色与授权（`edp_migrator` BYPASSRLS；`edp_app` NOBYPASSRLS）；
- 审计字段统一：`created_at/updated_at/created_by/updated_by`（core 层 SQLAlchemy mixin，UTC）；
- 种子（data migration）：默认租户 `default`（ACTIVE）、平台 admin 用户（环境变量注入初始密码，Argon2id）、五角色 + role_permissions 权限矩阵、样例 API Key（agent-hub readonly，供联调）；
- `alembic upgrade head` 幂等；`downgrade base` 可回滚（DROP SCHEMA CASCADE 逆序）；
- 迁移文件按 schema 目录组织（version_locations 多目录、单线性链，满足"按 schema 分版本链"意图）。

### 3.4 认证与租户上下文（EDP-003 + 023）

- `POST /auth/login`：username+password（+tenant_slug 可选）→ 校验 Argon2id → 签发 access(2h, claims: sub/tenant_id/roles/principal_type/is_platform_admin) + refresh(7d)；SUSPENDED 租户登录 → 403 TENANT_SUSPENDED；
- `POST /auth/refresh` / `GET /auth/me`（返回 roles + permissions 展开列表）；
- API Key：`X-API-Key` → SHA-256 比对 → 加载 tenant_id + scopes + principal_type；
- 双轨依赖 `get_principal()`：JWT 或 API Key 二选一，统一 Principal 对象；
- RBAC：permissions 表驱动，路由声明所需 permission code（如 `registry:write`）；scope 越界 → 403；
- 租户上下文中间件：认证通过后每请求事务内 `SET LOCAL app.tenant_id`；API 连接用 `edp_app` 角色（受 RLS 约束）；无租户上下文的业务请求 → 403；租户状态非 ACTIVE（SUSPENDED/CANCELLED）→ 403 TENANT_SUSPENDED。

### 3.5 Registry / Events / Outbox（EDP-004/005/006）

- **POST /objects**（API Key write:registry；前端新建对象 W2 再开 JWT 通道）：upsert 语义，`expected_revision` 失配 → 409 + current_revision；自然键 `(tenant_id, source_system, object_type, source_id)` 唯一；
- **GET /objects/{id} / GET /objects（组合键筛选，游标分页） / GET /objects/{id}/history**（W1 history 从 `event.outbox`（aggregate_type='OBJECT'）聚合 revision 轨迹；W2 审计模块就绪后切换审计日志源）；
- **POST /events/batch**：Header `Idempotency-Key`；接口层幂等表（DB 降级形态，存响应摘要，TTL 24h）+ 数据层 `event_id` 主键 `ON CONFLICT DO NOTHING`（UUIDv5(tenant_ns, source_system|source_id|occurred_at|event_type)）→ 响应 `{accepted, duplicated, rejected, deduplicated}`；
- **GET /events / GET /events/{id}**：JWT/readonly，游标分页（cursor = opaque base64(occurred_at,event_id)）；
- **Outbox**：events/objects 写事务内同插 `event.outbox(PENDING)`；Worker 进程按租户循环：`FOR UPDATE SKIP LOCKED` 批取 → 进程内订阅者分发（W1：结构化日志订阅者 + EBMS 通知 stub）→ 成功 PUBLISHED；失败 `retry_count+1`、`available_at = now() + 2^retry × 5s`，≥8 次 → FAILED；单租户异常捕获隔离不中断循环。

### 3.6 契约治理（EDP-007）

- `backend/scripts/export_openapi.py`：导入 FastAPI app → json 序列化（排序稳定）→ 写 `contracts/openapi.json` + `contracts/openapi.sha256`；
- CI 后端门禁：导出结果与仓库快照 diff → 不一致失败；前端门禁：重算快照 sha256 与 api-sdk 生成时记录的指纹比对；
- `contracts/README.md`：变更流程模板（PR + Tech Lead 评审 + SDK 重生成三联动）。

## 4. 前端设计

### 4.1 工程结构（pnpm workspace，设计文档 2.3.3）

```
frontend/
├── apps/web/            # Vite + React 18 + TS5；app/ shell/ features/ components/ lib/
├── packages/shared/     # tokens/ enums/ permissions/ components/（框架无关）
└── packages/api-sdk/    # generated/（openapi-typescript 产物）+ client.ts + interceptors.ts
```

- 依赖：antd 5、@tanstack/react-query v5、react-router-dom v6、zustand、tailwindcss v4、lucide-react、msw、@storybook/react-vite、vitest；
- Tailwind v4 `@theme inline` 将 `--edp-*` CSS 变量映射为工具类色板（变量定义从原型 `<style id="theme-vars">` 原样拷贝，亮/暗两套）；
- Antd ConfigProvider 消费 packages/shared/tokens 的同一 TS 常量（13.4.1 映射表：colorPrimary=#5b5ce2、colorBgLayout=#f7f8fc、borderRadius=8 等，暗色切换另一组值）；
- 暗色模式：`html.dark` class + `prefers-color-scheme` 初始化 + localStorage 记忆（theme store，zustand）。

### 4.2 壳层与登录（EDP-103，视觉基线 = 原型各页公共壳）

- 登录 `/login`：卡片式（原型无登录稿，按壳层规范实现：Logo + 租户/用户名/密码 + 错误提示），对接真实 `/auth/login`；
- 壳层：250px 侧边栏（Logo 区 70px / 租户切换器静态卡片 / 四组导航含"智能闭环"组按角色可见 / 用户区）+ 66px 顶栏（面包屑 `data-slot="crumb"` / 330px 全局搜索 / 通知铃铛 / ⌘K 按钮 / 用户菜单）；
- 路由守卫：未认证 → /login；受保护路由 + 403/404 兜底页；
- W1 未开发页面统一占位页（"建设中"，复用空态模式）；
- `data-dom-id` 锚点沿用原型命名（tenant-switch/nav-overview/nav-objects/nav-events/nav-evidence/nav-quality/nav-governance/nav-systems/nav-tenants/global-search/notifications-btn/command-palette/settings-btn）。

### 4.3 9 核心组件（EDP-104，packages/shared/components）

| 组件 | 要点（13.7 规格） |
|---|---|
| StatusPill | 语义色字典（13.4.3）驱动；10~11px + 可选圆点 |
| FilterChips | removable chip（`关键词：x`）+ onClear |
| KpiCard | 10px 大写标签 / 大数值 / 辅助说明 / 右上图标（语义色底）；4→2 列响应式 |
| VerticalTimeline | 语义色圆点 + 时间/文本/关联 ID·来源 |
| ModalForm | 图标徽标 + 标题 + X；取消+主行动按钮；宽 480/520/640 三档 |
| EmptyState | 圆形底大图标 + 标题 + 引导文案 + 双动作（清除筛选/新建） |
| DangerConfirm | 一般删除轻确认；强确认=输入 slug 解锁（复用为 hook + 组件） |
| MonoId | 类型前缀 + UUID 前 4~8 位；复制 + tooltip 全量；哈希 `a4c1…9f3d` |
| CursorPagination | 左"显示 X–Y 条，共 N 条" + 右页码（next_cursor 驱动） |

每组件 Storybook 三状态（默认/边界/空）。

### 4.4 api-sdk 管线（EDP-105）

- `pnpm --filter api-sdk gen`：`openapi-typescript ../../contracts/openapi.json -o src/generated/schema.d.ts`；
- 生成时同时记录 `src/generated/fingerprint.json`（快照 sha256）；CI 前端门禁脚本重算比对；
- client.ts：fetch 封装（baseURL 环境变量、Bearer 注入、JSON 错误结构解析）；interceptors.ts：401 刷新单飞/429 退避/TENANT_SUSPENDED 横幅事件（W1 实现机制与单测，页面级消费 W2 展开）。

## 5. CI（GitHub Actions）

- `.github/workflows/backend.yml`：路径 `backend/** contracts/**` → uv sync → ruff → import-linter → pytest unit → testcontainers 集成（services 起 Docker 或 testcontainers 自管）→ alembic upgrade head 容器实跑 → 契约导出 diff 门禁；
- `.github/workflows/frontend.yml`：路径 `frontend/** contracts/**` → pnpm install → eslint + vitest + tsc → storybook build → SDK 指纹门禁；
- 迁移门禁：CI 内 PG 容器 `alembic upgrade head` 后 `alembic downgrade -2` 冒烟。

## 6. 实施顺序（后端先行）

1. git init + 仓库根骨架（contracts/ deploy/ .github/）+ backend workspace + CI 文件 + compose（EDP-001）；
2. 附录 A 全量 DDL → Alembic 基线 + RLS + 种子，Docker PG 实跑验证（EDP-002 + 022 DDL）；
3. core（config/db/errors/pagination/security）+ 认证 API + 租户中间件（EDP-003 + 023）；
4. registry + events 模块 + outbox 写侧 + worker 分发（EDP-004/005/006）；
5. 契约导出 → contracts/ 快照（EDP-007）；
6. 跨租户隔离 + 全量集成用例进 CI（EDP-022 集成部分收口）；
7. 前端脚手架 + 令牌/主题/暗色 + Storybook（EDP-101 + 102）；
8. 壳层 + 登录 + 占位页 + 路由守卫（EDP-103）；
9. 9 组件 + Storybook 三状态（EDP-104）；
10. api-sdk 生成管线 + 指纹门禁（EDP-105）；
11. 端到端验证：compose 起 db+api+worker+web；登录→壳层→主题切换→退出；本地全量 CI 等效命令跑绿。

## 7. 验证清单（本地实跑）

- [ ] `alembic upgrade head` ×2 幂等；`downgrade base` 后再 upgrade 成功；
- [ ] pytest 单测（密码哈希/token 过期/scope 越界/UUIDv5 确定性/游标编解码/退避计算）全绿；
- [ ] testcontainers 集成：登录→建对象→并发 upsert 409→事件批量→重放 duplicated→outbox PUBLISHED→跨租户 A/B 矩阵 0 泄露；
- [ ] ruff + import-linter 通过；
- [ ] contracts/ 快照生成且 sha256 一致；
- [ ] 前端 eslint + vitest + tsc + storybook build 通过；
- [ ] `pnpm dev` 起动；登录真实后端成功；主题切换 localStorage 记忆；
- [ ] compose 全套起；浏览器走查壳层与登录/退出。

## 8. 非目标（明确排除）

- W2+ 任务：证据/审计/适配器/EBMS/Trace/Memory 等模块与页面；
- 21 主页面中除登录/壳层/占位外的业务页面实现；
- Redis、MQ、Patroni HA、备份（W5）；
- Playwright E2E 与视觉回归基线（W6 EDP-602/603，W1 仅预留 data-dom-id）。

## 9. 偏差登记（评审后批准）

- **ModalForm 位于 apps/web 而非 packages/shared**：实现依赖 antd（Modal/Form 组件与 Web 技术栈耦合，shared 为框架无关的 antd-free 层），plan T20 已载明该取舍，属既定决策非漏项。
- **种子 API Key scopes 含 write:event / write:registry**：B.2/B.3 写路径（POST /objects、POST /events/batch）仅支持 API Key 认证（JWT 人主体走权限轨），规格 §3.3 所写 "readonly" 为笔误；种子以 `['readonly','write:event','write:registry']` 落地（migrations/platform/0005_seed）。
- **session-store（zustand persist）超出 §13.2 字面清单**：§13.2 未覆盖"无服务端会话端点时 token/用户/租户的客户端持久化"场景；W1 无 logout/会话查询端点，localStorage 持久化（`edp-session`）是该形态下登录态续存与租户切换展示的必要客户端状态。
