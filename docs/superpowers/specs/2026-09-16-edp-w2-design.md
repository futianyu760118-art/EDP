# EDP 第二周任务（W2：总览/对象页 + 数据链路）

| 项 | 内容 |
|---|---|
| 日期 | 2026-09-16 |
| 状态 | 已获用户批准（对话中逐节确认：Section A 前端 / Section B 管道+证据 / Section C 审计+租户+收口） |
| 上游依据 | 《EDP数据平台开发计划_一阶段.md》W2 任务（EDP-008/009/010/024、EDP-201~203）、M2 出口条件；《EDP数据平台系统设计文档_V2.0.md》4.2/4.3（适配器与管道）、B.4（证据）、B.6（审计）、B.12（适配器运维）、B.14（租户管理）、13.6.1/13.6.2（页面规格）、13.9.2（错误映射） |
| 前置 | W1 已合并（M1 契约冻结）；W2/W3 MSW 数据层已合并（27 handler + fixtures + 50 测试） |
| 不改动 | W1 冻结契约既有端点的语义、既有测试基线、EBMS/质量/Trace/Memory 模块（W3+） |

## 1. 背景与范围决策

周五（M2，W2 周五）需前端可展示 + M2 数据链路演示。用户确认的决策：

1. **交付策略 = 方案一「两波交付」**：第一波纯前端页面（MSW 驱动，落地即可演示、周五保底），第二波纯后端数据链路（完成后关 `VITE_USE_MSW` 切真实数据双模式演示）；
2. 审计模块做**完整 EDP-009**（切面 + 月分区 + 查询 API），非最小版；
3. 管道触发 = **make 脚本 + sync API 最小版**（B.12），worker 定时调度不做（W4 适配器页再上）；
4. **含 EDP-024** 租户生命周期最小集（M2 出口条件「开通→暂停→恢复可演示」）；
5. 总览页图表**纯 SVG 自绘**（零图表库依赖，与原型像素对齐）。

任务范围：EDP-201/202/203（前端）+ EDP-008/009/010/024（后端）+ M2 对账收口。
不在范围：EDP-011/012/013/014/025（W2 计划内但非 M2 关键路径，下轮补）、事件流/证据库页面（W3 EDP-301/302）、租户成员/配额编辑 API（W5）。

## 2. Section A：第一波——前端三任务（MSW 驱动）

### 2.1 目录结构（feature-sliced 约定）

```
apps/web/src/features/
├── overview/     # EDP-202：OverviewPage + HeroCard + KpiGrid + RiskDrawer + 图表
└── registry/     # EDP-203：RegistryPage + ObjectCard/Table + CreateModal + DetailDrawer
```

### 2.2 EDP-201 收尾（拦截器页面级消费）

- `TENANT_SUSPENDED` 从 W1 toast 占位升级为 AppLayout 顶栏下方**常驻横幅**（warning 色 +「联系平台管理员」），`data-dom-id="tenant-suspended-banner"`；
- 全局 `queryClient` 错误回调统一 toast（NETWORK_ERROR 等未被页面捕获的错误）；
- 补齐 13.9.2 的 **13 种错误码 → 文案映射表**（放 shared）及单测，复用 MSW `lib/scenario.ts` 场景注入验证。

### 2.3 EDP-202 运营总览 `/admin/overview`

视觉基线：`原型设计/pages/运营总览.html` + `风险详情 - 抽屉.html`。

| 区块 | 实现 | 数据源（MSW handler 均已有） |
|---|---|---|
| Hero 状态卡 | 运行 pill + 动态标题（f(P1 数)）+ 查看风险/导出日报按钮 + 内嵌三指标（对象覆盖率/P95 延迟/适配器成功率） | `GET /admin/quality/coverage` + `GET /health?deep=true` + `GET /admin/adapters` |
| 8 KPI 网格 | 复用 `KpiCard`（日环比/角标着色） | 同上聚合派生 |
| 风险列表 ×3 | 等级 pill + `MonoId` 短 ID + 点击开风险抽屉 | `GET /ebms/exceptions?severity=P1&limit=3` |
| 风险抽屉 | 右侧 420px、避让侧边栏：头部（RSK-短ID+等级+状态/类别/时间）→ 受影响对象卡（2 迷你指标格）→ 事件时间线 4 节点 → 关联证据行 → 底部操作 | exceptions + events + evidence |
| 事件时间线 | `VerticalTimeline` 5 节点 +「进入事件流」 | `GET /events?limit=5` |
| 三栏图表 | 数据健康（24H mini 柱图，纯 SVG）/ 证据链健康（环形进度 SVG stroke-dasharray + Primary/Derived 计数）/ 审计动态 4 条 | quality reports + evidence + `GET /audit-logs?limit=4` |

- 30s 轮询：React Query `refetchInterval: 30_000`；**每面板独立 query + 独立错误/空态**（真实模式下无 quality 后端时单面板降级，不拖垮整页）；
- 布局复用 W1 `app.css` 的 `kpi-grid/three-col/page-shell`。

### 2.4 EDP-203 业务对象 `/admin/registry`

视觉基线：`业务对象.html` + `业务对象 - 空态.html` + `新建业务对象 - 弹窗.html`。

- 工具栏：搜索（ID/名称/来源）+ 域下拉 + 状态下拉 + 卡片/表格分段切换 + 筛选（`FilterChips` 呈现已生效筛选）；
- 卡片视图：等级 pill + 类型标签 + `source_id`（mono）+ 名称 + 域·来源 + 风险评分进度条（0-100 按等级着色）+ 标签 chips + `Rev N · 时间`；表格视图列对齐原型；
- **派生状态前端计算**：`f(最新能力结果 risk_level, DQ 异常, 同步时延)` → Healthy/Watch/At Risk/Blocking/DQ Exception/Delayed（纯展示不落库，13.6.2 派生规则）；
- 新建弹窗：复用 `ModalForm`；字段：对象名称*/对象编码*/所属域* select/数据来源* 多选 chip/责任人/描述；行内校验文案与原型逐字一致（「对象名称不能为空，且不能与已有对象重复」）→ `POST /objects`（409 → 「编码已存在」映射）；
- 详情抽屉：基本信息 + `GET /objects/{id}/history` revision 时间线（`VerticalTimeline`）；
- 空态：search-x 图标 +「新建对象 / 清空筛选」双动作；分页 `CursorPagination`；
- JWT 通道：`POST /objects` 走 JWT `require_write("registry")`（W1 principal 双凭据已支持；后端波顺带确认 seed 角色矩阵含 `registry:write`，缺失则补）。

### 2.5 前端测试

每页 Vitest（MSW node server）：渲染 + 交互（筛选/分页/新建校验/抽屉开合/横幅）+ 轮询行为；`data-dom-id` 锚点齐备；预计 +60~80 用例。

## 3. Section B：第二波（一）——EDP-010 管道 + EDP-008 证据

### 3.1 适配器包（`backend/packages/adapters/edp_adapters/` 骨架补齐）

| 文件 | 内容 |
|---|---|
| `base.py` | `SourceRecord` 补齐：`{source_system, object_type, source_id, occurred_at, payload, prev_hash?}`；`SourceAdapter` Protocol（`fetch_full(object_types)` / `fetch_incremental(since)` / `health_check()`）；`AdapterHealth` |
| `registry.py` | `AdapterRegistry` 实装：启动注册、按名查找 |
| `erp_mock.py` | `ErpMockAdapter`：确定性种子生成 ORDER/CUSTOMER/MATERIAL 记录（全量 ~60 条；`incremental(since)` 返回水位后新记录；同 seed 重放结果一致） |
| `pipeline.py` | `run_sync(adapter, mode, session)`：转换管道 + 统计 `{fetched, registered, duplicated, failed}` |
| `cli.py` | `python -m edp_adapters.cli full|incremental|reconcile`（bind_tenant 走 RLS，供 make 调用） |

### 3.2 转换管道（设计 4.3：逐条单事务，`SET LOCAL app.tenant_id` RLS 全程生效）

1. 对象 upsert：复用 `registry.service` 现有 upsert（revision+1 乐观锁）；
2. 事件：`event_id = UUIDv5(source_system|source_id|occurred_at|event_type)`——重放同记录 → 幂等跳过（duplicated 计数）、**不动 revision**；
3. 证据：snapshot + `checksum = SHA-256(canonical_json(payload))`，`source_record_id = "{source_id}#v{revision}"`；
4. Outbox 同事务写入（复用 events 模式，Worker 既有分发链路复用）。

- **增量水位**：`max(event.events.occurred_at) WHERE source_system = <adapter>`，持久化于 `platform.systems.config`；
- **迁移 0008**：`platform.systems` 加 `config JSONB DEFAULT '{}'`（承载 `adapter_mode=mock|real` + 水位）；补 `adapters:read/write` 权限码 + 角色矩阵行。

### 3.3 sync API（B.12 最小版，modules/adapters 新模块）

- `POST /admin/adapters/{name}/sync {mode: full|incremental}` → 202 `{sync_id, status: RUNNING, started_at}`；进程内 `asyncio.create_task` 执行（演示量级毫秒级完成），内存 sync registry 供 status 查询；
- `GET /admin/adapters/{name}/status` → `{adapter, mode, last_sync: {sync_id, finished_at, stats}, health}`；
- `GET /admin/adapters` → 清单与运行状态；
- JWT ADMIN（`adapters:read/write`）；Worker 定时调度不做。

### 3.4 EDP-008 证据 API（modules/evidence 新模块，六文件模式，B.4 四端点全量）

| 端点 | 要点 |
|---|---|
| `POST /evidence` | API Key `write:evidence` / JWT；checksum **服务端算**；`links[]` 可选随行建链 |
| `GET /evidence/{id}` | JWT/readonly；跨租户统一 404 不泄露 |
| `GET /evidence/{id}/verify` | 重算 canonical JSON SHA-256 比对；**失败 → 写审计告警（action=EVIDENCE_VERIFY_FAILED, risk=P1）** + `valid:false` |
| `GET /evidence?ref_type=&ref_id=&object_id=&limit=` | 逆向追溯（links 表索引已有），游标分页 |

`canonical_json` 单一实现（键排序 + 紧凑分隔符），管道与 verify 共用，防算法漂移。

## 4. Section C：第二波（二）——EDP-009 审计 + EDP-024 租户 + M2 收口

### 4.1 EDP-009 Audit Log（完整）

- **仅追加月分区**：`platform.audit_logs` 表已建（0001，PK 含 occurred_at）；0008 预建当月+未来 2 月分区 + `ensure_audit_partitions()` 幂等 SQL 函数；
- **强制仅追加**：0008 `REVOKE UPDATE, DELETE ON platform.audit_logs FROM edp_app`（验收「UPDATE/DELETE 被拒」直证）；
- **审计切面（全部写操作自动记 before/after）**：SQLAlchemy `before_flush` 会话事件捕获 new/dirty/deleted → 字段白名单序列化 + 敏感字段脱敏 + 截断 → **同事务**插 audit_logs；principal/action 取自 W1 contextvars；audit 行自身排除（防自引用）；GUARD_DENIED/verify 告警由 security 层显式写；挂载点 `core/db.py` 会话工厂，全部模块零改动获得审计；
- **查询 API**（modules/audit 六文件模式）：`GET /audit-logs?actor_id&resource_type&action&since&until&limit`——JWT ADMIN，游标分页，响应结构对齐已有 MSW fixtures。

### 4.2 EDP-024 租户生命周期（B.14 最小集）

| 端点（平台 ADMIN，新依赖 `require_platform_admin`：is_platform_admin 或 PLATFORM_ADMIN 角色） | 说明 |
|---|---|
| `POST /tenants` | 开通原子：租户 + 初始管理员（随机密码）+ 默认配额（按 plan 映射） |
| `POST /tenants/{id}/suspend` / `resume` | 202；暂停后该租户全部 API 即时 403 TENANT_SUSPENDED（W1 状态墙复用） |
| `POST /tenants/{id}/cancel` | Human-Only：`confirm:true` + `reason` 必填，缺失 422 |
| `GET /tenants` / `GET /tenants/{id}` | 平台 ADMIN 列表/详情（为 W5 切换器铺路） |

成员/配额编辑 API 不含（W5）。演示用新建租户（如 acme）走全流程，不动 default 租户。

### 4.3 M2 收口

- **对账**：`make reconcile`（`cli reconcile`）——源清单数 vs objects/events/evidence 落库数按 (source_system, object_type) 比对，输出偏差表，0 偏差 exit 0；
- **契约回填**：新端点（evidence/audit-logs/adapters sync/tenants CRUD）按 EDP-007 流程更新 `contracts/openapi.json` + sha256 + api-sdk 重生成；MSW fixtures 与真实契约漂移处对齐（跨页一致性测试防漂移）；
- **演示脚本**：`docs/demo/m2-demo.md` 七段叙事（MSW 总览 → 对象页 → 切真实模式 → make pipeline-full → 对象页真实数据 → verify 篡改演示 → 租户生命周期 curl）。

## 5. 验收映射（M2 出口条件）

| M2 出口条件 | 载体 |
|---|---|
| Mock ERP→管道→落库→控制台可见 | 对象页 `VITE_USE_MSW=0` + `make pipeline-full` |
| 对账 0 偏差 | `make reconcile` + 集成测试断言 |
| 租户开通→暂停→恢复全流程可演示 | 集成测试全流程 + curl 演示 |
| 篡改 snapshot → verify false + 审计告警 | 集成测试（migrator 直改行） |
| 全量+增量混合回放 0 重复、revision 递增正确 | 集成测试 |
| 任意写操作审计行含 before/after；UPDATE/DELETE 审计表被拒 | 集成测试（edp_app 角色直证） |
| 前端页面演示 | 总览 + 对象页（MSW）+ 新增单测（前端 +60~80、后端 +40~50） |

## 6. 工程约定

- 分支：`feat/w2`（第一波前端 merge 后续第二波）；
- 后端新模块沿用六文件模式（router/service/schemas/models/dependencies/__init__）；
- 全部新表/列变更集中于迁移 `0008`（systems.config、audit 分区与 REVOKE、新权限码）；
- CI 门禁全绿为合并条件（后端 lint+单测+集成、契约指纹、前端 lint+Vitest）。
