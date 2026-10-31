# EDP 第四周（W4：闭环集成 M4 + W3 遗漏收编）

| 项 | 内容 |
|---|---|
| 日期 | 2026-09-17 |
| 状态 | 已获用户批准（对话逐项确认：范围=全量分两波；EDP-021=本地最小 HA 拓扑实测；W3R 评审债务=并行子代理补评；EDP-032 最小版提前至 W4） |
| 上游依据 | 《EDP数据平台开发计划_一阶段.md》W4 任务（EDP-026/028/029、EDP-401~404）+ W3 遗漏收编（EDP-020/021/012 残余、EDP-032 提前）；《EDP数据平台系统设计文档_V2.0.md》7.5（状态机）、7.6（逆向追溯）、8.3/8.4（Guard/审计）、9.5（发布）、B.5/B.9（契约）、C.2/C.3（闭环时序）、13.6.5（智能闭环页）、13.7/13.9（交互/错误码）、附录 A.6/A.8（DDL）、附录 D（页面映射 #11~#19）；W3 缺口清单（m2-demo.md W3-01~42、W3R-01~12） |
| 前置 | W3 两轮已合并 master（后端 439 / 前端 259 测试基线；契约 50 路径指纹 `09f2dae7`；action/management 表已在 0004 迁移落库） |
| 不改动 | W1~W3 冻结契约既有端点语义（`GET /decisions/cases/{id}` 仅向后兼容新增可选字段；`GET /admin/adapters` 仅补可选 `next_cursor`）；既有测试基线只增不破；W5 模块（EDP-030/031、租户页、Agent 页） |

## 1. 范围与决策

本轮 = **W4 全量 + W3 遗漏收编**，单分支 `feat/w4` 两波交付（M4 是单一里程碑，契约一次冻结）：

1. **波1 后端（T1~T8）**：EDP-020 Action 状态机、EDP-012 残余（B.9 四端点 + management seed）、EDP-032 最小版（audit_policies）、EDP-028 闭环聚合、EDP-026 越权矩阵、W3 缺口收口（W3-23/24）、契约冻结；
2. **波2（T9~T15）**：前端 EDP-403 闭环案例页 / EDP-404 决策行动页 / EDP-401 审计页 / EDP-402 适配器页、EDP-029 M4 演示脚本与断言、EDP-021 staging 最小 HA 拓扑 + 演练、收口；
3. **并行线**：W3R 九项评审债务（T4~T12 + 整分支终审）子代理补评，修复以独立 commit 落 master，不阻塞 W4 主线。

**不在范围**：EDP-030/031 质量任务与备份调度（W5，402 页日志抽屉相应降级）、消息中心 API（前端本地通知承接）、`_jobs` 外置与限流多副本（W3-41/42、W3R-01——staging 单 api 副本语义可接受，Redis 外置 W5+ 评估，留缺口清单）、`/admin/outbox/status`（W5）、EDP-501~503 页面（W5）、Playwright E2E（W6）。

## 2. Section A：迁移 0012（T1）

`backend/migrations/versions/platform/0012_w4_baseline.py`（`_exists` 幂等守卫，风格同 0010/0011）：

1. **audit.policies 表**（RLS + 审计字段，风格对齐 A.6）：
   ```sql
   CREATE TABLE audit.policies (
       policy_id     UUID PRIMARY KEY,
       tenant_id     UUID NOT NULL REFERENCES platform.tenants(tenant_id),
       name          TEXT NOT NULL,
       description   TEXT,
       resource_types TEXT[] NOT NULL DEFAULT '{}',   -- 空=全部（fullname 或裸名）
       actions       TEXT[] NOT NULL DEFAULT '{}',    -- 空=全部（精确或 {PREFIX}_* 通配）
       actor_types   TEXT[] NOT NULL DEFAULT '{}',    -- 空=全部（HUMAN/AI/SERVICE）
       notify_channel TEXT,                            -- 可空：inapp/email
       status        TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','DISABLED')),
       -- + 审计字段（created_at/created_by/updated_at/updated_by）
       CONSTRAINT uq_audit_policy_name UNIQUE (tenant_id, name)
   );
   ```
2. **W3-23 收口**：`decision.cases` 补 `UNIQUE INDEX uq_cases_tenant_source ON decision.cases(tenant_id, source_id) WHERE source_id IS NOT NULL` + 普通索引（seed 一对一，既有数据无重复，testcontainers 实测兜底）；
3. **权限码**（uuid5 惯例）：**复用既有 `action:read`/`action:execute`**（0005 基线已有——action:execute → PLATFORM_ADMIN/ADMIN/MANAGER，action:read 另含 ANALYST；不新增 actions:* 码）；新增 `audit:policy_read` → 与 audit:read 同角色集（PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST 四角色，rbac.py:38 实测对齐）、`audit:policy_write` → PLATFORM_ADMIN/ADMIN；
4. **dev API Key scopes 追加** `write:action`（数组去重守卫；与模块 resource 名 `action` 一致——`make_require_access("action", "write")` 的 API Key 轨道）。

## 3. Section B：EDP-020 Action 状态机（T2，`modules/actions`）

B.5 逐字段；六文件模块模式。

| 端点 | 鉴权 | 要点 |
|---|---|---|
| POST `/actions` | JWT `action:execute` / API Key `write:action` | 请求 `{case_id, title, action_type, owner?, owner_role?, due_date?, description?}`；case_id 不存在 → 400（可选关联）；201 `{action_id, status:"PROPOSED", created_at}` |
| GET `/actions?status=&owner=&case_id=&limit=` | JWT `action:read` / readonly | 游标分页（created_at DESC）；简投影含 `allowed_to[]` |
| GET `/actions/{action_id}` | 同上 | 完整对象 + `allowed_to[]`；跨租户 404 |
| PATCH `/actions/{action_id}/status` | JWT `action:execute` / API Key `write:action`（**Human-Only 转移额外 Guard**；双轨为有意超 B.5「仅 JWT」口径，见缺口 W4-11） | 请求 `{from_status, to_status, comment?}`；200 `{action_id, status, updated_at}` |

**状态机（9 态，集中定义转移表）**：

```
PROPOSED → ASSIGNED / REJECTED / CANCELLED
ASSIGNED → ACCEPTED / CANCELLED
ACCEPTED → APPROVED / CANCELLED
APPROVED → EXECUTING(_human) / CANCELLED
EXECUTING → COMPLETED / CANCELLED
COMPLETED → VERIFIED(_human) / CANCELLED
终态：VERIFIED / CANCELLED / REJECTED
```

- **非法转移 → 422 `INVALID_TRANSITION`**，响应含 `allowed_to: [{to_status, human_only}]`（实现时核对 core/errors.py 的 B.0 映射，若 INVALID_TRANSITION 无既有 http 映射则新增，记缺口）；
- **乐观锁**：`from_status` ≠ 当前 status → 409 `CONFLICT`（并发双审批仅一成功；数据库层 `UPDATE ... WHERE status=:from` 双保险）；
- **Human-Only Guard**（`APPROVED→EXECUTING`、`COMPLETED→VERIFIED`）：非 HUMAN → 独立会话审计 `GUARD_DENIED` + 403 `GUARD_POLICY_DENIED`（复用 decisions/memories 模式）；`verified_at/verified_by` 于 VERIFIED 时回填、`completion_time` 于 COMPLETED 时回填；
- **审批意见落证据**（设计 7.5）：转移带 `comment` 非空 → 同事务创建 evidence（source_system=`edp`、source_record_id=`{action_id}#{to_status}`、ref_type=`ACTION`、ref_id=action_id）+ RESULT 链路沿用既有 links 语义；
- `action.verified` 事件回流由 Agent 中枢负责（C.2 原语义，演示经 curl 模拟）；
- 审计：切面自动（`ACTION_CREATE`/`ACTION_UPDATE` 前缀派生）。

## 4. Section C：EDP-012 残余（T3，ebms 模块扩展）

鉴权沿用 `ebms:read`（JWT MANAGER+）。

| 端点 | 要点 |
|---|---|
| GET `/ebms/reports/summary?period=` | `objectives` ← `management.objectives`（A.8 列逐字段）；`kpis` ← `kpi_definitions` join `kpi_values`（period 最近值）；`recent_changes_summary` ← 风险事件（risk_level IS NOT NULL）最近 5 条 `order_no + summary` 文案 |
| GET `/ebms/decisions/pending?limit=5` | OPEN cases 按 risk（P0>P1>P2>P3）+ created_at 排序，默认 5 条；`total_pending` 全量计数（B.9 形状） |
| GET `/ebms/todos` | 三段聚合：`pending_decisions`（OPEN cases）/ `pending_actions`（非终态 actions，due_date 升序）/ `exceptions_to_confirm`（风险事件无 case 关联者） |
| GET `/ebms/objectives` | objectives 完整列表（同 summary.objectives 全量版） |

**seed 扩展**：`demo` 模块增 management 段——objectives（Q4 准时交付率 target 95/current 91.2 等）+ kpi_definitions/kpi_values（on_time_delivery 91.2% 2026-W36，对齐 B.9 示例值）；RESET 清场纳入逆依赖序；幂等（行级 upsert，重跑 0 新增）。

## 5. Section D：EDP-032 最小版（T4，`modules/audit_policies`）

| 端点 | 鉴权 | 要点 |
|---|---|---|
| POST `/admin/audit-policies` | `audit:policy_write` | 201；重名 409 |
| GET `/admin/audit-policies?status=` | `audit:policy_read` | 游标分页 |
| PATCH `/admin/audit-policies/{id}` | `audit:policy_write` | 局部更新（name 除外字段 + 启停）；200 完整对象 |
| DELETE `/admin/audit-policies/{id}` | `audit:policy_write` | 204；前端危险确认 |

**命中打标**：审计切面写行时匹配 ACTIVE 策略（resource_type/action/actor_type 三维，空数组=通配，action 支持 `{PREFIX}_*`）→ 审计行 `detail.policy_hits: [policy_id]`；ACTIVE 策略进程内缓存（模块级，策略写操作失效；单副本语义 docstring 留痕，W3-41 同类）。验收（EDP-032 原文）：创建策略后，匹配的写操作审计行可见 policy_hits。

## 6. Section E：EDP-028 闭环聚合（T5，decisions 模块扩展）

`GET /decisions/cases/{case_id}` **向后兼容新增可选字段**（既有字段不动）：

- `event`：source 事件摘要（event_id/event_type/result_type/risk_level/summary/occurred_at）；
- `steps[]`：闭环时间线，时间升序——`[{step_type: EVENT|CASE_CREATED|DECISION|ACTION_TRANSITION, occurred_at, actor, title, detail?, human_only?}]`（DecisionRecord 与 Human-Only 转移节点标 human_only）；
- `actions[]`：关联行动全量（含 status/owner/due_date/allowed_to）；
- `evidence_chain[]`：四层链 `[{layer: RESULT|DECISION|EVIDENCE|SOURCE, evidence_id?, checksum?, source_system?, source_record_id?, title}]`——RESULT=回流结果事件、DECISION=决策记录（comment 证据）、EVIDENCE=ref_type=CASE 证据集合、SOURCE=各证据指向源记录；verify 由前端按节点调既有 `GET /evidence/{id}/verify`。

**ebms exceptions join 收口**：case 关联改**标量子查询**（`ORDER BY created_at DESC LIMIT 1`），与 A 节唯一约束双保险，消除同事件多案例行倍增（W3-23/T11 遗留）。

## 7. Section F：EDP-026 越权矩阵（T6）

`tests/integration/test_security_matrix.py` 参数化用例集，进 CI 常驻：

- 维度：主体（PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST 的 JWT × 租户 A/B + API Key scope 越界/只读）× 资源组端点抽样（tools×6、objects 写、events 写、evidence、decisions 写 + records Human-Only、actions 写 + Human-Only 转移、ebms 四端点、admin 面 adapters/audit-policies、平台面 tenants）；
- 断言：期望 403 `FORBIDDEN`/404 `NOT_FOUND`/空 items；**RLS 层直查双保险**（B 租户会话查 A 租户数据 → 0 行）；
- 全组合 0 泄露（EDP-026 验收：全部拒绝路径覆盖，用例集进 CI）。

## 8. Section G：W3 缺口收口——后端部分（T7）

- **W3-24**：`GET /admin/adapters` 响应补可选 `next_cursor`（恒 null，4 适配器固定清单；形状对齐 B.0）；
- 前端顺带项（W3R-03/W3-14 动作词表、W3-31 短 ID 尾 8、W3-32 千分位、W3-34/35/36/37 事件页小修）归入 Section I~L 对应任务；
- **明确不做**：`_jobs` 外置与按租户分键（W3-41/42）、限流多副本（W3R-01）——缺口清单标注 W5+。

## 9. Section H：契约冻结（T8，波1 收口）

- 预计新增 ~12 路径（actions×4、ebms×4、audit-policies×4）+ schema 变更（case detail 扩展、adapters `next_cursor`、`INVALID_TRANSITION` 若需补映射）；
- `make contract-export` + sha256 + api-sdk regen（方式沿 W3R T8）+ `make contract-gate` 绿；缺口清单 W4-nn 初稿；
- 波2 原则上不再改契约——发现漂移记清单，仅阻断 M4 时例外。

## 10. Section I：EDP-403 闭环案例页（T9，`features/cases`，M4 关键，真 API）

- `/cases` 列表：筛选（状态 OPEN/DECIDED/CANCELLED + 风险等级 chips）+ 表格（case_no/问题/风险 pill/状态/创建时间/操作）；
- `/cases/:id` 一屏闭环叙事（13.6.5 逐项）：① 问题卡（question + context 影响说明 + 风险 pill + options 列表）② 证据链横向图（Result→Decision→Evidence→源记录横向卡片流，节点点击 → 证据详情弹层 + verify 按钮即时切换 VALID/INVALID）③ Steps 垂直时间线（复用 shared 组件；Human-Only 节点人形图标）④ 关联行动卡（status pill + allowed_to 只读 + 跳 `/actions`）；
- **风险抽屉复用**：`RiskDrawer` 从 overview 泛化（props 化提升 shared 或抽公共组件），顺带统一短 ID 尾 8（W3-31）；
- 路由：`/cases`、`/cases/:id`（侧边栏「智能闭环」组解锁，W4 权限 ADMIN+）。

## 11. Section J：EDP-404 决策/行动页（T10，`features/decisions_actions`，真 API）

- `/decisions`：待决列表（`GET /ebms/decisions/pending`，含 total_pending 角标）+ 决策表单弹窗（选项 radio=case.options + 意见 textarea + Human-Only 人形图标与 tooltip「仅人工可执行」）→ `POST /decisions/cases/{id}/records` → 成功 toast + 列表刷新（case 移出待决）；403 `GUARD_POLICY_DENIED` 文案按 13.9.2；
- `/actions`：列表（status/owner 筛选 + 游标分页）+ 详情抽屉：**9 态状态机可视化**（横向状态轴：已走路径高亮、当前节点 primary、未达/终态 muted）+ `allowed_to` 驱动按钮（human_only 转移带人形图标）+ 转移弹窗（comment textarea）→ `PATCH`；
- 422 `INVALID_TRANSITION` → 按响应 `allowed_to` 重渲染按钮 + toast；409 `CONFLICT` → 「数据已被他人修改，已刷新」自动重拉（13.9.2 逐字）。

## 12. Section K：EDP-401 审计日志页（T11，`features/audit`）

- 视觉基线：`原型设计/pages/审计日志.html` + `导出审计日志 - 弹窗.html` + `新建审计策略 - 弹窗.html`（文案逐字；`data-dom-id` 锚点）；
- 7 列表格（以原型为准：audit_id/时间/actor_type/actor/action/resource_type+resource_id/摘要）+ 筛选（actor_id/resource_type/action/since/until，chips + 工具栏）+ 游标分页（千分位 fmt，顺带 W3-32）；
- **导出弹窗**：参数与接口筛选一一对应，前端 CSV（当前筛选全量拉取，上限保护）；
- **策略管理**：策略列表 tab + 新建弹窗（name/resource_types/actions/actor_types/notify_channel）+ 启停 PATCH + 删除危险确认（#10 模式）——真 API（Section D）；
- **GUARD_DENIED 行高亮**（-error 语义色）；
- **动作/资源词表字典**（收口 W3R-03/W3-13/W3-14）：action 全集常量以审计切面 `ACTION_PREFIXES` + 显式常量（`RATE_LIMITED`/`RATE_LIMIT_WARNING`/`GUARD_DENIED`/`EVIDENCE_VERIFY_FAILED`）实测枚举为准，另含 `{PREFIX}_{VERB}` 派生规则；resource_type 裸名→全名映射表（`records`→`evidence.records` 按 action 前缀消歧）。

## 13. Section L：EDP-402 适配器管理页（T12，`features/adapters`）

- 视觉基线：`适配器管理.html` + `新增适配器 - 弹窗.html` + `测试适配器 - 弹窗.html` + `数据源连接 - 弹窗.html`；
- 7 列表格（adapter/mode/status/health/last_sync_at + access/team 真模式降级「—」，W3-01 差异容忍）；
- 新增适配器弹窗 → `POST /systems`（auth_config 折叠面板，#15 模式）；测试连接弹窗 → `POST /{name}/sync`（incremental）+ status 轮询 → 成功行内提示；三步连接向导（#7 stepper，可回退）；
- 日志抽屉：最近一次 sync status（stats 时间线 #16 风格）+ 提示「完整任务日志 W5 交付」；顺带 W3-37 `useAdapterOptions` `enabled` 门控；
- 真模式 4 适配器 vs MSW 6 演示行差异沿 W3-01 口径。

## 14. Section M：EDP-029 M4 演示（T13）

- `docs/demo/m4-demo.md` 七段对齐计划 7.1 脚本（① 总览开场 → ② 风险抽屉下钻 → ③ 案例详情一屏证据链 + verify → ④ HITL 审批 + Action 闭环 PROPOSED→…→VERIFIED → ⑤ 回总览看 `action.verified` 回流），场景 2（物料 X 缺口 1000）驱动，命令 + 预期读数全记录；
- `tests/integration/test_m4_acceptance.py` 断言化：seed → tools 取数 → events/batch 回流 → case 创建 → records（Human-Only 403 举证 + 通过）→ action 9 态走通（含 422/409 举证）→ ebms todos/pending 口径 → staging compose `--build` 提醒（W3-39）；
- 浏览器级彩排 5 步清单（人工执行，收口 W3-38）；三方正式彩排（≥2 次）为线下动作，仓库内交付「脚本 + 断言 + 实测读数」三级证据。

## 15. Section N：EDP-021 staging 最小 HA（T14）

- `deploy/docker-compose.staging.yml`：etcd×1 + patroni×2（postgres:16 基镜像）+ pgbackrest + api + web + worker（与 dev 同构应用层、数据层换 HA 拓扑）；patroni 配置经卷挂载（restapi/etcd/pgbackrest 段）；
- `deploy/scripts/deploy-staging.ps1`：迁移先行（`edp_migrator` 账号）→ 滚动重建 api/web → `/health` 探测，失败自动回退上一容器；`rollback` 子命令；
- **演练 1 次**：`patronictl switchover` 主从切换 + 切换前后 `/health` 连续探测（记录中断秒数）+ 复制 lag 读数 → `docs/demo/staging-drill.md` 归档；
- 资源不足降级预案：patroni×2 → ×1（无备库，仅验证拓扑编排），留缺口 W5 补双节点。

## 16. 测试 / 门禁 / 风险

**基线（只增不破）**：后端 439 / 前端 259（22+96+141）；`ruff + import-linter`；契约指纹 `09f2dae7` → T8 新值一次冻结；`make verify-all` 七 job（migrate-check 沿 T20 一次性容器等价法）；前端 flake 沿用 `--maxWorkers=2 --testTimeout=60000`。

**测试重点**：状态机转移表全组合单测（9 态 × 合法/非法 + Human-Only 两转移）、并发 from_status 409、Guard 403 + 审计行、安全矩阵参数化 0 泄露、闭环聚合字段完整性（steps/evidence_chain/actions）、ebms 聚合口径（total_pending/todos 三段/summary 三段）、策略命中打标、seed 重放幂等（含 management 段与 cases 唯一约束共存）。

**风险登记**：

| # | 风险 | 缓解 |
|---|---|---|
| 1 | staging Patroni 于 Docker Desktop（Windows 卷权限/资源） | 先起最小拓扑冒烟；不行降 patroni×2→×1 并留缺口 |
| 2 | cases 唯一约束与既有数据冲突 | seed 一对一无重复；迁移进 testcontainers 实测 |
| 3 | EDP-029 依赖三方联调（外部） | 仓库内 curl 模拟中枢全链 + 断言；正式彩排留清单 |
| 4 | 契约新增 ~12 路径漂移 | 附录 B 逐字段对照评审（沿 W3 惯例）；SDK regen 门禁 |
| 5 | 评审补评与 W4 并行触碰同文件 | 补评只读 + 修复独立 commit 落 master；W4 合并时统一处理 |
| 6 | M4 签认（PM/Tech Lead）为线下动作 | 仓库内交付三级证据；签认线下 |

**M4 出口对照**：7 分钟脚本走通（T9/T10/T13）+ 越权矩阵 0 泄露进 CI（T6）+ 彩排 ≥2 次中 ≥1 次仓库内可复现（T13）；三方彩排与签认线下补。

**并行评审线**：开工即派发——W3R T4~T12 九项 + 整分支终审（沿各任务 Notes 与既有测试证据），发现问题以修复 commit 落 master；W4 分支合并前核对评审修复与本分支的冲突面。
