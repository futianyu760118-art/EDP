# EDP 第五周（W5：可靠性与质量 M5 + W4 遗留收编）

| 项 | 内容 |
|---|---|
| 日期 | 2026-09-20 |
| 状态 | 已获用户批准（对话逐项确认：范围=计划全量+W4 遗留、Redis 仅评估；演练环境=staging 兼任、prod 试运行记缺口；「连续 3 天」备份验证=任务化+连续 N 次等价证据+偏差登记；备份存储=staging 加 MinIO 容器迁 S3；编排=仿 W4 两波+独立演练线） |
| 上游依据 | 《EDP数据平台开发计划_一阶段.md》W5 任务（EDP-027/030/031、EDP-501~503；EDP-032 已于 W4 提前完成）+ M5 出口条件；《EDP数据平台系统设计文档_V2.0.md》9.1~9.3/9.6（可靠性/质量/可观测）、B.13（质量契约）、B.14（租户管理契约）、13.7/13.8/13.9（交互/多租户前端/错误码）、附录 D（页面映射）；W4 缺口清单 W4-01~13（m2-demo.md）；staging-drill.md 后续项 |
| 前置 | W4 已合并 master（后端 618 / 前端 302 测试基线；契约 53 路径指纹 `687b6cd7`；staging patroni×2+etcd+pgbackrest 双向 switchover 已演练） |
| 不改动 | W1~W4 冻结契约既有端点语义（新增端点/可选字段除外）；既有测试基线只增不破；限流令牌桶与审计策略缓存的进程内实现（外置统一走 Redis 评估，W6 决策） |

## 1. 范围与决策

本轮 = **W5 全量 + W4 明确留 W5 项**，单分支 `feat/w5` 两波 + 独立演练线：

1. **波1 后端（T1~T9）**：迁移 0013（ops.tasks，T1）、B.14 租户 API 补齐（T2）、质量 API（EDP-030，B.13 逐字段，T3/T4）+ 适配器同步历史（W4-07 收口，T5）+ evidence reindex（W3-04 收口，T6）、演练记录 API（EDP-502 后端，T7）、Minor 修复批（T8）、契约冻结（T9，波1 闸门）；
2. **波2 前端（T10~T13）**：EDP-501 租户 6 页 + 4 弹窗（T10）、EDP-502 演练回放页（T11）、EDP-503 Agent 三页（T12）、真模式对接批（质量页/健康页备份卡/证据重索引/Bell 消息中心，T13）；
3. **演练线（并行，不碰 `contracts/` 与前后端代码）**：MinIO 入拓扑 → pgbackrest 迁 S3 → 备份调度容器化 + 恢复验证任务化（连续 N 次等价证据）→ PITR 整库恢复演练 → 租户级恢复演练 → HAProxy 单写入口（api 自动跟随主切换）→ 读数归档 `docs/demo/w5-drills.md`。

**不在范围**：prod 环境搭建与试运行启动（记缺口/W6 前置项——用户批准口径：staging 兼任）；Redis 实际外置（仅评估文档）；`GET /admin/outbox/status`（W6 运营报告随 EDP-034 评估）；Playwright E2E（W6）；真实外部源系统接入（Mock 基线不变）。

**关键决策与理由**：
- **演练环境 = staging 兼任**：M5 出口三项演练全部在 staging（本机 Docker Desktop）实测归档；「prod W5 起试运行」记缺口，不虚报（偏差登记 §13）。
- **备份验证「连续 3 天」→ 任务化 + 连续 N 次**：每日备份+恢复验证任务化（容器 cron + 手动触发），收口前以「连续 N≥3 次成功 + 任务化证据」等价收口，偏差登记；后续自然累计 3 天归档。
- **备份存储迁 MinIO（S3 兼容）**：staging 拓扑加 MinIO 容器，pgbackrest repo 迁 `type=s3`；PITR/租户恢复均从对象存储恢复——对齐设计 9.2「独立于数据库卷的持久卷/对象存储」。
- **异步任务统一落库（ops.tasks）**：质量重校验/证据重索引/适配器同步历史共用一张 RLS 表；适配器 `_jobs` 内存态迁 DB（**顺带收口 W3-41/42 的 jobs 单副本语义**——多副本安全；限流/审计策略缓存仍单副本，留 Redis 评估）。
- **演练记录数据源 = 仓库 JSON + 只读 API**：`deploy/drills/drill-records.json`（演练线唯一写者）+ `GET /admin/drills` 读取——静态归档值不建表，W6 运营报告可复用同一 JSON。
- **消息中心最小版**：复用 `GET /events`（前端过滤 `quality.*` 前缀）+ Bell 下拉最近 20 条 + localStorage 未读计数；不新增通知 API（B 原文「写 event + 通知」的 event 半边已落，通知半边前端承接——W4 规格同口径延续）。

## 2. Section A：迁移 0013（T1）

`backend/migrations/versions/platform/0013_w5_baseline.py`（`_exists` 幂等守卫，风格同 0012）：

1. **ops.tasks 表**（RLS + 审计字段，租户级）：
   ```sql
   CREATE TABLE ops.tasks (
       task_id     UUID PRIMARY KEY,
       tenant_id   UUID NOT NULL REFERENCES platform.tenants(tenant_id),
       task_type   TEXT NOT NULL CHECK (task_type IN
                   ('quality_recheck','evidence_reindex','adapter_sync')),
       status      TEXT NOT NULL DEFAULT 'RUNNING'
                   CHECK (status IN ('RUNNING','SUCCEEDED','FAILED')),
       scope       TEXT,           -- recheck: RECONCILE|ORPHAN|CHECKSUM|ALL；reindex: 全量/条件；sync: full|incremental
       ref_name    TEXT,           -- adapter_sync 适配器名；其余可空
       stats       JSONB NOT NULL DEFAULT '{}',   -- 各类型自定：计数/偏差/抽样结果/sync 四计数
       logs        JSONB NOT NULL DEFAULT '[]',   -- [{ts, level, message}] 追加式
       started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
       finished_at TIMESTAMPTZ
   );
   CREATE INDEX ix_tasks_tenant_type ON ops.tasks (tenant_id, task_type, started_at DESC);
   ```
   RLS 策略沿既有 `USING (tenant_id = current_setting('edp.tenant_id')::uuid)` 模式；upsert 无需唯一约束语义冲突（started_at 天然区分）。
2. **权限码**（uuid5 惯例，rbac.py 矩阵同步，计数断言 21→23）：
   - `quality:read`（quality, read）→ PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST（与 audit:read 同角色集——只读分析面）；
   - `quality:run`（quality, run）→ PLATFORM_ADMIN/ADMIN（rechecks/reindex 触发）。
3. **适配器 `_jobs` 迁移兼容**：无 DDL 依赖；service 改造在 T5（本迁移仅落表与权限）。

## 3. Section B：B.14 租户 API 补齐（T2，tenantmgmt 扩展，EDP-501 后端）

全部挂 platform_router（`require_platform_admin`，不挂 tenant_scoped），members/usage 两端点另开**租户内 ADMIN 轨道**（W3R-04 收口）。B.14 逐字段：

| 端点 | 鉴权 | 要点 |
|---|---|---|
| PATCH `/tenants/{id}` | 平台 ADMIN | `{name?, plan?}`；200 完整租户对象；404 跨平台不存在 |
| POST `/tenants/{id}/context` | 平台 ADMIN | 切换自身会话目标租户上下文；200 `{tenant_id, switched_at, note}`；后续请求以目标租户执行，**全程审计**（平台面审计行带 from/to） |
| GET `/tenants/{id}/members?limit=` | 平台 ADMIN / 租户内 ADMIN（本租户） | 游标分页；投影 member_id/user_id/display_name/member_roles/status/joined_at |
| POST `/tenants/{id}/members` | 平台 ADMIN | `{user_id, member_roles}`；201 成员对象；已在册 409 |
| PATCH `/tenants/{id}/members/{mid}` | 平台 ADMIN | `{member_roles?, status?}`（改角色/禁用）；200 更新后对象；不可禁用最后一个 ACTIVE ADMIN（400） |
| GET `/tenants/{id}/quotas` | 平台 ADMIN | 完整配额对象（B.14 七字段） |
| PATCH `/tenants/{id}/quotas` | 平台 ADMIN | `{api_rate_limit?, storage_gb?, events_per_month?, reason}`；reason 必填（临时提额留痕）；200 更新后对象；审计 |
| GET `/tenants/{id}/usage?since=&until=` | 平台 ADMIN / **租户内 ADMIN（本租户，W3R-04）** | 既有端点扩展轨道：租户 ADMIN 经 tenant_scoped 路由查本租户（新 `router.py` 挂 `/tenants/current/usage` 或复用路径按主体判定——实现取「`/tenants/{id}` 路径 + 主体为该租户 ADMIN 放行」最小改动，记缺口清单） |

- context 切换实现：平台 ADMIN 的 JWT 增发 `act_tenant` claim（refresh 端点扩展或专用签发），中间件优先级 `act_tenant > 绑定租户`；SUSPENDED 目标租户拒绝切换（403 TENANT_SUSPENDED）；
- 租户切换与前端 13.8 的对接（全站缓存清空重拉）在 T9 前端完成。

## 4. Section C：质量 API 与任务轨道（T3/T4/T5，EDP-030 + W4-07 + W3-04）

新模块 `modules/quality`（六文件模式）。鉴权：读 `quality:read`，触发 `quality:run`。

### 4.1 报告端点（T3，B.13 逐字段）

| 端点 | 要点 |
|---|---|
| GET `/admin/quality/reports?date=` | 200 四段聚合：`reconciliation[]`（source_system/object_type/source_count/edp_count/deviation_pct/ok）、`coverage`（overall_pct + by_type[]）、`orphans`（event_orphans/evidence_orphans 计数）、`checksum_sampling`（sampled/failed）。**date 参数接受但当前按实时计算返回**（报告日期=请求日；预聚合留 W6——记缺口）；另含 MSW 扩展字段 `kpi`/`dimensions`（质量页 KPI 带与维度评分，真数据派生：pending=OPEN 异常、high=P0/P1、四维度评分由四段结果派生），对齐 mocks/types.ts 既有形状 |
| GET `/admin/quality/coverage` | 覆盖率简报（`coverage` 字段同形）——Go/No-Go ≥95% 周报数据源 |

**口径定义**（写死在 service docstring + 测试断言）：
- **对账**：`(source_system, object_type)` 分组——`edp_count` = projections 领域快照行数；`source_count` = 适配器声明的期望基数（Mock 确定性数据集常量；real/无水位时 `source_count=null, ok=true` 降级呈现）；`deviation_pct = |source-edp|/source×100`，阈值 >2% 即 `ok=false`；
- **覆盖率**：已接入对象（≥1 event 或 ≥1 evidence 关联）/ 注册对象，overall 与 by_type 双口径；
- **孤儿**：`event.events.object_id` 无对应注册对象计数；`evidence.records` 悬挂计数（object_id 非空且无注册对象）；
- **checksum 抽检**：P0/P1 证据（按 ref 关联事件 risk_level）抽样（每日上限 120 或全量取小），重算 canonical checksum 比对，failed 计数；失配写 `event.events(event_type=quality.checksum_failed)` + 审计告警。

### 4.2 任务轨道（T4，202 异步 + 轮询，形状对齐 MSW 既有 handlers）

| 端点 | 要点 |
|---|---|
| POST `/admin/quality/rechecks` | `{scope: RECONCILE\|ORPHAN\|CHECKSUM\|ALL}` → 202 `{task_id, status:"RUNNING"}`；后台执行对应检查并写 ops.tasks（stats 携带结果摘要）；完成时质量事件落库（`quality.recheck_succeeded/failed`） |
| GET `/admin/quality/tasks/{task_id}` | 200 `{task_id, task_type, status, scope, stats, logs[], started_at, finished_at}`；404 跨租户；RUNNING 时可轮询 |

- 后台执行沿用 staging 单副本语义（FastAPI BackgroundTasks + 进程内执行、状态落库）——多副本安全由 ops.tasks 落库保证，执行互斥不保证（单副本部署语义，docstring 留痕，Redis 评估覆盖）。

### 4.3 适配器同步历史（T5，W4-07 收口）

- `adapters_admin/_jobs` 内存 dict **移除**，job 状态写透 ops.tasks（task_type=adapter_sync，ref_name=适配器名，stats=四计数，logs=进度行）；
- `GET /admin/adapters/{name}/status`：读 ops.tasks 该适配器最近一条；响应形状不变（既有契约兼容）；
- `GET /admin/adapters/{name}/jobs?limit=`（**新增**）：历史任务列表（游标，started_at DESC）——适配器页日志抽屉「完整任务日志」真数据源；W5 提示文案移除。

### 4.4 证据重索引（T6，W3-04 收口）

- `POST /admin/evidence/reindex`（`quality:run`）：`{scope?: ALL|TENANT}` → 202 任务（task_type=evidence_reindex）；后台重算全量 evidence canonical checksum 并回写（失配计数进 stats + 质量事件）；`GET /admin/quality/tasks/{id}` 复用轮询；证据库页重索引三步向导接线（真模式按钮启用）。

## 5. Section D：演练记录 API（T7，EDP-502 后端）

- `deploy/drills/drill-records.json`：三项演练记录（switchover/PITR/tenant-restore），每项 `{drill_type, executed_at, topology, rto_seconds, rpo_seconds, result, readings{}, manual_url}`；演练线唯一写者（T14~T16 实测回填）；
- `GET /admin/drills`（`quality:read`，平台 ADMIN 语义沿用）：读 JSON 返回 `{items: [...]}`；文件缺失 → 空列表（不报错，前端空态）；
- 无 DB、无迁移；文件随仓库版本化即归档。

## 6. Section E：Minor 修复批（T8，一次 commit）

1. **JWT 弱密钥（W4-12）**：staging compose `EDP_JWT_SECRET` 换 64+ 随机字符（compose 内置演示值 + 注释「生产经 secret manager 注入」）；dev 不变（本地语义）；
2. **词表预留前缀（W4 终审 Minor）**：audit 页 vocab.ts 预留 `POLICY_*`/`QUALITY_*` 前缀映射；
3. **notify_channel 演示文案（W4 终审 Minor）**：审计策略弹窗通知渠道占位文案对齐「站内消息（email 预留）」。

## 7. Section F：契约冻结（T9，波1 收口）

- `make contract-export`：新增路径（tenants PATCH/context/members×3/quotas×2、quality×4、adapters jobs、drills、evidence reindex ≈13 路径）+ context 签发相关 schema；
- sha256 重算 + api-sdk regen + `make contract-gate` 绿；波2 不改 `contracts/`；
- 缺口清单 W5-nn 初稿（预期：usage 双轨路径形态、reports 无预聚合、执行互斥单副本、outbox/status 未做、prod 缺口、连续 3 天等价）。

## 8. Section G：波2 前端（T10~T13）

| 任务 | 页面 | 要点 |
|---|---|---|
| T10 EDP-501 | 租户管理列表/详情/成员/配额 + 新建租户/邀请成员/权限分配/租户切换 4 弹窗 + 暂停/恢复/注销 | 视觉基线 6 稿逐字（租户管理/新建租户/邀请成员/权限分配/租户切换/删除确认）；注销强确认=输入 slug 解锁（删除确认稿语义）；`TenantSwitchModal` 接 `POST /context` 真调用：切换后 queryClient 清缓存全站重拉（13.8）+ 顶栏租户名更新；权限分配弹窗写 members PATCH |
| T11 EDP-502 | 演练回放页（运维监控组） | 三项演练只读记录卡：结果 pill/RTO/RPO 实测值/拓扑摘要/读数表（readings key-value）+ 手册链接（docs/demo/w5-drills.md 与 staging-drill.md 仓库相对路径说明）；`GET /admin/drills` 真数据 + MSW handler；空态三件套 |
| T12 EDP-503 | Agent 工具/Trace/记忆三页（无稿，13.7 模式） | 工具页：六接口在线试查表单（对象类型+查询键）→ 只读 JSON 结果 + evidence_hint 链接（跳证据库）；Trace 页：列表（游标）+ 详情展开 DAG（tool_calls 树 + token_usage 汇总卡）；记忆页：候选列表（capability 筛选）+ 评审状态 pill |
| T13 真模式对接批 | 质量页/健康页/证据库/顶栏 Bell | 质量页 KPI/维度接真 reports（MSW kpi/dimensions 注释「EDP-030 落地后替换」兑现）、重校验弹窗/任务日志抽屉接真 tasks（抽屉历史下拉接 adapters jobs）；健康页备份卡接 drills 读数（最近备份时间/大小/可恢复性 N/N）；证据库重索引向导真模式启用；Bell 下拉=events 过滤 `quality.*` 最近 20 条 + localStorage 未读计数（最小消息中心） |

MSW handlers 同步补：tenants 平台面、drills、quality tasks 真形状微调（若有）、adapters jobs；fixtures 跨页一致性断言维持。

## 9. Section H：演练线（T14~T16，staging，不碰代码契约）

按序执行，读数全部归档 `docs/demo/w5-drills.md`（+ 回填 drill-records.json）：

1. **MinIO + pgbackrest 迁 S3**（T14）：staging compose 加 `minio`（console 9001 暴露）+ bucket 初始化；pgbackrest `[repo] type=s3`（endpoint=minio:9000，path-style）；验证 `stanza-create` + 全量备份到 S3 + `info` 读数；
2. **备份调度 + 恢复验证任务化**（T15a）：pgbackrest 容器内置 cron（每日 02:00 全量）+ `verify` 入口（`check` + 抽样恢复临时库 + 行数抽样断言）；`deploy/scripts/backup-verify.ps1` 手动触发；**连续 N≥3 次成功**为 M5 等价证据（偏差登记）；验证日志追加式归档；
3. **PITR 整库恢复演练**（T15b）：基础备份 + WAL 重放至目标时点（目标=写入标记行后 1min）；恢复至新实例 → 标记行存在 + 数据校验（对账端点复跑）；RTO/RPO 实测（RTO ≤2h 目标、RPO ≤5min 目标）；
4. **租户级恢复演练**（T15c）：模拟租户数据误删（DELETE 该租户业务数据）→ `pg_dump --table` 逻辑导出（按 tenant_id 过滤，BYPASSRLS 运维账号 + 全程审计）→ 恢复至隔离库 → 校验 → 按表回放 → 抽样行数/校验和比对；RTO 实测（≤4h 目标）；
5. **HAProxy 单写入口**（T16）：staging 加 haproxy 容器（5432 → 主库，8008 健康检查选主）；api/worker `DATABASE_URL` 改指 haproxy；重跑 switchover 演练验证**连接自动跟随零改配**；/health 连续探测中断秒数对比 W4 读数。

降级预案：MinIO 不可用 → 回退本地 repo 卷（记录缺口）；宿主资源不足 → 演练按「拓扑冒烟 + 命令演练」降级并记录（沿 W4 预案口径）。

## 10. Section I：Redis 评估 + 收口（T17/T18）

- **Redis 外置评估文档**（`docs/redis-evaluation.md`）：三处单副本点位（限流令牌桶 W3R-01、审计策略缓存 W4-03、quality 任务执行互斥）× 方案对比（Redis / PG advisory lock + 表缓存 / 保持单副本+HAProxy 单写入口语义）+ 建议 + 工作量估计；**仅评估不实施**（W6 决策输入）；
- **收口**：`make verify-all` 七 job 全绿（前端 flake 参数惯例）；台账 W5 表 + 终审行；缺口清单终稿（含 prod 试运行缺口、连续 3 天偏差项）；合并 master 后复跑指纹不变。

## 11. 测试与门禁

- 后端：迁移 0013 全周期（upgrade→downgrade→upgrade）+ RLS 跨租户 0 行；租户 API（生命周期补端点 + members 业务规则 + quotas 留痕 + context 切换后租户作用域断言）；质量四段口径单测（构造数据断言精确值）+ 任务轨道集成（202→轮询→SUCCEEDED + 事件落库）+ 适配器 jobs 迁移回归（既有用例改 DB 断言）；reindex 集成；drills 读 JSON；越权矩阵扩 quality:read/run 与 members/quotas 角色行；
- 前端：租户 6 页/弹窗交互（MSW）；演练页/Agent 三页渲染与数据；真模式对接批 MSW 形状对齐；Bell 未读计数；
- 基线只增不破：后端 618 / 前端 302 起；契约指纹 `687b6cd7` → 新值一次冻结。

## 12. 契约变更清单（EDP-007 流程）

| 变更 | 类型 |
|---|---|
| `PATCH /tenants/{id}`、`POST /tenants/{id}/context`、`GET|POST /tenants/{id}/members`、`PATCH /tenants/{id}/members/{mid}`、`GET|PATCH /tenants/{id}/quotas` | 新增（B.14 补齐） |
| `GET /tenants/{id}/usage` | 扩展（租户内 ADMIN 轨道；响应不变） |
| `GET /admin/quality/reports`、`GET /admin/quality/coverage`、`POST /admin/quality/rechecks`、`GET /admin/quality/tasks/{id}` | 新增（B.13） |
| `POST /admin/evidence/reindex` | 新增（W3-04） |
| `GET /admin/adapters/{name}/jobs` | 新增（W4-07） |
| `GET /admin/drills` | 新增（EDP-502） |

## 13. 偏差登记（用户已批准口径）

1. **prod 试运行未启动**：M5 出口不含 prod；staging 兼任全部演练（缺口/W6 前置项）；
2. **「连续 3 天」备份验证以连续 N≥3 次任务化证据等价**：日历累计 3 天后补充归档；
3. **质量 reports 实时计算无预聚合**：date 参数接受但不回溯（W6 压测后评估物化）；
4. **异步任务执行互斥为单副本语义**：状态落库多副本安全，执行互斥不保证（Redis 评估覆盖）；
5. **演练记录静态 JSON**：不建表（演练线唯一写者，W6 运营报告复用）；
6. **quality:read 角色集宽于 B.13「JWT（ADMIN）」原文**：对齐 audit:read 只读分析面（PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST）；触发类 `quality:run` 仍限 PLATFORM_ADMIN/ADMIN。
