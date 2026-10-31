# EDP 第三周补齐任务（W3 剩余：注册中心/Trace/Memory/MES/限流 + 前端三页）

| 项 | 内容 |
|---|---|
| 日期 | 2026-09-16 |
| 状态 | 已获用户批准（对话逐项确认：范围=W3 补齐；重索引 MSW 先行真模式降级；用量日报走 B.14 usage API 最小版；EDP-017 做 MES Mock + 产能投影） |
| 上游依据 | 《EDP数据平台开发计划_一阶段.md》W3 剩余任务（EDP-011/013/014/017/025、EDP-302/303/304）；《EDP数据平台系统设计文档_V2.0.md》3.5（租户防护）、9.3（数据质量 W5）、9.6（可观测性）、B.7/B.10/B.11/B.13/B.14、13.6.2/13.6.3（页面规格）、附录 A.7/A.9/A.11（DDL）；《2026-09-15-edp-msw-mock-data-design.md》（MSW 端点与替换时机） |
| 前置 | W3-M3 已合并（后端 394 / 前端 131 测试基线；契约 35 路径指纹 f5ee32a8；tools/seed/回流/EBMS/health/事件页已交付） |
| 不改动 | W1~W3 冻结契约既有端点语义（`GET /evidence` 仅新增可选 `q`）；既有测试基线；W4+ 模块（Action/审计页/适配器页/闭环页/质量任务 EDP-030） |

## 1. 范围与决策

本轮 = **W3 剩余任务**（补齐计划中未交付项），按用户逐项确认：

1. 后端：EDP-011 注册中心（B.7 八端点）、EDP-013 Trace（B.10 三端点）、EDP-014 Memory（B.11 三端点）、EDP-017 剩余（MES Mock + 产能投影）、EDP-025 限流配额（应用层令牌桶 + statement_timeout + 用量计数 + B.14 usage API）；
2. 前端：EDP-302 证据库页、EDP-303 数据质量页、EDP-304 系统健康页；
3. **EDP-302 重索引向导 MSW 先行**：列表/详情/verify 走真 API；重索引向导仅 MSW 模式可用，真模式按钮禁用 + 提示「W5 交付」（与 MSW spec 声明的替换时机一致）；
4. **用量日报 = B.14 `GET /tenants/{id}/usage` 最小版**（平台 ADMIN，游标分页），W5 租户页直接复用；
5. **EDP-017 = MES Mock + 产能投影**：验收原文「rd.projects/milestones 可同步」已由 plm-demo 满足，本轮补齐 mes-demo 与 `delivery.capacity`。

**不在范围**：EDP-020 Action 状态机（W4）、EDP-026 安全矩阵（W4）、EDP-030 质量任务 API（W5，故 303 页 MSW 驱动）、备份/告警后端（W5 EDP-031/032，故 304 页 MSW 先行）、`/admin/outbox/status`（B.13 未实现，304 页用 `/health` 字段）、消息中心 API（前端本地通知承接）。

## 2. Section A：EDP-011 注册中心（`modules/catalog`）

**端点（B.7 逐字段，前缀 `/api/v1`）**：

| 端点 | 鉴权 | 要点 |
|---|---|---|
| POST `/systems` | JWT `registry:write` / API Key `write:registry` | 201 `{system_id, name, status, created_at}`；同名 409 CONFLICT |
| GET `/systems?status=` | JWT `registry:read` / readonly | `{items, next_cursor}` |
| POST `/capabilities` | API Key `write:registry` / JWT `registry:write` | 201 `{capability_id, name, status, created_at}`；name 唯一冲突 409；字段：name/domain/input_schema/output_schema/risk_level/permission/endpoint/owner |
| GET `/capabilities?domain=&status=` | JWT/API Key | 列表（简投影） |
| GET `/capabilities/{capability_id}` | JWT/API Key | 含 input/output_schema；跨租户 404 |
| PUT `/capabilities/{capability_id}` | API Key `write:registry` / JWT `registry:write` | 局部更新（endpoint/input_schema/output_schema/status，RETIRED 下线）；200 返回完整对象 |
| POST `/skills` | API Key `write:registry` / JWT `registry:write` | 201 `{skill_id, capability_id, status, created_at}`；capability 不存在 → 400 |
| GET `/skills?capability_id=&status=` | JWT/API Key | 列表 |

**实现要点**：
- `platform.systems` 与 ingest 适配器水位共表：catalog 自持 ORM 映射（注释注明分工——catalog 管注册字段，ingest 管 `last_watermark`/`adapter_mode`）；capabilities/skills 为 catalog 独占 ORM；
- 事务边界/RLS/游标/错误码沿用既有模块模式（`tenant_scoped` + `make_require_access` 双轨）；
- 契约形状对齐设计 B.7 示例；MSW 无此组 handler（W5 EDP-503 页面用），无需前端本轮对接。

## 3. Section B：EDP-013 Trace（`modules/traces`）

| 端点 | 鉴权 | 要点 |
|---|---|---|
| POST `/traces` | API Key `write:trace`（仅 SERVICE） | B.10 请求体（trace_id 客户端提供、tool_calls[] 随行）；新 trace → 201 `{trace_id, status, created_at}`；**同 trace_id 重发 → 200 幂等返回既有**（Agent 重试安全，不重复写 tool_calls） |
| GET `/traces?agent_id=&task_id=&capability_id=&since=&limit=` | JWT `trace:read` / readonly | 游标分页（started_at DESC, trace_id DESC），简投影 |
| GET `/traces/{trace_id}` | 同上 | 完整轨迹含 `tool_calls[]`（seq 升序）；跨租户 404 |

**实现要点**：
- ORM：`trace.traces` + `trace.tool_calls`（A.9 全列；`call_id=uuid4`、`called_at` 请求值或 now）；
- `capability_id` 存在性校验（不存在 → 400）；`evidence_refs` UUID[] 直存；
- HUMAN 无写权限码（B.10 写仅 API Key），HUMAN 写 → 403 FORBIDDEN。

## 4. Section C：EDP-014 Memory（`modules/memories`）

| 端点 | 鉴权 | 要点 |
|---|---|---|
| POST `/memories` | API Key `write:memory` | 201 `{memory_id, status: "CANDIDATE", created_at}`；capability_id 不存在 → 400 |
| GET `/memories?status=&capability_id=` | JWT `memory:read` / readonly | 游标分页（created_at DESC） |
| PATCH `/memories/{memory_id}/review` | **Human-Only**：`kind != HUMAN` → 403 `GUARD_POLICY_DENIED` + 审计；HUMAN 需 `memory:review` | 请求 `{status: APPROVED|REJECTED, comment?}`；写 `reviewed_by/reviewed_at/review_comment`；已评审再评 → 409 |

## 5. Section D：EDP-017 剩余（MES Mock + 产能投影）

- `edp_adapters/mes_mock.py`：`MesMockAdapter`（name=`mes-demo`，source_system=`mes`），产能记录 `CAPACITY`（payload：`product_line/period/capacity_qty`；场景 7「产能紧张」：`L1 / 2026-W40 / 1200`，另补 2 条正常产线）；
- 数据集：`demo_dataset.py` 增 CAPACITY 段（anchor 相对偏移）；`demo_plm`/`demo_erp` 模式复制到 `demo_mes`；
- 投影：`projections/service.py` 增 `_project_capacity` → `delivery.capacity`（id=uuid5(object_id,"cap")、product_line/period/capacity_qty/snapshot_at=occurred_at；按 (tenant, product_line, period, snapshot_at) 唯一索引 upsert）；
- 注册第 4 适配器 `mes-demo`（adapters_admin 清单 4 行）；seed 快照段归并集合纳入 mes；
- 验收：`POST /admin/adapters/mes-demo/sync` → `delivery.capacity` 行可查 + 对账计数齐等。

## 6. Section E：EDP-025 限流配额（应用层）

**落点**：`tenantmgmt.dependencies.tenant_scoped`（全部租户域请求单点；顺序：认证 → 租户状态 → bind_tenant → **限流** → **statement_timeout** → **用量计数**）。

1. **令牌桶**（进程内 per-tenant，惰性补充）：capacity=`tenant_quotas.api_rate_limit`（默认 100），refill=limit/60 每秒；取不到令牌 → 429 `RATE_LIMITED` + `Retry-After: {秒}` 头 + 审计 `RATE_LIMITED` + `tenant_usage_daily.throttled_429 += 1`——**429 路径的审计与计数经独立会话提交**（请求事务将回滚，复用 tools 拒绝审计的独立会话模式）；水位达 80% 首达 → 审计告警（每窗口一次，同独立会话）；
2. **statement_timeout**：`SET LOCAL statement_timeout = {query_timeout_ms}ms`（事务级，随请求结束复位）；
3. **用量计数**：`api_calls` 每请求 upsert（**同请求事务**——请求失败则不计入，语义为「受理调用数」，docstring 留痕；演示量级，W6 性能评估）；
4. **批量限额**：`events/batch` 事件数 > `batch_max_events` → 400 VALIDATION_ERROR（超配额提示）；
5. **网关层**：deploy nginx 补全局 `limit_req` 文档片段（租户维度需鉴权后信息，归应用层——设计 3.5「网关 + 应用双层」的应用侧实现，网关侧全局限流为部署配置）。

**B.14 usage API**：`GET /api/v1/tenants/{tenant_id}/usage?since=&until=`（平台 ADMIN；游标分页）→ `items[{usage_date, api_calls, events_in, events_duplicated, storage_gb, throttled_429}]`（`events_duplicated` 为本轮超集字段，B.14 未列）；`next_cursor`。

**幂等边界**：限流/用量不作用于非租户域端点（`/healthz`、`/auth/*`、平台租户管理路由）；进程内桶为单副本语义（多副本 = limit×副本，网关层兜底），记入缺口清单。

## 7. Section F：前端三页

### 7.1 EDP-302 证据库 `/admin/evidence`（`features/evidence`）

- **KPI 带**：证据数量（真 `/health.ops_metrics.evidence_count`）/ 对象覆盖率 / 校验和有效 / 原文访问 24H——后三者无真源 → 「—」降级（字段级），MSW 模式全量；
- **双栏 1.2fr | 0.8fr**：左证据列表（卡内搜索 → `GET /evidence?q=` 新参数，匹配 `source_record_id`/`source_system` ILIKE）+ 页头操作（完整性抽检 → toast 占位；重建索引 → 向导）；右证据链图（选中证据 → 其 links 链式节点 + 同 object 证据节点；Derived 节点 info 色）+ 底部「链上校验」区（「N 份证据校验和均有效，依赖关系完整」按当前链计算）；
- **verify 联动**：点击校验 → `GET /evidence/{id}/verify` → 状态 pill 即时切换（VALID/INVALID）；状态来源 = 本会话校验结果，未校验 → 中性「未校验」pill（列表无状态字段，记偏差）；
- **重索引三步向导**：① 范围（对象集合多选 + 日期范围）→ ② 校验规则 radio 卡 → ③ 执行确认（预估条数/耗时）→ `POST /admin/evidence/reindex`（MSW）；真模式禁用 + tooltip「重索引任务 W5 交付」；
- 筛选 chips（关键词/来源/状态）+ 空态三件套（含建议替代关键词）+ `data-dom-id` 锚点。

### 7.2 EDP-303 数据质量 `/admin/quality`（`features/quality`，MSW 驱动）

- KPI 4 卡（综合质量/时效性 SLA/完整性/待处理异常含高优先角标）← MSW `GET /admin/quality/reports` 的 `kpi` 扩展字段；
- 左栏维度评分（5 域进度条，<95 warning 色）；右栏异常卡（优先级 pill + 对象短 ID + 详情 + 处理按钮 → 占位）+ 合并提示；
- 重校验弹窗（2×2 复选卡默认全选 + 范围 radio + info 条）→ `POST /admin/quality/rechecks`（MSW）→ 成功通知（**前端本地 notification**，无消息中心 API）+ 列表刷新；
- 任务日志抽屉（头部 TASK-YYYYMMDD-#### + 运行中 pill；元信息；日志时间线 INFO/WARN/ERROR；下载日志占位）→ `GET /admin/quality/tasks/{id}` 轮询（MSW）；
- 真模式：quality API 未实现（W5 EDP-030）→ 面板级降级「—」，重校验禁用提示。

### 7.3 EDP-304 系统健康 `/admin/systems`（`features/health`，MSW 先行）

- 四卡：HA（真 `/health?deep=true` 的 `db_ha`：role/复制延迟/副本数）、备份（MSW `backup` 扩展 → 真模式「—」）、Outbox 积压（真 `outbox_pending` + `ops_metrics.dlq`）、告警渠道配置（静态卡）；
- 演练入口 → `/admin/drills` 占位链接；10s 深层轮询（`refetchInterval: 10_000`，`?deep=true`）；`VITE_USE_MSW` 双模式；`data-dom-id` 锚点。

## 8. 迁移 0011 清单

1. 权限码：`trace:read`（PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST）、`memory:read`（同）、`memory:review`（PLATFORM_ADMIN/ADMIN/MANAGER）；
2. dev API Key scopes 追加 `write:trace`、`write:memory`（同 0010 的哈希匹配与幂等守卫）；
3. 无新表/列（trace/memory/capacity 表 0004 已建；`tenant_quotas`/`tenant_usage_daily` 字段齐备）。

## 9. 契约变更清单（EDP-007 流程）

- 新增路径：`/systems`、`/capabilities`（+`/{id}`）、`/skills`、`/traces`（+`/{id}`）、`/memories`（+`/{id}/review`）、`/tenants/{id}/usage`（共 15 路径）；
- 修改：`GET /evidence` 增可选 `q`；
- 收口：导出 + sha256 + api-sdk regen + `make contract-gate` 绿；偏差清单追加：证据状态 pill 语义（本会话校验）、重索引 MSW-only、限流单副本语义、`events_duplicated` 超集字段。

## 10. 验收映射（各任务验收标准）

| 任务 | 载体 |
|---|---|
| EDP-011 | 集成测试：注册 `Delivery.OrderRisk`（201）→ GET 列表/详情可查 → PUT 改 endpoint → 重名 409 |
| EDP-013 | 集成测试：POST 一条 trace + N tool_calls（201）→ GET 详情含 N 条 seq 升序 → 重发 200 幂等 |
| EDP-014 | 集成测试：候选创建（201 CANDIDATE）→ capability 过滤 → SERVICE 评审 403 GUARD_POLICY_DENIED + 审计 → HUMAN 评审 200 |
| EDP-017 | 集成测试：mes-demo sync → `delivery.capacity` 行 + 对账齐等 |
| EDP-025 | 集成测试：超限 429 + `Retry-After` + `throttled_429` 计数；usage API 返回日报（since/until 过滤）；statement_timeout 生效 |
| EDP-302 | 前端 Vitest（KPI/双栏/verify 联动/链计数/向导三步/空态）+ 真 API 冒烟（verify 切换） |
| EDP-303 | 前端 Vitest（KPI/维度/异常卡/重校验通知/日志抽屉轮询） |
| EDP-304 | 前端 Vitest（四卡/10s 轮询/降级）+ 真 API 冒烟（db_ha） |
| 全量 | `make verify-all` 全绿（migrate-check 按 T20 容器等价法） |

## 11. 工程约定与分波

- 分支 `feat/w3-remaining`；后端新模块沿六文件模式；迁移集中于 `0011`；
- 波 1（后端）：catalog → traces → memories → mes/capacity → 限流/usage → 契约导出与 SDK；
- 波 2（前端）：EDP-302 → EDP-303 → EDP-304（MSW 先行 + 真 API 冒烟）；
- 波 3（收口）：`docs/demo/m3-demo.md` 补段（trace/memory/限流/usage）或新建 `w3-remaining-demo.md`、verify-all、台账与缺口清单更新。
