# AEOS 企业数据与证据中台 EDP 迭代版总体方案 V1.2（修订稿）

**上位框架：** AEOS V7.2  
**中台编号：** M02  
**工程简称：** EDP / Data Foundation  
**方案版本：** V1.2  
**基准版本：** V1.1（本稿为 V1.1 的修订稿，未在本文列出的章节沿用 V1.1 原文）  
**修订依据：** 《EDP 数据与智能中台 × AEOS V7.2 架构与代码核准报告 V1.0》（2026-10-06）+ EDP 仓库代码盘点（2026-10-09，迁移至 `0013_w5_baseline`）  
**目标版本阶段：** 从当前 L2.5～L3 迭代至 L4  

---

# 〇、修订说明

V1.1 发布后，以核准报告与当前源码为准重新核对，发现三个根本性问题：

1. **排期基线错位。** V1.1 第四十八节的 W1–W6 按"Decision / Action / Trace / ToolAPI / EBMS 尚未实现"排期，但当前代码中这些能力已完整实现（迁移已推进到 W5 基线）。按 V1.1 排期执行会出现"重做已有能力、真缺口没时间"的倒挂。
2. **范围过载。** V1.1 把 7 个治理模块 + 准入管线 + 双层人机共审 + 归档 + 血缘塞进原 6 周，同时保留全部原 V1.0 范围。核准报告的核心告诫（设计领先代码、先闭环后扩展）实际被稀释。
3. **边界与冲突未处理。** 核准报告第十一节提出的 Goal/KPI/Constraint Owner 边界问题 V1.1 未回应；V1.1 的准入门禁 G1–G4 与核准报告的架构门禁 G0–G5 同名冲突；四层数据模型与现有 ingest 直写投影的实现没有映射关系。

本修订稿变更清单如下：

| 编号 | 变更点 | 对应 V1.1 章节 | 性质 |
| --- | --- | --- | --- |
| C1 | 新增代码现状基线（2026-10-09 盘点），作为排期唯一基准 | 新增 | 新增 |
| C2 | 重写 6 周迭代计划，按代码实际缺口排期 | 第二十四 / 四十八节 | 重写 |
| C3 | 治理能力分期：第一阶段仅覆盖首链路关键对象，机器审为主、人工抽检 | 第三十一节起 | 修订 |
| C4 | 数据准入门禁 G1–G4 更名 A1–A4，避免与架构门禁 G0–G5 冲突 | 第三十八～四十二节 | 修订 |
| C5 | 新增 Goal / KPI / Constraint Owner 边界（规则归 M01，事实归 EDP） | 新增 | 新增 |
| C6 | Metric Registry 边界澄清（定义 Owner=业务域/M01，EDP 只做注册与记录） | 第十一节 | 修订 |
| C7 | 四层数据模型与现有资产映射表 + ingest RAW 留存改造清单 | 第三十三节 | 增补 |
| C8 | A2/A3 审核执行者说明（自治中心建成前由 EDP 轻量审核工作台承载） | 第四十 / 四十一节 | 增补 |
| C9 | Value Ledger、search_objects 多维查询补入排期 | 第四十六 / 四十八节 | 增补 |
| C10 | Contract Pack 增加治理类 schema 并进入 CI 门禁 | 第二十一节 | 重写 |
| C11 | 模块结构对齐代码实际命名，并纳入治理模块 | 第二十节 | 重写 |
| C12 | 连接器计划收缩：ERP + MES 真实连接 + Excel/CSV 通道，CRM 明确后移 | 第十四节 | 修订 |
| C13 | 验收标准增补治理类指标 | 第二十六节 | 重写 |
| C14 | 前端页面清单对齐现状 + 数据准入工作台 | 第十九节 | 修订 |
| C15 | 新增 memory 处置（已实现但属 P2，冻结新功能）、quality 演进说明、worker 调度缺口说明 | 新增 | 新增 |
| C16 | "需要立即停止的事项"增补 | 第二十八节 | 修订 |

---

# 一、新增：代码现状基线（2026-10-09 盘点）

本节是 V1.2 排期的唯一事实基准。任何周计划必须先与本节核对，不得按"设计假设"排期。

## 1.1 已完整实现（不重做、不返工）

| 模块 | 关键事实 |
| --- | --- |
| platform / tenantmgmt | JWT/API Key、RLS 多租户、配额、限流、审计切面（aspect.py）、audit_policies |
| registry | `master.business_objects`，组合键 upsert、revision 历史、乐观锁 |
| events | `event.events/outbox`，三层幂等（Idempotency-Key/UUIDv5/ON CONFLICT）、SKIP LOCKED 分发 |
| evidence | `evidence.records/links`，canonical sha256、verify 重算、逆向追溯 |
| decisions | `decision.cases/records`，案例编号、Human-Only 决策、GUARD_DENIED 留痕 |
| actions | `action.actions`，9 态状态机（TRANSITIONS 单一事实来源）、乐观锁 409 |
| traces | `trace.traces/tool_calls`，trace_id 幂等、工具调用轨迹 |
| tools | Agent Tool API，`edp_agent_ro` 只读角色、404/200 分层语义 |
| ebms | 只读聚合：exceptions / reports / pending decisions / todos / objectives |
| memories | CANDIDATE→APPROVED/REJECTED 人工评审（Human-Only） |
| catalog | `platform.systems/capabilities/skills` |
| quality | 对账（偏差≤2%）、覆盖率、抽验 checksum、重检任务（ops.tasks + Redis 互斥） |
| projections | 14 张领域投影表（master/sales/delivery/rd），供 tools/ebms 查询 |
| ingest | 单记录单事务：对象 upsert→投影(savepoint)→SNAPSHOT 事件→证据→outbox |
| adapters_admin | mock 适配器同步任务轨道 |
| health / demo / search | 已实现 |

迁移基线：`platform/0001` ～ `platform/0013_w5_baseline`，共 49 张表。

## 1.2 部分实现

| 能力 | 现状 | 缺口 |
| --- | --- | --- |
| Result | 仅 `event.events.result_type` 列 + `capability.result.*` 事件 | **无独立模块**，无 Result Contract 实体、无 verified 闭环 |
| Metric | `management.objectives/kpi_definitions/kpi_values` 三表 + ebms 只读查询 | 无 Metric Registry、无管理 API、无 period_rule |

## 1.3 完全不存在

- Result 独立模块、Metric Registry、Value Ledger；
- 治理全栈：data cleaning、standardization、entity resolution、classification/taxonomy、tag、RAW/CLEAN/STANDARD/CURATED 四层、data profiling、数据准入状态机、lineage（血缘）、数据资产审核工作流——**代码为零**；
- Contract Pack：`contracts/` 目前只有 `openapi.json + sha256 + README`，无任何域 schema；
- 真实系统连接器：`backend/packages/edp_adapters` 仅 erp_mock / mes_mock / demo_plm，**无 CRM，无真实连接**；
- worker 调度能力：现 worker 只有 outbox 分发，无定时摄取/编排任务；
- Period Service（AEOS 经营窗口 16→15 日）。

## 1.4 基线结论

> 原 V1.0 计划的 W3/W5 能力已提前完成，而 V1.1 新增的 W1/W2 治理栈为零。**V1.1 的 6 周排期整体失效，V1.2 按真实缺口重排（见第十二节）。**

---

# 二、修订：核心设计原则（V1.1 第三节）

原八条原则全部保留，增补两条并冻结：

**第九，先基线后计划。** 任何迭代计划的排期必须以代码盘点为基线，不允许按"设计假设"排期；已实现模块不重复建设。

**第十，治理随闭环走。** 数据治理能力随第一条业务链同步建设，第一阶段只治理闭环涉及的关键对象，不搞平台级全量治理（详见第四节 C3）。

---

# 三、修订：Object Contract（V1.1 第五节）

原字段全部保留，增补：

```text
official_version        -- 指向 CURATED/OFFICIAL 层版本（空 = 尚未成为正式事实）
layer_status            -- RAW / CLEAN / STANDARD / CURATED / ARCHIVED（冗余索引字段）
lineage_id              -- 指向数据血缘记录
```

说明：`business_object` 保存"标识 + 必要事实 + 引用 + 快照 + 证据"的定位不变；新增字段用于把对象与四层模型、血缘、准入状态串起来，不复制业务系统全字段。

---

# 四、新增：Goal / KPI / Constraint Owner 边界

响应核准报告第十一节（P0 级边界问题）。正式冻结：

```text
M01 AEOS Kernel
│
├─ Goal 定义与目标值
├─ KPI 口径定义
├─ Policy / Constraint
└─ 指标口径争议裁决
        ↓ 下发快照
M02 EDP
│
├─ Goal Snapshot（记录，只读引用）
├─ KPI Value（计量值）
├─ Metric 注册表（记录版：注册、版本、公式快照）
├─ Result
├─ Evidence
└─ 历史状态
```

原则：

1. **规则归 Kernel，事实归 EDP。** EDP 不得新增目标管理、指标口径决策功能；
2. 现有 `management.objectives / kpi_definitions / constraints` 表的处置：第一阶段保留现状，但必须加 `owner` 与 `source`（M01 下发 / 域 Owner 录入）字段，并在 W4 建 Metric Registry 时一并迁移，杜绝 EDP 内部产生第二套口径；
3. 指标定义 Owner 为业务域（Delivery / Sales / Quality / Finance / R&D），目标值 Owner 为 M01，EDP 只做注册、版本与记录（见第六节）。

---

# 五、修订：Metric Registry（V1.1 第十一节）

原字段保留，增补边界字段：

```text
definition_owner       -- 业务域，如 Delivery
definition_source      -- M01_KERNEL / DOMAIN
target_owner           -- M01（目标值决策方）
snapshot_policy        -- 定义变更时是否留存快照（默认必须）
```

并增加约束：

- 所有 EBMS 指标必须引用 Metric Registry，禁止前端临时写公式（保留原要求）；
- Metric Registry 的 formula 是**注册快照**，口径变更必须由 definition_owner 发起、版本化、留审计；EDP 不裁决口径；
- W4 交付 `management.kpi_*` 三表到 Metric Registry 的迁移映射。

---

# 六、修订：Connector 优先级（V1.1 第十四节）

第一阶段交付范围收缩为：

```text
1. ERP 真实 Connector（首链路必需）
2. MES 真实 Connector（首链路必需）
3. Excel / CSV 导入通道（历史数据准入演示用）
```

明确后移第二阶段的：PLM、CRM、品质、财务、外部 API、设备数据。

说明：当前代码仅 erp_mock / mes_mock / demo_plm，**CRM 无任何现成代码，属新造**，不应出现在 W5 交付物中。统一接口 `connect() / healthcheck() / pull() / normalize() / checkpoint() / retry() / replay()` 保留。

---

# 七、修订：前端控制台定位（V1.1 第十九节）

页面清单按代码现状收敛为：

```text
运营总览 / 对象注册 / 事件 / 证据 / 决策案例 / 行动 / 轨迹 / 审计 / 质量
/ 适配器 / 系统健康 / Agent Tool / 记忆评审（冻结维护） / 演练 / 全局搜索 / 租户
/ 数据准入工作台（W2 新增，A1–A4 状态视图 + 人工抽检入口）
```

不变的约束：不为 EBMS 或自治中心做经营驾驶舱。

---

# 八、修订：新版模块结构（V1.1 第二十节）

与代码实际命名对齐，并纳入治理模块：

```text
backend/apps/api/edp_api/modules/
│
├── platform
├── tenantmgmt
├── catalog
├── health
│
├── registry
├── projections
├── search
│
├── ingest
├── events
├── evidence
│
├── decisions          -- 原 decision_record，代码已实现
├── actions            -- 原 action_record，代码已实现
├── traces             -- 原 trace，代码已实现
├── memories           -- 已实现，P2 冻结新功能（见第十三节）
│
├── result             -- 新增（W3）
├── metric             -- 新增（W4）
├── value              -- 新增 Value Ledger（W4）
├── period             -- 新增 Period Service（W4）
│
├── governance         -- 新增（W2）
│   ├── data_profiling
│   ├── cleaning_rules
│   ├── standardization
│   ├── entity_resolution
│   ├── classification
│   └── tagging
│
├── admission          -- 新增（W2）：A1–A4 状态机、归档、审核记录
├── lineage            -- 新增（W3）
│
├── quality            -- 演进：对账/覆盖率/抽验 + 六维 DQ（不重建）
├── audit
│
├── adapters_admin
├── tools              -- 原 toolapi
└── ebms               -- 原 ebms_api
```

命名变更说明：V1.1 的 `decision_record / action_record / trace / toolapi / ebms_api` 统一改为代码实际使用的 `decisions / actions / traces / tools / ebms`，避免文档与代码两张皮。

---

# 九、修订：Contract Pack（V1.1 第二十一节）

```text
contracts/
│
├── object/   business-object.schema.json
├── event/    event.schema.json
├── result/   result.schema.json
├── evidence/ evidence.schema.json
├── decision/ decision-record.schema.json
├── action/   action-record.schema.json
├── trace/    trace.schema.json
├── metric/   metric.schema.json
├── value/    value-ledger.schema.json
│
├── governance/
│   ├── cleaning-rule.schema.json
│   ├── classification.schema.json
│   ├── lineage.schema.json
│   └── admission-state.schema.json
│
└── openapi/
```

冻结节奏（Contract First）：

```text
W1 冻结：object / event / result / evidence / governance 四个 schema
W3 冻结：decision / action / trace（与已实现代码对账导出，不得反向改代码语义）
W4 冻结：metric / value
```

所有 schema 必须进入 CI Gate：在现有 openapi 指纹门禁旁增设 JSON Schema 校验，schema 变更未过 CI 不得合入。

---

# 十、修订：第一条正式业务闭环（V1.1 第二十二节）

原链路保持不变，增补两条硬约束：

1. W6 闭环中所有 Result 引用的 Business Object 必须处于 OFFICIAL/ARCHIVED 状态，否则 Result 不得作为经营事实；
2. 现有 `ebms` / `tools` 端点当前直查 projections，**W3 必须完成 `official_only` 过滤改造**（默认仅读 OFFICIAL/ARCHIVED，第四十六节语义一致）。

---

# 十一、修订：轻版 / 重版（V1.1 第二十三节）

轻版清单增补治理最小集：

```text
Mock Connector + Excel/CSV 通道
PostgreSQL
Modular Monolith
Outbox
RAW 留存表 + A1–A4 状态机
单域清洗规则 + 人工抽检审核
基础 Result / Evidence / Metric Registry / Value Ledger
```

轻版不引入：Kafka、Lakehouse、K8s、实时计算、向量集群、**重型 MDM/图谱治理产品**（治理先用手工 + 规则 + 单表实现）。

---

# 十二、重写：6 周迭代计划（替换 V1.1 第二十四 / 四十八节）

以代码现状基线（第一节）为准重排。已完成的 Decision/Action/Trace/ToolAPI/EBMS 不再排期重建，只在 W3 做与 Result 的关联补全。

## W1：契约冻结 + 治理模型冻结 + 现状映射

```text
System Boundary / Data Ownership / Goal-KPI Owner 边界（第四节）
Contract Pack 冻结：object / event / result / evidence / governance schema
Data Source Inventory：mock 基线 + 真实 ERP/MES 字段清单获取计划
四层模型 ↔ 现有 49 张表映射表（第七节清单的输入）
A1–A4 状态机与审核记录模型定义
清洗规则注册表 / 标准化字典 / 分类维度模型（仅首链路对象范围）
```

Gate：**G0 / G1**（架构门禁 / 契约门禁）

## W2：治理最小闭环（RAW → ARCHIVED，仅首链路关键对象）

```text
ingest 改造：RAW 持久化（raw_payload + batch_id + checksum），先留存后处理
CLEAN / STANDARD 层 + 清洗规则注册表落地（Customer / Product / Material / Order 范围）
实体解析（别名映射）+ 分类 / 标签基础
A2 本系统机器审（全量）+ 人工抽检；A3 管理机器复审 + 人工确认（关键对象）
A4 归档 + 数据准入工作台（最小页面）
数据质量门禁接入管道
```

验收：

```text
mock 订单数据集 100% 走完 RECEIVED → ARCHIVED
血缘可回放（Source → Raw → Rule → Review → Official）
```

## W3：企业事实与结果层 + official_only 改造

```text
result 独立模块（result_id / result_type / object_ref / period / value / status / evidence_refs / verified_*）
decisions / actions / traces / evidence 增加 result_refs 关联
business_object 挂 official_version / lineage_id（第三节）
lineage 模块
ebms / tools 端点接入 official_only 过滤
Contract Pack 冻结：decision / action / trace
```

验收：

```text
Result → Evidence 100% 可追溯
Decision → Action → Result → Evidence 全链可追踪
```

Gate：**G2**（数据门禁，首段）

## W4：Metric + Value + Period

```text
Metric Registry（复用 management.kpi_* 三表，按第五节迁移映射）
Period Service（AEOS 经营窗口：上月16日～当月15日）
Value Ledger 基础版
EBMS 指标全量走 Registry
Contract Pack 冻结：metric / value
```

验收：

```text
EBMS 指标口径 100% 引用 Registry
AEOS 周期聚合结果正确
```

Gate：**G3**（闭环门禁，首段）

## W5：真实连接器 + 准入规模验证 + 多维查询

```text
ERP 真实 Connector、MES 真实 Connector、Excel/CSV 通道（第六节收缩范围）
真实数据接入 W2 管道，抽样双审跑通
worker 调度任务：profiling / 清洗 / 机器审编排（补 scheduler 缺口）
search_objects 多维查询（dimensions / classifications / tags / official_only）
Agent Tool API 增补：全部走 OFFICIAL 数据
```

验收：

```text
真实数据 A1–A4 全链路跑通（抽样）
Agent 无法读到非 OFFICIAL 数据
```

## W6：经营闭环 UAT + 验收

```text
销售 → 订单 → 交付 → 应收 全链 UAT（含准入、Result、Decision、Action、Evidence、Trace）
六类异常跑通：物料缺料 / 产能不足 / 交期风险 / 品质异常 / 出货延期 / 应收逾期
G0–G4 验收 + 第十四节验收标准表全量核对
Owner Verify + Evidence 验收
```

---

# 十三、新增：三个专项处置说明

## 13.1 memory 模块处置

`memories` 模块已实现，但按核准报告属 P2（第二阶段）能力。处置：**保留现状、冻结新功能**，不纳入本轮验收指标，不投入迭代工时。

## 13.2 quality 模块演进

现有 quality 模块（对账 / 覆盖率 / 抽验 / 重检任务）是工程化程度较高的资产。V1.1 第十五节六维 DQ（Completeness / Accuracy / Consistency / Timeliness / Uniqueness / Traceability）以**演进**方式落地：复用现有模块与 ops.tasks 任务轨道，新增六维规则注册与 DataQualityReport 批次输出，禁止另建一套质量系统。

## 13.3 worker 调度缺口

准入管线需要编排（profiling → cleaning → 标准化 → 分类 → 机器审），现 worker 只有 outbox 分发。W2/W5 在 worker 中补调度任务（沿用 ops.tasks + Redis 互斥模式，不引入新中间件）。

---

# 十四、重写：第一阶段验收标准（替换 V1.1 第二十六节）

| 项目 | 标准 |
| --- | ---: |
| 关键 Object 覆盖率 | ≥95% |
| Event 入库可靠性 | ≥99.9% |
| Event 幂等 | 100% |
| Result → Evidence | 100% |
| Decision → Evidence | 100% |
| Action 有 Owner | 100% |
| Action 有 Deadline | 100% |
| Action 有 Verify | 100%（有意较报告 ≥95% 收紧） |
| 首链路数据 OFFICIAL 覆盖率 | 100% |
| 首链路数据 A1–A4 状态机覆盖 | 100% |
| OFFICIAL 数据血缘完整率 | 100% |
| 清洗 / 标准 / 分类规则版本化 | 100% |
| 审核动作有责任人 + Audit | 100% |
| EBMS / Agent 消费非 OFFICIAL 数据 | 0 |
| 跨租户越权 | 0 |
| Agent 直接写 DB | 0 |
| EBMS 跨域直查业务表 | 0 |
| Contract Gate 通过率（含 schema CI） | 100% |
| 核心 API P95 | <2 秒 |
| 失败同步可重放 | 100% |
| 审计覆盖 | 100% |

---

# 十五、修订：Gate 机制（V1.1 第二十五节）

架构门禁 G0–G5 保留原义不变。**数据准入门禁更名**：

```text
A1 原始数据留存
A2 本系统人机共审
A3 管理系统人机复审
A4 正式归档
```

即 V1.1 第三十八节中的 G1–G4 自本版起一律称为 A1–A4，避免与架构门禁混淆。V1.1 第三十九～四十二节中的 G1/G2/G3/G4 标题与正文同步替换为 A1/A2/A3/A4，其余内容沿用。

---

# 十六、修订：治理章节（V1.1 第三十一～四十七节）

- **第三十一节**增补分期原则：第一阶段治理范围 = 首链路（销售→订单→交付→应收）关键对象（Customer / Product / Material / Order）；全对象覆盖与全量双人审为第二阶段；
- **第三十二节**主链保留，但 A1–A4 名称按第十五节替换；
- **第三十三节**增补现状映射表与 RAW 改造清单：

```text
现有资产                    → 四层归属         → 改造动作
adapters 输出（无留存）       → 无               → 新增 raw_records 表，先留存后处理
event.events / outbox        → 事件层（不动）     → 无
master.business_objects      → STANDARD 定位     → 增 official_version / lineage_id
projections 14 表            → STANDARD 投影     → 增 official_only 过滤入口
evidence.records/links       → Evidence（不动）   → 无
```

- **第三十四 / 三十五节**清洗模块与规则注册表：范围限定首链路关键对象，规则注册表字段沿用；
- **第三十六 / 三十七节**多维分类：第一阶段只建 Customer / Product / Material / Order 四个维度的最小 Taxonomy 与 Tag 集合，其余维度后移；
- **第三十八节**流程图 G1–G4 改为 A1–A4；
- **第四十节**增补执行者说明：A2/A3 在 M05–M09 自治中心建成前，由 EDP 轻量审核工作台承载——审核人以域 Owner / 管理角色账号操作，EDP 只保存审核记录与审核任务，**不实现审批流引擎**；自治中心建成后接管 A2；
- **第四十三 / 四十四节**审核结果与状态机沿用，状态变化必须产生 Event 与 Audit（保留原要求）；
- **第四十五节**血缘模型沿用，W3 落地 lineage 模块；
- **第四十六节**search_objects 排入 W5，默认 `official_only = true`（保留）；
- **第四十七节**红线增补两条：

```text
13. 已实现模块不重复建设，不推倒重建；
14. 目标管理、指标口径决策不归 EDP。
```

---

# 十七、修订：需要立即停止的事项（V1.1 第二十八节）

原 10 条保留，增补：

```text
11. 对已实现的 Decision / Action / Trace / ToolAPI / EBMS / Memory 推倒重建；
12. 在 EDP 中开发目标管理、KPI 口径管理、指标争议裁决功能；
13. 引入重型 MDM / 图谱 / 治理平台产品；
14. 在自治中心建成前实现审批流引擎；
15. 治理范围铺开到全对象全量双人审（应随闭环走）。
```

---

# 十八、修订后的阶段优先级总览

```text
数据可信（首链路） > 契约与边界 > Result / Metric / Value > 真实连接器 > 闭环验收
```

其中已实现能力（Event / Evidence / Decision / Action / Trace / ToolAPI / EBMS）以"补关联、不重建"的方式进入 W3。

**本方案 V1.2 作为 EDP 下一轮开发、整改、验收的正式执行基线。凡本文已给出的章节，以本文为准取代 V1.1 相应章节；本文未涉及的章节（方案目标、总体定位、数据脊柱、Event Contract、Result Contract、Evidence Chain、Decision/Action 边界与状态机、EBMS 接口、成熟度目标、最终目标形态与结论、审核结果标准、状态机、血缘模型、最终原则补充等）继续沿用 V1.1 原文，其中引用 V1.1 内 G1–G4 准入门禁的一律按第十五节更名为 A1–A4。**
