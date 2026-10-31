# EDP 第三周补齐任务（W3 剩余）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 W3 剩余：注册中心（B.7）、Trace（B.10）、Memory（B.11）、MES Mock + 产能投影（EDP-017 剩余）、租户限流配额（EDP-025）+ B.14 usage API，并交付前端证据库/数据质量/系统健康三页。

**Architecture:** 后端沿用六文件模块模式（catalog/traces/memories 三个新模块）；限流嵌入 `tenantmgmt.dependencies.tenant_scoped` 单点（进程内令牌桶 + statement_timeout + 用量计数）；mes-demo 走既有演示适配器/数据集/投影链路；前端三页 feature-sliced，302 真 API + MSW 重索引降级，303/304 MSW 先行。

**Tech Stack:** FastAPI + SQLAlchemy 2 async + Alembic（PG16 RLS）；React 19 + TanStack Query v5 + Tailwind v4 + MSW 2.15；vitest / pytest + testcontainers。

**Spec:** `docs/superpowers/specs/2026-09-16-edp-w3-remaining-design.md`（已批准，commit 53720ee）

## Global Constraints

- 分支 `feat/w3-remaining`（已建）；每任务一 commit，消息 `feat(w3r): ...` / `test(w3r): ...` / `chore(w3r): ...`
- 后端 lint：`cd backend && uv run ruff check . && uv run lint-imports`（modules 仅可 import 其他模块的 service；core 禁 import modules）
- 前端校验：`cd frontend && pnpm -r test && pnpm -r lint && pnpm --filter web build`
- 全量门禁：`make verify-all`（合并前必须绿；migrate-check 对填充 dev 库按 T20 一次性容器等价法）
- 契约冻结（EDP-007）：T8 统一导出契约 + 重算 sha256 + api-sdk regen；此前任务不改 `contracts/`
- 测试基线：后端 394 / 前端 249（131 web + 96 shared + 22 api-sdk）——只增不破
- 视觉基线：`原型设计/pages/证据库.html`、`数据质量.html`、`任务日志 - 抽屉.html`、`重新校验 - 弹窗.html`、`证据重新索引 - 执行流程.html`、`搜索无结果 - 空态.html`（系统健康无设计稿，按 13.6.3 描述）；文案逐字；`data-dom-id` 锚点
- 环境：Windows PowerShell；uv 在 `backend\.venv\Scripts\`（不在全局 PATH）；make 需 `$env:PATH` 前缀；Docker 已运行
- 工作区存在与本轮无关的既有未提交改动（`EDP数据平台开发计划_一阶段.md`、`EDP数据平台系统设计文档_V2.0.md`、`docs/superpowers/specs/2026-09-14-edp-w1-design.md`、`frontend/apps/web/src/shell/Sidebar.tsx`、`frontend/packages/shared/src/permissions/*`、`.idea/`）——**禁止提交/修改**；只 `git add` 明确列出的任务文件

---

# 波 1：后端（T1~T8）

## T1 — 迁移 0011（权限码 + Key scopes）

**Files:**
- `backend/migrations/versions/platform/0011_w3_remaining.py`（新建）
- `backend/tests/integration/test_w3r_migration.py`（新建）

**实现**（风格同 0010：`revision="0011_w3_remaining"`、`down_revision="0010_w3_baseline"`、`_exists` 幂等守卫、`uuid5(NIL, f"edp-perm-{code}")`）：
1. 权限码与角色矩阵：
   - `trace:read`（trace, read）→ PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST
   - `memory:read`（memory, read）→ 同上
   - `memory:review`（memory, review）→ PLATFORM_ADMIN/ADMIN/MANAGER
2. dev API Key（`edp-dev-agent-hub-key`，哈希同 0010）scopes 追加 `write:trace`、`write:memory`（数组去重守卫）。

**downgrade**：逆序（scope 剔除 → role_permissions + permissions 删除）。**测试**：三权限码存在且角色矩阵精确；dev Key scopes 含两新 scope 且原 scopes 保留；`test_w3r_migration.py` 参考 `test_w3_migration.py` 写法。

**Verify:** `& "backend\.venv\Scripts\uv.exe" run alembic upgrade head`（workdir=backend）+ `& "backend\.venv\Scripts\python.exe" -m pytest tests/integration/test_w3r_migration.py -q`
**Commit:** `feat(w3r): 0011 迁移——trace/memory 权限码与 Key scopes`

## T2 — 注册中心模块（EDP-011，`modules/catalog`）

**Files:**
- `backend/apps/api/edp_api/modules/catalog/__init__.py` / `models.py` / `schemas.py` / `service.py` / `router.py` / `dependencies.py`（新建）
- `backend/apps/api/edp_api/main.py`（挂 router）
- `backend/tests/integration/test_catalog.py`（新建）

**实现**（B.7 逐字段；DDL 见 `0001_platform_baseline.py`：systems 含 `type/endpoint/adapter_mode/auth_config/status(ACTIVE|DISABLED)`；capabilities 含 `name/domain/input_schema/output_schema/risk_level(L0~L3)/permission(HUMAN_ONLY|READ_ONLY|AUTO_ALLOWED)/endpoint/owner/status(DRAFT|ACTIVE|RETIRED)`；skills 含 `capability_id/prompt/model_version/status`）：
- `models.py`：`System`/`Capability`/`Skill` ORM；**System 注释**：platform.systems 与 ingest 水位共表——catalog 管注册字段（type/endpoint/auth_config/status），ingest 管 `last_watermark`/`adapter_mode`；
- 8 端点（spec §2 表）；鉴权 `make_require_access("registry", "read"/"write")` 双轨；读列表游标分页（created_at DESC, id DESC）；
- 冲突：`uq_systems_name`/`uq_capability_name` 冲突 → 409 CONFLICT（IntegrityError 捕获）；skills 的 capability 不存在 → 400 VALIDATION_ERROR；
- PUT capabilities 局部更新（仅传入字段覆盖：endpoint/input_schema/output_schema/status；RETIRED 可下线）→ 200 完整对象。

**测试**（`test_catalog.py`）：注册 `Delivery.OrderRisk`（201）→ 列表/详情可查（含 schema）→ PUT endpoint 生效 → 重名 409；systems 同名 409/查询；skills 创建 + capability 过滤 + capability 不存在 400；JWT/API Key 双轨 403/200；跨租户 404。

**Verify:** `& "backend\.venv\Scripts\python.exe" -m pytest tests/integration/test_catalog.py -q`（workdir=backend）+ ruff + lint-imports
**Commit:** `feat(w3r): 注册中心 API——systems/capabilities/skills（EDP-011）`

## T3 — Trace 模块（EDP-013，`modules/traces`）

**Files:**
- `backend/apps/api/edp_api/modules/traces/__init__.py` / `models.py` / `schemas.py` / `service.py` / `router.py` / `dependencies.py`（新建）
- `backend/apps/api/edp_api/main.py`（挂 router）
- `backend/tests/integration/test_traces.py`（新建）

**实现**（B.10；DDL `A.9`：traces 全列 + `evidence_refs UUID[]`；tool_calls `call_id/seq/tool_name/input/output/status_code/error/latency_ms/called_at`）：
- `POST /traces`（API Key `write:trace`，HUMAN 403）：请求 `{trace_id, agent_id, task_id?, capability_id?, started_at, finished_at?, status, input_context?, output_structured?, token_usage?, evidence_refs?, tool_calls[]}`；新 trace → 201 `{trace_id, status, created_at}`；**同 trace_id 重发 → 200 幂等返回既有 `{trace_id, status, created_at}`，不重写 tool_calls**；capability_id 不存在 → 400；
- `GET /traces?agent_id=&task_id=&capability_id=&since=&limit=`（JWT `trace:read` / readonly）：游标（started_at DESC, trace_id DESC）简投影；
- `GET /traces/{trace_id}`：含 `tool_calls[]`（seq 升序）；跨租户 404；
- tool_calls 写入：`call_id=uuid4()`、`called_at` 取请求值（缺省 now）；同请求内批量 insert。

**测试**：一条 trace + 3 tool_calls（201）→ 详情 3 条 seq 升序/字段齐 → 重发 200 且 tool_calls 仍 3 条 → 列表过滤 → HUMAN POST 403 → 跨租户 404。

**Verify:** `& "backend\.venv\Scripts\python.exe" -m pytest tests/integration/test_traces.py -q`
**Commit:** `feat(w3r): Trace API——写入/查询含 tool_calls（EDP-013）`

## T4 — Memory 模块（EDP-014，`modules/memories`）

**Files:**
- `backend/apps/api/edp_api/modules/memories/__init__.py` / `models.py` / `schemas.py` / `service.py` / `router.py` / `dependencies.py`（新建）
- `backend/apps/api/edp_api/main.py`（挂 router）
- `backend/tests/integration/test_memories.py`（新建）

**实现**（B.11；DDL `A.7`：memory_id/capability_id/source_type/source_id/content/status(CANDIDATE|APPROVED|REJECTED)/reviewed_by/reviewed_at/review_comment）：
- `POST /memories`（API Key `write:memory`）：201 `{memory_id, status:"CANDIDATE", created_at}`；capability_id 不存在 → 400；
- `GET /memories?status=&capability_id=`（JWT `memory:read` / readonly）：游标（created_at DESC, memory_id DESC）；
- `PATCH /memories/{memory_id}/review`（**Human-Only**）：非 HUMAN → 独立会话审计 `GUARD_DENIED` + 403 `GUARD_POLICY_DENIED`（复用 `decisions/service.py` 的 `record_guard_denied` 模式，模块内自实现同构 helper）；HUMAN 需 `memory:review`；请求 `{status: APPROVED|REJECTED, comment?}` → 写 reviewed_by/at/comment → 200；已评审（status != CANDIDATE）→ 409；跨租户 404。

**测试**：候选创建 + capability 过滤；SERVICE 评审 403 + 审计行；HUMAN 评审 200（reviewed_by/at）；重复评审 409；capability 不存在 400。

**Verify:** `& "backend\.venv\Scripts\python.exe" -m pytest tests/integration/test_memories.py -q`
**Commit:** `feat(w3r): Memory 候选 API + Human-Only 评审（EDP-014）`

## T5 — MES Mock + 产能投影（EDP-017 剩余）

**Files:**
- `backend/packages/adapters/edp_adapters/mes_mock.py`（新建）
- `backend/packages/adapters/edp_adapters/demo_dataset.py`（追加 CAPACITY 段）
- `backend/apps/api/edp_api/modules/projections/{models,service}.py`（增 Capacity ORM + `_project_capacity`）
- `backend/apps/api/edp_api/modules/adapters_admin/service.py`（注册 mes-demo）
- `backend/apps/api/edp_api/modules/demo/service.py`（归并集合纳入 mes 适配器）
- `backend/tests/unit/test_mes_mock.py` + `backend/tests/integration/test_capacity_projection.py`（新建）

**实现**：
- `MesMockAdapter`（name=`mes-demo`，source_system=`mes`）：`build_records(anchor)` 从 `demo_dataset.CAPACITY_RECORDS` 构造（`object_type="CAPACITY"`，payload `{product_line, period, capacity_qty, owner_domain:"delivery"}`）；场景 7 数据：`L1 / 2026-W40 / 1200`（紧张），另补 `L2 / 2026-W40 / 3600`、`L1 / 2026-W41 / 2400`；确定性偏移（-8d/-6d/-4d）；
- 投影：`Capacity` ORM（`delivery.capacity`：id/product_line/period/capacity_qty NUMERIC(18,4)/snapshot_at + 审计列）；`_project_capacity`（id=uuid5(object_id,"cap")；按 (tenant, product_line, period, snapshot_at) 唯一索引 upsert）；
- `demo/service.merged_snapshot_records` 纳入 mes 适配器（全局序：erp → mes → plm，依赖无关）；
- `adapters_admin` 注册第 4 适配器（清单 erp/erp-demo/mes-demo/plm-demo 四行）；`test_adapters_api` 清单断言同步。

**测试**：单测 mes 适配器确定性/过滤；集成：seed 后 `delivery.capacity` 3 行且 product_line/period/qty 正确；`POST /admin/adapters/mes-demo/sync` 202 → duplicated==fetched。

**Verify:** `& "backend\.venv\Scripts\python.exe" -m pytest tests/unit/test_mes_mock.py tests/integration/test_capacity_projection.py tests/integration/test_adapters_api.py -q`
**Commit:** `feat(w3r): MES Mock 适配器 + 产能投影（EDP-017 剩余）`

## T6 — 租户限流配额（EDP-025）

**Files:**
- `backend/apps/api/edp_api/modules/tenantmgmt/ratelimit.py`（新建：令牌桶 + 拒绝审计/计数）
- `backend/apps/api/edp_api/modules/tenantmgmt/service.py`（`get_quota` + `bump_usage_daily` 扩展 api_calls/throttled_429）
- `backend/apps/api/edp_api/modules/tenantmgmt/dependencies.py`（tenant_scoped 扩展三段）
- `backend/apps/api/edp_api/core/errors.py`（429 handler 支持 `Retry-After` 头）
- `backend/apps/api/edp_api/modules/events/service.py`（batch_max_events 校验）
- `backend/tests/unit/test_ratelimit.py` + `backend/tests/integration/test_ratelimit.py`（新建）

**实现**：
- `ratelimit.py`：
  ```python
  @dataclass
  class _Bucket:
      tokens: float; last: float; warned: bool = False

  _buckets: dict[UUID, _Bucket] = {}

  def check_rate_limit(tenant_id, limit_per_min: int, *, now: float | None = None) -> int:
      """取令牌；成功返回 0，失败返回 Retry-After 秒数（进程内 per-tenant 桶）。"""
      # refill = limit/60 每秒；cap = limit；首次触碰桶=满
      # tokens >= 1 → tokens -= 1, 0；否则 retry_after = ceil((1 - tokens) / rate)
      # tokens/cap <= 0.2 且 not warned → warned=True 返回 0（调用方补 80% 告警审计）；refill 满时 warned=False
  ```
  注入时钟便于单测；模块级 dict 单副本语义（docstring 注明多副本 = limit×副本，网关层兜底）。
- `service.py`：`get_quota(sess, tenant_id) -> TenantQuota`（缺省行 → 默认值 100/1000/5000）；`bump_usage_daily` 增 `api_calls=0`/`throttled_429=0` 参数（表达式累加）；
- `dependencies.tenant_scoped` 在 `bind_tenant` 后：
  1. `quota = await tenantmgmt_service.get_quota(sess, principal.tenant_id)`；`retry = check_rate_limit(...)`；`retry > 0` → 独立会话写 `RATE_LIMITED` 审计 + `bump_usage_daily(throttled_429=1)` → `raise EdpError.rate_limited(..., extra={"retry_after": retry})`；
  2. `SET LOCAL statement_timeout = {int(quota.query_timeout_ms)}`（`text(f"SET LOCAL statement_timeout = {int(...)}")`，SET 不支持绑定参数，整型内插安全）；
  3. `bump_usage_daily(api_calls=1)`（同请求事务；失败请求不计，语义=受理调用数）；
  4. 80% 告警：桶返回警示标记时经独立会话写审计 `RATE_LIMIT_WARNING`（每窗口一次）。
- `core/errors.py`：`EdpError` handler 中 `retry_after = exc.extra.pop("retry_after", None)` → 响应头 `Retry-After`（保持 body 干净）；
- `events/service.ingest_batch`：`len(events) > quota.batch_max_events` → `EdpError.validation_error(f"批量事件数超过租户上限 {n}")`。
- **注意**：tenant_scoped 也被平台租户管理路由/health 使用——按 spec §6 边界，限流只作用于租户域（tenant_scoped 本身即租户域；`/auth/*`、`/healthz` 不经过，天然不受限）。

**测试**：单测（假时钟：满桶消耗/回填/Retry-After 计算/80% 标记/回满重置）；集成：把 default 租户 `api_rate_limit` 调 3 → 前 3 次 200、第 4 次 429 + `Retry-After` 头 + 审计行 + `throttled_429=1`；usage 的 `api_calls` 随请求累加；`statement_timeout` 探针路由读到设定值；batch 超 `batch_max_events` → 400。

**Verify:** `& "backend\.venv\Scripts\python.exe" -m pytest tests/unit/test_ratelimit.py tests/integration/test_ratelimit.py -q`
**Commit:** `feat(w3r): 租户限流配额——令牌桶/statement_timeout/用量（EDP-025）`

## T7 — 使用量日报 API（B.14 最小版）

**Files:**
- `backend/apps/api/edp_api/modules/tenantmgmt/platform_router.py`（追加 GET usage）
- `backend/apps/api/edp_api/modules/tenantmgmt/schemas.py`（`UsageItem`/`UsagePage`）
- `backend/apps/api/edp_api/modules/tenantmgmt/service.py`（`query_usage`）
- `backend/tests/integration/test_usage_api.py`（新建）

**实现**：`GET /api/v1/tenants/{tenant_id}/usage?since=&until=&limit=&cursor=`（`require_platform_admin`）→ `{items: [{usage_date, api_calls, events_in, events_duplicated, storage_gb, throttled_429}], next_cursor}`；`usage_date DESC` 游标（`{d,i}`，i=行 id）；`since`/`until` 按日期闭区间；租户不存在 404。

**测试**：造 usage 行（直接 upsert 或经请求）→ 查询过滤/排序/游标；非平台 ADMIN 403；租户不存在 404。

**Verify:** `& "backend\.venv\Scripts\python.exe" -m pytest tests/integration/test_usage_api.py -q`
**Commit:** `feat(w3r): 使用量日报 API（B.14 最小版）`

## T8 — 证据搜索参数 + 契约收口（波 1 收口）

**Files:**
- `backend/apps/api/edp_api/modules/evidence/{service,router}.py`（`q` 参数）
- `backend/tests/integration/test_evidence.py`（追加）
- `contracts/openapi.json` / `contracts/openapi.sha256`（重导出）
- `frontend/packages/api-sdk/src/generated/{schema.d.ts,fingerprint.json}`（regen）
- `docs/demo/m2-demo.md`（缺口清单追加 W3R 条目）

**实现**：
1. `GET /evidence` 增可选 `q`：`ILIKE` 匹配 `source_record_id` 或 `source_system`（`%`/`_` 转义），与既有 ref_type/ref_id/object_id 过滤可组合；测试覆盖命中/空/组合；
2. 契约导出（`make contract-export`，PATH 前缀 venv）：确认新增 15 路径（B.7×8、B.10×3、B.11×3、usage×1）与 `/evidence?q`；sha256 更新；
3. api-sdk regen（方式同 T14，W3-M3）+ `make contract-gate` 绿；
4. 缺口清单追加：证据状态 pill=本会话校验语义、重索引 MSW-only（真模式禁用）、限流单副本语义、`events_duplicated` 超集字段、`/admin/outbox/status` 未实现（304 用 /health）。

**Verify:** `make contract-export && make contract-gate && cd frontend && pnpm --filter @edp/api-sdk test`
**Commit:** `chore(w3r): 契约冻结更新（catalog/traces/memories/usage + evidence q）+ SDK regen`

---

# 波 2：前端三页（T9~T11）

## T9 — 证据库页（EDP-302，`features/evidence`）

**Files:**
- `frontend/apps/web/src/features/evidence/{api.ts,hooks.ts,EvidencePage.tsx,EvidenceList.tsx,ChainPanel.tsx,VerifyPill.tsx,ReindexWizard.tsx}`（新建）
- `frontend/apps/web/src/app/router.tsx`（`admin/evidence` 指向 `EvidencePage`）
- `frontend/apps/web/src/features/evidence/EvidencePage.test.tsx` / `ReindexWizard.test.tsx`（新建）

**实现**（视觉基线 `原型设计/pages/证据库.html` + `证据重新索引 - 执行流程.html` + `搜索无结果 - 空态.html`；设计 13.6.2 证据库节）：
- KPI 带 4 卡：证据数量（`/health.ops_metrics.evidence_count` 真值）、对象覆盖率/校验和有效/原文访问 24H（无真源 → 缺失「—」，MSW 全量）；
- 左栏证据列表：卡内搜索（`q` 参数，300ms 防抖）→ `GET /evidence?q=`；证据卡（类型 pill Primary/Derived 按 `source_system` 或 links 判定；状态 pill ← 本会话 verify 结果，未校验中性；短 ID/来源/业务键/描述/时间/哈希缩写/部门——缺失字段「—」）；游标分页；
- 右栏证据链图：选中证据 → `GET /evidence/{id}` 的 links 链式节点 + `GET /evidence?object_id=` 同对象证据节点（垂直链，Derived info 色）+ 底部链上校验区（「N 份证据校验和均有效」按本会话校验计数）；
- verify 联动：`GET /evidence/{id}/verify` → 状态 pill 即时切换 VALID/INVALID + toast；
- 重索引向导（三步 stepper 720px：范围多选+日期 → 规则 radio 卡 → 确认预估）：`VITE_USE_MSW` 时提交 `POST /admin/evidence/reindex` → 202 展示 task；**真模式按钮禁用 + tooltip「重索引任务 W5 交付」**；
- 筛选 chips（关键词/来源/状态）+ 空态三件套 + 建议替代关键词；`data-dom-id` 锚点。

**测试**（MSW server）：KPI 四卡、列表搜索过滤、verify 点击后 pill 切换（真 API handler）、链图节点数/校验区计数、向导三步/202、真模式禁用态（`VITE_USE_MSW=0` 分支 mock）、空态。

**Verify:** `pnpm --filter web test -- --maxWorkers=2` + `pnpm --filter web lint` + `pnpm --filter web build`
**Commit:** `feat(w3r): 证据库页——列表/链图/verify 联动/重索引向导（EDP-302）`

## T10 — 数据质量页（EDP-303，`features/quality`，MSW 驱动）

**Files:**
- `frontend/apps/web/src/features/quality/{api.ts,hooks.ts,QualityPage.tsx,KpiBand.tsx,DimensionScores.tsx,ExceptionCards.tsx,RecheckModal.tsx,TaskLogDrawer.tsx}`（新建）
- `frontend/apps/web/src/app/router.tsx`（`admin/quality` 指向 `QualityPage`）
- `frontend/apps/web/src/features/quality/QualityPage.test.tsx`（新建）

**实现**（视觉基线 `数据质量.html` + `重新校验 - 弹窗.html` + `任务日志 - 抽屉.html`；设计 13.6.3 数据质量节）：
- KPI 4 卡 ← `GET /admin/quality/reports?date=` 的 `kpi` 扩展字段（综合质量 97.8%/时效性 SLA/完整性/待处理异常含高优先角标）；
- 左维度评分（5 域进度条，<95 warning）；右异常卡（优先级 pill + 对象短 ID + 详情 + 处理按钮 → toast 占位）+ 合并提示；
- 重校验弹窗（2×2 复选卡默认全选 + 范围 radio + info 条）→ `POST /admin/quality/rechecks`（MSW）→ 202 → **前端本地 notification「校验任务已提交，完成后将通知」** + 列表刷新；
- 任务日志抽屉：头部 TASK-YYYYMMDD-#### + 运行中 pill、元信息、日志时间线（INFO/WARN/ERROR）、下载日志占位 → `GET /admin/quality/tasks/{id}` 轮询（1s）；
- 真模式：quality API 未实现（W5）→ 面板级降级「—」+ 重校验禁用提示；
- `data-dom-id` 锚点。

**测试**（MSW）：KPI 四卡值、维度条 warning 色、异常卡数量/合并提示、重校验弹窗提交 → notification + 刷新、抽屉日志时间线/轮询、真模式降级。

**Verify:** 同 T9
**Commit:** `feat(w3r): 数据质量页——维度/异常/重校验/任务日志（EDP-303）`

## T11 — 系统健康页（EDP-304，`features/health`，MSW 先行）

**Files:**
- `frontend/apps/web/src/features/health/{api.ts,hooks.ts,HealthPage.tsx,HaCard.tsx,BackupCard.tsx,OutboxCard.tsx,AlertChannelsCard.tsx}`（新建）
- `frontend/apps/web/src/app/router.tsx`（`admin/systems` 指向 `HealthPage`）
- `frontend/apps/web/src/features/health/HealthPage.test.tsx`（新建）

**实现**（设计 13.6.3 系统健康节；无设计稿）：
- HA 卡：`GET /api/v1/health?deep=true` 的 `db_ha`（role 主/从 + 复制延迟 + 副本数）；真模式经 JWT（MANAGER 有 audit:read）；
- 备份卡：MSW `backup` 扩展（最近全量/WAL 归档/恢复验证）；真模式缺字段 → 「—」；
- Outbox 卡：真 `outbox_pending` + `ops_metrics.dlq`（积压/死信）；
- 告警渠道配置卡：静态展示（站内+邮件等，后续 EDP-032 接后端）；
- 演练入口 → `/admin/drills` 链接；**10s 深层轮询**（`refetchInterval: 10_000`）；`VITE_USE_MSW` 双模式；`data-dom-id` 锚点。

**测试**（MSW）：四卡渲染、10s 轮询（fake timers 断言二次请求）、真模式缺 backup 字段「—」、演练链接。

**Verify:** 同 T9
**Commit:** `feat(w3r): 系统健康页——HA/备份/Outbox/告警四卡（EDP-304）`

---

# 波 3：收口（T12）

## T12 — 演示脚本补段 + 验收用例 + verify-all + 台账

**Files:**
- `docs/demo/m3-demo.md`（追加「W3 补齐」节：catalog/trace/memory/mes/限流/usage curl 段）
- `backend/tests/integration/test_w3r_acceptance.py`（新建，聚合验收）
- `.superpowers/sdd/progress.md`（W3R 台账）
- `docs/demo/m2-demo.md`（缺口终稿追加，与 T8 呼应）

**实现**：
1. m3-demo.md 追加六段（命令 + 预期）：① 注册 `Delivery.OrderRisk` + 查询；② trace 写入（1+N）+ 重发幂等；③ memory 候选 + capability 过滤 + SERVICE 评审 403 举证；④ mes-demo sync → capacity；⑤ 限流 429 + `Retry-After` 举证（低配额租户）+ usage 日报查询；⑥ 前端三页（MSW/真模式）人工清单；
2. `test_w3r_acceptance.py`：①~⑤ 断言化（catalog 注册可查、trace 幂等、memory guard、capacity、429+usage）；
3. `make verify-all` 全绿（migrate-check 按 T20 容器等价法；前端若宿主 flake 用 `--maxWorkers=2 --testTimeout=60000` 并说明）；
4. 台账 W3R 表 + 终审行占位；缺口清单终稿。

**Verify:** `& "backend\.venv\Scripts\python.exe" -m pytest tests/integration/test_w3r_acceptance.py -q` + `make verify-all`
**Commit:** `docs(w3r): 演示脚本补段 + 验收用例 + 收口台账`

---

## 依赖关系（供 subagent 派发）

- T1 → T2/T3/T4（权限码/scopes 先落）；T2/T3/T4 文件不重叠可并行；
- T5 依赖 T1（无关，可并行）但改 `demo/service.py` 与 `adapters_admin`——与 T6/T7 不冲突；
- T6 → T7（usage 表字段与 `bump_usage_daily` 签名）；T8 依赖 T2~T7 全部（契约收口）；
- T9 依赖 T8（SDK 类型 + evidence q）；T10/T11 依赖 T8 的 SDK（health 类型已存在，可并行于 T9）；
- T12 依赖全部。

