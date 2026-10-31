# EDP 第六周（W6：试运行与验收 M6 Go/No-Go + W5 遗留收编）

| 项 | 内容 |
|---|---|
| 日期 | 2026-09-22 |
| 状态 | 已获用户批准（对话逐项确认：范围=计划全量+W5 缺口全收编；压测=locust+dev compose+中等规模 seed；Redis=决策记录+B 轻量项实施（advisory lock），本体不引入留二期；全局搜索=真 API+结果页；E2E=CI 真栈；试运行=任务化等价（连续 N≥3 巡检周期）；编排=两波三线） |
| 上游依据 | 《EDP数据平台开发计划_一阶段.md》W6 任务（EDP-033~035、EDP-601~604）+ M6 出口条件 + §7.2 Go/No-Go 指标表；《EDP数据平台系统设计文档_V2.0.md》9.4（性能与租户防护）、11（验收指标）、7.2、13.6/13.9（错误码/交互）、L1061/L1224/L2633（全局搜索/视觉回归/E2E 口径）、附录 D；W5 缺口清单（m2-demo.md W5-03/05/06/09/11/12/13/21）；docs/redis-evaluation.md（W6 决策输入） |
| 前置 | W5 已合并 master（后端 663 / 前端 349 测试基线；契约指纹 `4b576ee5`；staging MinIO+pgbackrest S3+PITR+租户恢复+HAProxy 单写入口已实测归档） |
| 不改动 | W1~W5 冻结契约既有端点语义（新增端点/可选字段/可选参数除外；唯一例外：`GET /admin/drills` 权限收紧，W5-21 终审裁定，见 §9）；既有测试基线只增不破（drills 授权矩阵用例随裁定同步修订）；限流令牌桶与审计策略缓存的进程内实现（维持单副本语义，Redis 仅决策记录）；Mock 适配器基线不变；不引入 Redis/Chromatic 等外部服务 |

## 1. 范围与决策

本轮 = **W6 全量 + W5 遗留缺口全收编**，单分支 `feat/w6` 两波 + 三专项线：

1. **波1 后端契约批（T1~T4）**：4 新端点（search / outbox status / admin users / events 前缀参数）、health ops_metrics 补 5 字段、任务互斥 advisory lock、Minor 修复批（W5-21/09）、pg_stat_statements 供给、契约冻结（T4 闸门）；
2. **波2 前端收口批（T8~T9）**：EDP-601（500 页/errorElement/403 触发接线/搜索结果页/空态收口）+ 前端体验收编（capability 收敛/用户目录/前缀过滤/rto 加注）；
3. **专项线A 压测（T5~T7，不碰 `contracts/`）**：数据放大 + locust 引入 + 执行 + RLS 开销验证 + 慢查询治理 + Redis 决策记录 + 预聚合条件项；
4. **专项线B E2E/视觉回归（T10~T11，不碰 `contracts/`）**：Playwright 基座 + M4 闭环/多租户隔离两脚本 + CI e2e job + 视觉回归基线（组件层 storybook 截图 + 页面层 E2E 截图）；
5. **专项线C 验收线（T12~T15）**：ops-report 一键导出（§6 九指标）、试运行任务化巡检、文档归档（运维/演练/FAQ/前端交接/prod 设计/Memory 对接）、M6 收口（verify-all + 台账 + 缺口终稿 + Go/No-Go 指标表评审）。

**关键决策与理由**：
- **压测 = locust + dev compose + 中等规模 seed**：locust 入 uv dev 依赖（栈统一、场景脚本化）；dev compose 起栈轻、数据可控；目标规模 ~5k 对象 / ~50k 事件 / ~10k 证据（中等量级）；结论同时作为 Redis 决策输入；
- **Redis 决策 = 记录 + B 轻量项**：任务互斥落 `pg_try_advisory_lock`（redis-evaluation §4 建议，多副本安全）；限流/缓存按压测结论定「维持单副本 + 文档化」或「W6+ 过渡实现」；**不引入 Redis 本体**（留二期）；
- **全局搜索 = 真后端 API**：设计文档 L2633 明确 `GET /search?q=`（跨索引聚合，W6 收口）——契约新增走 EDP-007 流程；
- **E2E = CI 真栈**：多租户隔离脚本对 mock 无意义；CI 起 postgres service + api/worker + vite preview + seed-demo，PR 强制门禁（验收「CI 强制通过」）；
- **视觉回归 = playwright-screenshot 双层**：组件层（storybook-static 逐 story）+ 页面层（E2E 真栈逐路由）合计覆盖 26 设计稿关键状态（设计文档 L1224 口径）；不引 Chromatic（外部服务）；
- **试运行 = 任务化等价（W5 先例）**：连续 N≥3 个巡检周期无 P0/P1 等价「≥3 天」，偏差登记；日历 3 天后续自然累计；
- **prod 形态 = 仅设计文档**：HAProxy 双实例 + keepalived/VIP 与 prod 试运行窗口写部署设计留二期（W5-06 缺口延续）；
- **Memory 评审流转中枢接管 = EDP 侧仅对接说明**：既有 `PATCH /memories/{id}/review` 端点不变，交接文档写明中枢接管口径（EDP-014 注）。

**不在范围**：Redis 实际引入；限流 UPSERT 原子化（压测结论为需要时记 W6+ 工作项）；质量报告预聚合/物化（P95 达标即登记不做，条件项）；prod 环境实测；真实外部源系统接入（Mock 基线不变）。

## 2. Section A：波1 后端契约批（T1~T3）

### 2.1 新端点（4 个，EDP-007 流程新增）

| 端点 | 鉴权 | 要点 |
|---|---|---|
| `GET /api/v1/search?q=&limit=` | 认证用户（RLS 自然过滤） | 跨 objects/events/evidence 三表 ILIKE/前缀匹配聚合；响应 `{query, objects[], events[], evidence[], total}`；每组默认 10 条上限；匹配字段：对象 source_id/object_type/attrs 摘要、事件 event_type/data 摘要、证据 ref/kind——设计稿 21「全局搜索结果/空态」数据源（设计文档 L1061/L2633） |
| `GET /api/v1/admin/outbox/status` | `quality:read` | `{pending_count, oldest_pending_age_seconds, published_last_hour, dlq_count, last_published_at}`——event.outbox 聚合（W5-05 收口；运营报告/健康页数据源） |
| `GET /api/v1/admin/users` | 平台 ADMIN | 平台用户目录简投影 `{user_id, username, display_name}` 游标分页（W5-11 收口；邀请成员下拉真数据源；B.14 未定义，本轮补契约） |
| `GET /api/v1/events` 扩展 | 不变 | 新增可选参数 `event_type_prefix`（LIKE prefix%；与既有 `event_type` 精确匹配同传 → 422 校验拒绝）——Bell 消息中心后端前缀过滤（W5-12 收口） |

### 2.2 health ops_metrics 补 5 字段（可选字段，向后兼容）

对齐 MSW `HealthResponse.ops_metrics` 既有形状（`health/schemas.py:9` 注释兑现）：

| 字段 | 数据源 |
|---|---|
| `backup` | 备份读数派生（drills JSON 备份相关 readings / backup-verify 任务化读数：`{last_backup_at, status, source: "drills"}`；无记录 null） |
| `audit_events_7d` | audit 表 7d 计数 |
| `policy_hits_today` | 审计策略命中当日计数 |
| `adapters_success_rate` | ops.tasks 最近 20 条 adapter_sync 成功率 |
| `evidence_valid_rate` | 最近一次 checksum 抽检 stats 派生（无记录 null） |

### 2.3 任务互斥 advisory lock（Redis B 轻量项）

- quality recheck / evidence reindex / adapter sync 三类后台任务执行入口统一 `pg_try_advisory_lock(hashtext('ops.task:' || task_type))`：
  - 拿到锁 → 执行（finally 释放）；
  - 锁被占 → `409 TASK_CONFLICT`（`{code, message, current_task_hint}`）——多副本安全互斥（单副本下等价无影响，语义前向兼容）；
- 无 DDL、无迁移；集成测试：同 task_type 并发触发仅一任务执行、另一请求 409。

### 2.4 Minor 修复批（T3，一次 commit）

1. **W5-21-a**：adapter sync FAILED 时 stats 四计数置空（quality/evidence 保留已完成段语义统一——FAILED 即无最终计数）；
2. **W5-21-c**：`GET /admin/drills` 权限收紧——`quality:read` 角色集去掉 MANAGER/ANALYST（收紧至 PLATFORM_ADMIN/ADMIN；内容为基础设施元数据、无凭据，但最小权限原则收口）；越权矩阵与既有用例同步修订（唯一行为变更，见 §9）；
3. **W5-09**：内部来源写事件（quality 抽检 `quality.checksum_failed` 等）豁免 api_calls 计量——ingest 内部调用路径加 internal 标志，api_calls 与审计不受影响（仅配额计数豁免）。

### 2.5 pg_stat_statements 供给（部署侧，无迁移）

- dev compose 与 staging patroni `postgresql.parameters` 加 `shared_preload_libraries: pg_stat_statements` + `pg_stat_statements.track: all`；
- dev `pg-init` 与 staging init SQL 建扩展（超级用户侧）；`edp_migrator`/`edp_app` 不涉及——压测线消费（§3）。

## 3. Section B：压测线（T5~T7，EDP-033）

1. **数据放大（T5）**：`seed-demo --scale N`（demo CLI 加参数）：对象/事件/证据按 N 倍确定性放大（UUIDv5 幂等保重放复位）；压测目标 **~5k 对象 / ~50k 事件 / ~10k 证据**（N 按现有 dataset 基数定，plan 阶段落具体值）；
2. **locust 引入（T6）**：
   - `backend` dev 依赖组加 `locust`（uv）；`backend/scripts/loadtest/locustfile.py`；
   - 场景（读为主 + 1 写）：登录取 token → `GET /health`、`GET /objects`（组合键/分页）、`GET /events`（过滤+游标翻页）、`GET /admin/quality/reports`、`GET /admin/quality/coverage`、`GET /audit-logs`、`GET /tools/*` 订单查询、`GET /decisions/cases/{id}` 闭环详情、写场景 `POST /events/batch`（小批量）；
   - Makefile 目标 `make loadtest`（headless 阶梯 20 → 50 → 100 VU，每档 3~5min，总时长 bounded）；
   - 报告：locust `--json` + HTML 归档 `deploy/loadtest/` + 读数汇总 `docs/demo/w6-loadtest.md`；
3. **RLS 开销 <5% 验证（DB 层口径）**：API 层无 bypass 通道（鉴权边界），改 **DB 层双会话同查询计时**：`edp_app`（RLS 生效）vs `edp_migrator`（BYPASSRLS）× 主要查询模式（events 过滤翻页 / objects 组合键 / audit 过滤），各跑 N 次取 P95 差值百分比——写入压测报告专节；
4. **慢查询治理闭环（T7a）**：压测后查 `pg_stat_statements` top（mean_exec_time desc）→ >500ms 查询建索引或改查询 → 视需要迁移 `0014_ops_indexes`（tenant_id 前缀，对齐设计 9.4）→ 复测达标；
5. **Redis 决策记录（T7b）**：压测结论 + QPS 数据 → `docs/redis-evaluation.md` 追加「W6 决策」终节：任务互斥已落 advisory lock（§2.3）；限流/缓存按实测结论定「维持单副本 + 文档化」或「W6+ 过渡实现」；不引入 Redis 本体（留二期）；
6. **预聚合条件项（T7c，W5-03）**：`GET /admin/quality/reports` P95 ≥ 2s → 物化/缓存治理并复测；< 2s → 登记不做（条件项闭合）。

**验收对齐**：主要接口 P95 <2s、RLS 开销 <5%、压测报告归档——EDP-033 三出口全覆盖。

## 4. Section C：波2 前端收口（T8~T9，EDP-601 + 体验收编）

1. **500 页新增**：`ServerErrorPage`（`data-dom-id="page-500"`）+ 路由根级 `errorElement`（React Router 6 错误边界渲染）；
2. **403 触发接线**：`guards.tsx` 路由权限守卫（按路由所需角色，无权限 → 跳 `/403`；路由权限表随 §2.4 drills 收紧同步——演练页限 ADMIN+）——现状 403 路由存在但零触发点（探索确认）；
3. **搜索结果页**：`/search?q=` 三组结果（对象卡/事件行/证据行，复用既有列表组件）+ 设计稿 21 无结果空态 + `GET /search` MSW handler 与真模式接线；
4. **空态收口**：未用 `EmptyState` 的 8 页统一（Overview/Quality/Tools/Health/TenantDetail/Adapters/CaseDetail/搜索）；
5. **走查表**：13 错误码 × 触发路径 × 呈现方式全表（归 `frontend/README.md` §错误码，签收物）；
6. **体验收编（T9，W5 缺口）**：
   - Agent 三页 capability 下拉接 `GET /capabilities`（三处硬编码 `CAPABILITY_LABELS` 收敛单点；MSW + 真模式；W5-13）；
   - 邀请成员用户下拉接 `GET /admin/users`（真模式 404 占位移除；W5-11 前端侧）；
   - Bell 消息中心接 `GET /events?event_type_prefix=quality.`（`FEED_WINDOW=50` 客户端过滤降为兜底；W5-12 前端侧）；
   - 演练页 switchover `rto_seconds=0` 展示加注「healthz 零中断口径，DB 写面见 readings」（W5-21-b）。

## 5. Section D：专项线B E2E 与视觉回归（T10~T11，EDP-602/603）

1. **Playwright 基座（T10）**：`frontend/apps/web/e2e/`（`playwright.config.ts` + tests）；`@playwright/test` devDependency；选择器**全用 `data-dom-id`**（现有 967 处锚点）；
2. **CI e2e job**：独立 `.github/workflows/e2e.yml`（`frontend/**` 或 `backend/**` 变更即触发）：`postgres:16` service → alembic 迁移 → `seed-demo` → api（uvicorn）+ worker 本地起 → web `vite build` + `preview` → `playwright test`；PR 强制门禁；
3. **脚本① M4 闭环**：登录 → 总览 KPI/风险卡 → 风险抽屉 → 案例详情证据链 → **逐证据 verify=true 断言（追溯率 100% 内嵌，§7.2 指标自动化断言）** → HITL 审批 → Action 执行 → Verified → 总览闭环事件回流；
4. **脚本② 多租户隔离**：A 租户造数 → B 租户上下文 API 403/空列表断言 + 前端不渲染断言；
5. **视觉回归基线（T11，playwright-screenshot 双层）**：
   - **组件层**：独立 visual project 对 `storybook-static`（build-storybook 产物）iframe 逐 story `toHaveScreenshot`——现有 11 组件 story 全覆盖；
   - **页面层**：E2E 真栈逐路由页面截图基线（seed 确定性数据 + 动画/caret/字体禁用保稳定）；
   - 组件层 + 页面层合计覆盖 **26 设计稿关键状态**（设计文档 L1224 口径）；基线快照入库（`e2e/__screenshots__/`）；偏差 CI 失败 → `--update-snapshots` 走 PR 评审。

## 6. Section E：验收线·运营报告（T12，EDP-034）

- `backend/scripts/ops_report.py` + `make ops-report`：DB 直读（`edp_migrator` 全租户口径）+ 压测 JSON + drills JSON + E2E 结果 → 产物 `docs/demo/w6-gonogo.md`（§7.2 指标表全绿呈现）+ `deploy/ops-report/w6-ops-report.json`（版本化工件）；
- 九项指标数据源落地：

| 指标（门槛） | 实现 |
|---|---|
| 业务对象覆盖度 ≥95% | 复用 quality coverage 口径 SQL |
| 证据可追溯率（P0/P1）100% | 证据→事件→对象链路存在性 SQL + E2E 脚本①内嵌断言 |
| 重大风险召回率 ≥80%（误报 ≤20%） | 十类场景 ground truth（dataset.py 期望事件）vs 实际风险事件对账统计（seed 回放） |
| Action 闭环率 ≥90% | `action.verified` 事件数 / 生成行动总数 SQL |
| AI 越权执行 =0 | GUARD_DENIED 全量导出（JSON 工件）+ 断言无越权**成功**行 + 越权矩阵 CI 报告引用 |
| Action 审计完整率 100% | 审计行数 vs 决策/行动总数对账 SQL |
| 接口响应 <2s | 压测 JSON（P95）读取 |
| 租户隔离 100% 拒绝 | 跨租户用例集（CI 常驻）+ E2E 脚本②结果 |
| 高可用/备份恢复 RTO<5min 等 | drills JSON 读取（W5 实测记录复用） |

## 7. Section F：试运行与文档归档（T13~T15，EDP-035 + EDP-604 + M6）

1. **试运行任务化巡检（T13）**：
   - `deploy/scripts/trial-patrol.ps1`：staging 起栈后周期巡检（`/health?deep`、关键端点、outbox 积压、备份状态、worker 心跳）→ 追加 `deploy/logs/trial-run.log`；
   - `docs/demo/w6-trial-run.md`：P0~P3 缺陷分级定义 + 缺陷登记表 + 巡检读数汇总；
   - **连续 N≥3 个巡检周期无 P0/P1 → 等价收口**（W5「连续 3 天」先例口径），偏差登记；日历 3 天后续自然累计；
2. **文档归档（T14）**：
   - `docs/ops-runbook.md` 运维手册（部署/迁移/备份/监控/故障处置，复用 W5 演练素材）；
   - `docs/drill-handbook.md` 演练手册（w5-drills/staging-drill 汇编）；
   - `docs/faq.md`；
   - `frontend/README.md`（EDP-604）：组件清单、路由表、枚举字典（含 13 错误码走查表）、MSW/真模式切换、E2E 与视觉回归维护说明、交接说明；Memory 评审流转中枢接管对接小节（EDP-014：端点不变、中枢接管评审流转）；
   - `docs/prod-deploy-design.md`（仅文档，留二期）：HAProxy 双实例 + keepalived/VIP 生产形态、prod 试运行窗口建议（W5-06 缺口延续）；
   - 归档清单签收：台账 W6 表；
3. **M6 收口（T15）**：`make verify-all` 全绿（含新 e2e/visual CI job）→ 台账 W6 表 + 缺口终稿 → Go/No-Go 指标表评审（`w6-gonogo.md` 全绿）→ 合并 master 后指纹复跑不变。

## 8. 测试与门禁

- 后端：search 聚合（三组命中/空态/RLS 过滤）、outbox status、admin users、events prefix 参数（与 event_type 互斥 422）、health 5 字段派生、advisory lock 并发（同 task_type 仅一执行 + 409）、drills 权限收紧用例修订、内部计量豁免断言；越权矩阵扩 search/admin users/outbox status 行；
- 前端：500/403 路由触发、搜索页 MSW、空态收口、capability/用户目录/前缀过滤接线测试；基线只增不破（前端 349 起）；
- E2E：两脚本 CI 强制；视觉回归基线偏差走 PR 评审；
- 基线：后端 663 / 前端 349 起；契约指纹 `4b576ee5` → 新值一次冻结（T4）。

## 9. 契约变更清单（EDP-007 流程）

| 变更 | 类型 |
|---|---|
| `GET /api/v1/search?q=&limit=` | 新增（设计 L2633 收口） |
| `GET /api/v1/admin/outbox/status` | 新增（W5-05） |
| `GET /api/v1/admin/users` | 新增（W5-11） |
| `GET /api/v1/events?event_type_prefix=` | 扩展（可选参数，W5-12） |
| `GET /api/v1/health` 响应 `ops_metrics` 5 可选字段 | 扩展（向后兼容） |
| `GET /api/v1/admin/drills` 鉴权收紧（去掉 MANAGER/ANALYST） | **行为变更**（W5-21-c 终审裁定，唯一例外；用例同步修订） |

## 10. 偏差登记（用户已批准口径）

1. **试运行 ≥3 天以连续 N≥3 巡检周期等价**：任务化 + 日志归档（W5 先例；日历 3 天后续自然累计）；
2. **RLS 开销以 DB 层双会话计时为口径**：API 层无 bypass 通道（鉴权边界），DB 层同查询对比为等价证据；
3. **视觉回归「26 稿关键状态」以组件层 11 story + 页面层逐路由截图合计覆盖**：不逐稿建页面 story（工作量与收益不匹配）；
4. **预聚合/限流 UPSERT 为条件项**：压测结论达标即登记不做（W5-03/W3R-01 闭合口径）；
5. **prod 形态仅设计文档**：HAProxy 双实例/VIP 与 prod 试运行窗口留二期（W5-06 延续）；
6. **Redis 不引入**：任务互斥 advisory lock 落地，限流/缓存维持单副本语义 + 文档化（视压测结论记 W6+ 工作项）。
