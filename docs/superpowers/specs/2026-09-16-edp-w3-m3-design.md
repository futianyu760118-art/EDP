# EDP 第三周任务（W3-M3：能力数据供给）

| 项 | 内容 |
|---|---|
| 日期 | 2026-09-16 |
| 状态 | 已获用户批准（对话逐项确认：范围=M3 关键路径；EDP-018 最小版纳入；tools 数据走领域表投影；事件页 total/KPI 全真契约扩展；演示数据相对 seed 时刻锚定） |
| 上游依据 | 《EDP数据平台开发计划_一阶段.md》W3（EDP-015~021、EDP-301~304）与 M3 出口条件；《EDP数据平台系统设计文档_V2.0.md》4.2/4.3（适配器与管道）、7.3/7.5、8.3（Read-Only 三层）、8.4（审计与 Guard）、B.3/B.4/B.5/B.8/B.9/B.12/B.13、13.6.2（事件流页）、13.10（演示支撑）、附录 C.2/C.3；《2026-09-15-edp-msw-mock-data-design.md》§4 十场景故事线 |
| 前置 | W1/W2 已合并（后端 215 / 前端 115 测试基线；契约 23 路径指纹 886ea568）；MSW 27 handler 就绪 |
| 不改动 | W1/W2 冻结契约既有端点语义；`ErpMockAdapter` 通用数据集与 W2 测试基线（演示数据集走新增适配器）；W4+ 模块（Action/Trace/Memory/质量/健康页/审计页） |

## 1. 范围与决策

本轮 = **M3 三能力数据就绪**关键路径 + 事件流页，按用户逐项确认的决策：

1. 后端：EDP-015 tools API（六接口 + Read-Only 三层）、EDP-016 演示 seed + 事件重放、EDP-019 回流完善、EDP-012 EBMS exceptions、EDP-018 最小版（cases/records）；
2. 前端：EDP-301 事件流页（含回放向导）；
3. tools 数据供给 = **领域快照表投影**（设计原意）：管道按 object_type 投影到 `master/sales/delivery/rd` 领域表，tools 读领域表；
4. 事件页 total 与 KPI 带 = **全真**：`GET /events` 响应扩展 + `GET /api/v1/health` 的 `ops_metrics`（MSW 既有形状）落真实数据；
5. 演示数据时间 = **相对 seed 时刻锚定**并持久化（`platform.tenants.attributes.demo_seed.anchor`），重跑复用锚保幂等，`RESET=1` 重锚；
6. EDP-018 仅最小版：cases 创建/列表/详情 + records 提交（Human-Only），不含状态流转扩展与 actions（EDP-020 下轮）。

**不在范围（下轮/后续周）**：EDP-011（systems/capabilities/skills）、EDP-013 Trace、EDP-014 Memory、EDP-017 剩余（MES Mock、产能、适配器运维接入）、EDP-020 Action 状态机、EDP-021 staging、EDP-025 限流配额（tools 的 429 运行时本轮不实现，契约声明保留）、EDP-302/303/304 页面、B.9 其余端点（reports/summary、decisions/pending、todos、objectives）。

> 追溯说明：W2 收口记录提及「W3 待办 13 项见对话归档」，该清单未落盘；本 spec 以开发计划 W3/M3 + MSW spec §4 + M2 契约缺口清单为准重建范围，上表即未纳入项。

## 2. Section A：领域快照投影（管道扩展）

### 2.1 触发与事务

`ingest.service.process_record` 在对象 upsert 之后、事件写入之前调用 `project_record(sess, tenant_id, record, obj)`；投影与三元组同事务（RLS 会话已 bind_tenant）。`duplicated` 记录（事件已存在）提前返回，不投影。投影异常按单条记录捕获记 `logger.warning`，不阻断管道。

### 2.2 对象类型 → 领域表映射

| object_type | 领域表 | 映射 |
|---|---|---|
| CUSTOMER | `master.customers` | code=source_id、name、level、attributes=其余键 |
| MATERIAL | `master.materials` | code、name、unit、attributes |
| PRODUCT | `master.products` | code、name、category、status |
| SUPPLIER | `master.suppliers` | code、name、attributes |
| ORDER | `sales.orders` + `sales.order_lines` | order_no=source_id；customer_id=resolve(CUSTOMER, payload.customer_code)；amount/currency/status/delivery_date、snapshot_at=occurred_at；lines[] → order_lines（line_id=uuid5(object_id, idx)、product_id/material_id 解析、quantity/unit_price/amount） |
| PURCHASE_ORDER | `delivery.purchase_orders` | po_no=source_id；supplier_id/material_id 解析；quantity/expected_date/status、snapshot_at=occurred_at |
| INVENTORY | `delivery.inventory` | inv_id=object_id；material_id 解析；warehouse/quantity_available/quantity_reserved、snapshot_at=occurred_at。**对象粒度 =（物料, 仓库）**：source_id=`{material_code}:{warehouse}`，payload 含 material_code/warehouse/available/reserved |
| BOM | `master.boms` + `master.bom_items` | bom_id=object_id；product_id 解析；version=payload.bom_version、status；items[] → bom_items（item_id=uuid5(object_id, idx)、material_id、quantity、position=idx） |
| SUPPLIER_LEAD_TIME | `delivery.supplier_lead_times` | 对象粒度 =（供应商, 物料）：source_id=`{supplier_code}:{material_code}`；id=uuid5(object_id, "lead")；supplier_id/material_id 解析；lead_time_days、updated_at=occurred_at；按 (tenant, supplier_id, material_id) upsert（唯一索引） |
| PROJECT | `rd.projects` + `rd.milestones` | project_id=object_id；project_no=source_id；product_id 解析；status/stage/readiness_level、snapshot_at=occurred_at；milestones[] → rd.milestones（milestone_id=uuid5(object_id, idx)、name/due_date/actual_date/status） |

- 行明细（order_lines/bom_items/milestones）策略：**先按父 id 删后插**（同事务，revision 更新时防残留）；
- `resolve(tenant, object_type, source_id)` 查 `master.business_objects` 自然键；未命中 → FK 置 NULL + warning（演示数据集按依赖顺序排列：客户/物料/产品/供应商先于订单/采购/BOM）；
- 投影为派生快照行，**加入审计切面排除清单**（与 outbox 同策略，避免派生写污染业务审计）；领域表 RLS/索引由 0004 迁移提供，本轮无新表。

### 2.3 模块归属（import-linter：模块间仅可 import 对方 service）

新增模块 `modules/projections`：`models.py` 承载全部领域表 ORM（`master.customers/materials/products/suppliers/boms/bom_items`、`sales.orders/order_lines`、`delivery.inventory/purchase_orders/supplier_lead_times`、`rd.projects/milestones`；沿既有约定：不声明 ForeignKey、不参与迁移）；`service.py` 提供 `project_record(sess, tenant, record, obj)` 与 tools 查询服务（`get_order/list_orders/get_inventory/…`）。

- `ingest.service.process_record` 调用 `projections.service.project_record`（同事务）；
- `modules/tools` 只经 `projections.service` 读数据，不直连领域 ORM。

## 3. Section B：演示数据集与 seed/replay（EDP-016）

### 3.1 适配器与时间锚

- `edp_adapters` 新增 `DemoErpAdapter`（name=`erp-demo`）、`DemoPlmAdapter`（name=`plm-demo`）；`ErpMockAdapter` 保持不动（W2 基线）；
- 端口扩展：`fetch_full(object_types, *, anchor=None)` / `fetch_incremental(since, *, anchor=None)`（keyword-only 可选参数；既有实现忽略）；`ingest.run_sync/run_sync_per_record` 经 `platform.service` 读租户 `attributes.demo_seed.anchor` 并传入（platform.service 增读写函数）；未设置 → 模块常量 `DEMO_ANCHOR=2026-09-28T08:30:00Z` 兜底（适配器自身仍为纯函数：同锚 → 同记录）；
- 数据集时间 = anchor + 固定偏移（分钟/小时/天，确定性）；`source_system` = `erp` / `plm`（事件展示来源）；
- 注册：`adapters_admin` 注册表登记三适配器（erp / erp-demo / plm-demo），sync API 可按名触发与 replay。

### 3.2 数据集（十场景故事线，对齐 MSW spec §4）

`modules/demo/dataset.py` 确定性常量（值对齐 MSW fixtures 与 B.8 示例）：

- **快照段**（走适配器 → 管道 → 对象/事件/证据/领域表）：订单对象 10 个（对齐 MSW fixtures：SO-2026-00122/00123/00124/00126/00128/00129/00130/00131 + 例行单，含行明细；覆盖场景 1/2/3/5/6/7/8/9）、客户 C-008 等、物料 X-100/Y-200、产品 P-F/P-D、供应商 S-021/S-030/S-118、采购单 PO-2026-00771/00785、BOM(P-F,V3)、库存（X-100@WH-01 等）、供应商交期（S-021→X-100=10 天 等）；PLM：项目 PRJ-D + 里程碑（场景 4）；
- **回流段**（服务层调用，幂等键 `seed-demo:results:v1`）：8 条能力结果事件（`capability.result.*`，带 result_type/risk_level/score、data.reason/recommendation/summary/order_no，对齐 MSW fixtures 行）+ 场景 2 case（OPEN，question/options/evidence_ids → CASE links）；场景 10 的 `adapter.sync.failed` 事件一并落库；
- 事件类型说明：真实数据为 `{TYPE}_SNAPSHOT`（管道）+ `capability.result.*`/`adapter.sync.failed`（回流）；MSW 的 `order.created` 等展示型事件不迁入（避免双轨，记入契约偏差清单）。

### 3.3 seed 服务与 CLI

- `resolve_anchor(sess, tenant_id)`：读 tenants.attributes.demo_seed.anchor；缺失则写 `{anchor: now 截整点 ISO, version: 1}` 并返回；
- `seed(sess_factory, tenant_id, reset=False)`：可选 reset → 快照同步（erp-demo + plm-demo，mode=full，逐记录独立事务）→ 回流段（events/batch 服务调用 + 结果证据/links + case）；
- `reset`：删 default 租户业务数据（master/event/evidence/decision/sales/delivery/rd/quality 各 schema 本租户行 + outbox + idempotency_keys + systems 水位行；审计保留仅追加）并重锚；
- CLI `python -m edp_api.modules.demo.cli seed [--reset]`；Makefile：`make seed-demo` / `make seed-demo RESET=1`。

### 3.4 replay（事件重放）

- `SyncTriggerRequest.mode` Literal 扩展为 `full|incremental|replay`；`replay` 语义 = `fetch_full` 全量重放 + 可选 `since` 过滤（occurred_at ≥ since）；UUIDv5 幂等 → 重放计数 `duplicated`，不产生重复行、不推 revision；
- 回放向导的「按原序 / 并发」仅前端呈现（与 MSW 一致，不改 API 参数）；执行经 `POST /admin/adapters/{name}/sync`（202）。

### 3.5 幂等与演示复位

- `make seed-demo` 重跑：锚复用 → 快照事件全部 duplicated 跳过；回流段幂等键命中 → 不重复；case 已存在则跳过；
- `RESET=1`：清业务数据 + 重锚后重建（M4 演示「重放复位」入口）。

## 4. Section C：tools API（EDP-015）

新模块 `modules/tools`（六文件模式），前缀 `/api/v1/tools`：

| 端点 | 数据源 | 响应要点（B.8） |
|---|---|---|
| GET `/orders/{order_no}` | sales.orders + order_lines + master.customers | 客户/金额/状态/交期 + lines |
| GET `/orders?customer=&status=&limit=` | sales.orders（join customers） | 摘要列表（无 lines） |
| GET `/inventory?material_code=` | delivery.inventory（join materials） | warehouses[] + total_available + snapshot_at |
| GET `/purchase-orders?material_code=&status=` | delivery.purchase_orders | items + next_cursor |
| GET `/bom?product_code=` | master.boms + bom_items | bom_version + items[] |
| GET `/supplier-lead-times?supplier_code=` | delivery.supplier_lead_times | lead_times[] + updated_at |
| GET `/customers/{customer_code}` | master.customers | name/level/attributes |

- **Read-Only 三层**：① 应用层——路由仅注册 GET（非 GET → 405，统一错误 envelope，补 StarletteHTTPException→METHOD_NOT_ALLOWED 处理器）+ 双轨鉴权 `make_require_access("tools","read")`（SERVICE scope=`readonly`；HUMAN 权限 `tools:read`）；② 数据库层——迁移 0010 建 `edp_agent_ro`（NOLOGIN，`master/sales/delivery/rd` 四 schema SELECT）+ `GRANT edp_agent_ro TO edp_app`，tools 查询事务内 `SET LOCAL ROLE edp_agent_ro`（事务级，自动复位）；③ 审计层——scope/权限拒绝 → 显式 `GUARD_DENIED` 审计（resource_type=tools，含 actor/scope 详情）后抛 403；
- 响应统一含 `evidence_hint: {object_id, event_id}`（该对象最新 `{TYPE}_SNAPSHOT` 事件；无则 event_id=null）；无数据 → 404 NOT_FOUND；429 本轮不实现（EDP-025）；
- 对象解析：按 code 查领域表（join master 主数据）；订单/库存/采购/BOM/交期/客户全部限定租户（RLS 兜底）。

## 5. Section D：回流完善 + 决策案例最小版（EDP-019/018）

### 5.1 events/batch 结果证据

- 对 `risk_level` 非空的事件（能力结果回流）：同事务自动创建结果证据（`source_system`=事件来源、`source_record_id="result:{event_id}"`、`snapshot=ev.data`、`event_id`、`captured_at=occurred_at`）+ `RESULT` link（ref_id=event_id）；事件已存在（duplicated）→ 跳过，不重复建；
- 幂等计数：`platform.tenant_usage_daily` 增列 `events_duplicated`（0010）；events/batch 与管道两条入库路径 upsert `(tenant, usage_date)` 的 `events_in` / `events_duplicated`。

### 5.2 决策案例（B.5 最小版，新模块 `modules/decisions`）

| 端点 | 鉴权 | 要点 |
|---|---|---|
| POST `/decisions/cases` | SERVICE scope `write:decision` / HUMAN `decision:decide` | case_no=DC-YYYYMMDD-NNN（当日同租户序号，唯一索引兜底）；`evidence_ids[]` → `CASE` links；201 `{case_id, case_no, status, created_at}` |
| GET `/decisions/cases?status=&risk_level=&limit=` | HUMAN `decision:read` / SERVICE `readonly` | 游标分页 |
| GET `/decisions/cases/{case_id}` | 同上 | 含 `evidence_refs[{evidence_id, checksum, source_system}]`（links join）+ `decisions[]` |
| POST `/decisions/cases/{case_id}/records` | **Human-Only**：`principal.kind != HUMAN` → 403 `GUARD_POLICY_DENIED` + 审计；HUMAN 需 `decision:decide` | 成功 → 写 decision.records + case 置 `DECIDED`/`decided_at`；201 `{decision_id, case_id, decision_time, case_status}` |

- 迁移 0010 为 dev API Key（`edp-dev-agent-hub-key`）追加 `write:decision` scope。

## 6. Section E：EBMS exceptions + 事件契约扩展（EDP-012）

### 6.1 GET /api/v1/ebms/exceptions（新模块 `modules/ebms`）

- 数据：`risk_level IS NOT NULL` 的事件（occurred_at DESC）；`severity`（risk_level）与 `status` 过滤、`limit`（默认 20，上限 100）、游标分页；
- `case_id` = `decision.cases` 中 `source_id = event_id` 的案例（join 派生）；`order_no` = data.order_no 回退对象 source_id；`summary` = data.summary 回退 data.reason 回退 event_type；
- `status` 语义：`OPEN`（默认）= 无已决策案例；`RESOLVED` = 关联案例已 DECIDED（与 MSW mock 约定差异记入契约偏差清单）；
- 鉴权：JWT `ebms:read`（0010 新增权限码，角色集同 decision:read）。

### 6.2 事件响应扩展（`GET /events` 与 `/events/{id}`）

| 字段 | 作用范围 | 来源 | 说明 |
|---|---|---|---|
| `total` | 仅列表 | 同过滤计数 | `core.pagination.Page` 增可选 `total`（本轮仅 events 填充，其余端点保持缺省，后续逐页转正）；解冻契约缺口 #3；前端分页文案「显示 X–Y 条，共 N 条」 |
| `ingest_latency_ms` | 列表 + 详情 | `event.events` 新列（0010） | 入库处理耗时：管道/批量实测；seed 用确定性值 |
| `delivery_status` | 列表 + 详情 | outbox 左连接派生 | PUBLISHED→DELIVERED / PENDING→PENDING / FAILED→DEAD_LETTER |
| `object_source_id` | 列表 + 详情 | join master.business_objects | 表格「对象」列展示（如 SO-2026-00123） |

### 6.3 GET /api/v1/health（B.13 子集）

- 挂 `tenant_scoped`；基础字段 `status/db/outbox_pending/last_sync/version` + `ops_metrics`：`events_24h`（created_at 近 24h 计数）、`ingest_peak_24h`（小时峰值）、`p95_latency_ms`（近 24h 分位）、`idempotency_hit_rate`（近 24h duplicated/(in+duplicated)，日粒度近似）、`dlq`（outbox FAILED 计数）、`evidence_count`；其余 MSW 扩展字段省略（前端可选渲染）；
- `?deep=true` 需 ADMIN：本轮 `db_ha` 返回基础值（role=primary、replicas/lag 取 pg_stat_replication，开发库为 0）。

## 7. Section F：前端 EDP-301 事件流页

### 7.1 页面（`features/events/`）

视觉基线：`原型设计/pages/事件流.html` + `事件回放 - 执行流程.html`；设计 13.6.2。

- **KPI 带**（4 卡）：24H 事件（+峰值副标）/ P95 接入延迟 / 幂等命中率（+副标）/ 死信队列（warning 副标）——`GET /api/v1/health` `ops_metrics`（无环比数据源，副标降级隐藏）；
- **工具栏**：事件类型下拉（由事件类型字典派生）+ 时间范围（24H/7D/30D，映射 since/until）+ 筛选；已生效筛选 chips（设计 13.6.2 提及搜索框、原型无——本轮按原型不设，留痕待后续加 `q` 契约参数）；
- **表格 9 列**：事件（短 ID mono）｜类型（彩色 pill）｜对象（object_source_id 回退短 UUID）｜描述（data.summary/reason/note，truncate）｜发生时间｜接入耗时（ingest_latency_ms）｜来源（展示名映射）｜状态（delivery_status → DELIVERED/PENDING/DEAD_LETTER pill）｜操作（详情）；
- **详情抽屉**：事件全字段 + data JSON + 关联证据行（结果事件经 `GET /evidence?ref_type=RESULT&ref_id={event_id}`，无则空态）；
- 游标分页（`CursorPagination` + 「显示 X–Y 条，共 N 条」）、空态三件套、「新建订阅」占位（toast「后续交付」）。

### 7.2 回放向导（三步 stepper 弹窗 720px）

① 选择事件（列表 + 选中回显）→ ② 配置参数（目标适配器 select ← `GET /admin/adapters`；回放模式 radio 卡：按原序/并发；开始时间 datetime-local；底部只读事件摘要卡）→ ③ 确认执行 → `POST /admin/adapters/{name}/sync {mode:"replay", since?}` → 202 → 成功反馈（sync_id/状态），失败按 13.9.2 文案。

### 7.3 MSW 对齐与双模式

- api-sdk regen 后同步 `mocks/types.ts` / `EventResponse` 新字段（total/ingest_latency_ms/delivery_status/object_source_id）；events fixtures 补齐字段；
- health handler 已含 `ops_metrics`（对齐真实子集）；adapters replay 已有；
- 真 API 模式（`VITE_USE_MSW=0`）冒烟：列表/筛选/分页/向导 202。

## 8. 迁移 0010 清单

1. `event.events` 加列 `ingest_latency_ms INTEGER`（可空）；
2. `platform.tenant_usage_daily` 加列 `events_duplicated BIGINT NOT NULL DEFAULT 0`；
3. 角色 `edp_agent_ro`（NOLOGIN）+ `master/sales/delivery/rd` 四 schema `USAGE/SELECT` 授权（覆盖六工具域）+ `GRANT edp_agent_ro TO edp_app`；
4. 权限码 `tools:read`、`ebms:read` + 角色矩阵行（对齐 decision:read 角色集）；
5. dev API Key scopes 追加 `write:decision`。

## 9. 契约变更清单（EDP-007 流程）

- 新增路径：`/api/v1/tools/{orders/{order_no}, orders, inventory, purchase-orders, bom, supplier-lead-times, customers/{customer_code}}`、`/api/v1/decisions/cases{,/{case_id},/{case_id}/records}`、`/api/v1/ebms/exceptions`、`/api/v1/health`；
- 修改：`GET /events` 响应四字段；`SyncTriggerRequest.mode` Literal + `replay`；
- 收口：`make contract-export`（openapi.json + sha256）→ api-sdk regen → `make contract-gate` 绿；
- 契约偏差清单追加：exceptions status 语义（mock 约定 → 真实 join）、展示型事件类型不迁入 seed、adapters 清单字段差异（W4 对齐）。

## 10. 验收映射（M3 出口条件）

| M3 出口条件 | 载体 |
|---|---|
| tools 六接口对三大能力联调通过（带 evidence_hint） | 集成测试（六端点 + evidence_hint + RLS 跨租户 404）+ `docs/demo/m3-demo.md` curl 段 |
| 非 GET → 405；readonly 外 Key → 403 + GUARD_DENIED 审计 | 集成测试（405 envelope / 403 后审计行存在）+ `edp_agent_ro` INSERT 被拒断言 |
| 回流事件含风险字段且 EBMS exceptions 可查 | 集成测试（batch 结果事件 → 证据/links → exceptions 含 case_id）+ seed 实测 |
| 演示数据 seed 可重放（EDP-016） | `make seed-demo` 幂等测试（二跑 0 新增）+ replay 202/duplicated 断言 |
| EDP-301 分页文案与向导 | 前端 Vitest（计数文案/向导三步/202）+ 真 API 冒烟 |
| 全量回归 | `make verify-all` 全绿（后端 lint+单测+集成+迁移；前端 lint+Vitest；契约指纹） |

## 11. 工程约定与分波

- 分支 `feat/w3-m3`；后端新模块沿六文件模式；迁移集中于 `0010`；
- 波 1（后端数据底座）：投影 → demo 数据集/seed/replay → tools → 回流/cases → EBMS/事件扩展/health → 契约导出与 SDK；
- 波 2（前端）：EDP-301 页面 + 向导 + MSW 对齐 + 真 API 切换；
- 波 3（收口）：`docs/demo/m3-demo.md`（seed → tools 六接口 → 405/403 举证 → 回流 → exceptions → replay → 控制台）、verify-all、进度台账与缺口清单更新。
