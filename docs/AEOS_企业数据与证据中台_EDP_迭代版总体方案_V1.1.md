# AEOS 企业数据与证据中台 EDP 迭代版总体方案 V1.1

**上位框架：** AEOS V7.2  
**中台编号：** M02  
**建议正式名称：** AEOS Enterprise Data & Evidence Platform  
**中文名称：** AEOS 企业数据与证据中台  
**工程简称：** EDP / Data Foundation  
**方案版本：** V1.1  
**目标版本阶段：** 从当前 L2.5～L3 迭代至 L4  
**建设原则：** 不推倒重做、沿用现有技术栈、清洗优先、标准化、多维分类、双层人机审核、先数据可信再进入经营闭环

---

# 一、方案目标

本轮迭代不再把 EDP 定义为传统“数据平台”，而是正式升级为：

> **AEOS 全系统统一的企业事实、事件、结果、证据、审计与价值数据底座。**

EDP 不负责替代 ERP、MES、CRM、PLM，也不负责替代 EBMS 或 Agent 中枢。

EDP 的核心任务只有一个：

> **让企业中每一个重要经营事实、变化、判断、行动和结果，都有统一对象、统一事件、统一结果、统一证据，并可被 EBMS、Agent 和各自治中心可靠调用。**

---

# 二、迭代后的总体定位

AEOS V7.2 中的系统关系调整为：

```text
                          AEOS V7.2
                              │
                  ┌───────────┴───────────┐
                  │                       │
              M01 Kernel               M03 EBMS
         权限/目标/Guard/Agent       经营结果与决策工作面
                  │                       │
                  └───────────┬───────────┘
                              │
                        M02 EDP
              Enterprise Data & Evidence
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
     Fact/Object           Event                Evidence
        │                     │                     │
        └─────────────── Result / Value ───────────┘
                              │
              API / Event / Tool / Contract
                              │
      ┌───────────┬───────────┼───────────┬───────────┐
      │           │           │           │           │
     销售        研发        交付        品质        财经
     M05         M04         M06         M08         M09
```

EDP 是“中间事实层”，不是“超级业务系统”。

---

# 三、核心设计原则

本轮迭代冻结八条原则。

第一，**数据有 Owner，EDP 不抢业务所有权。**

例如客户由销售自治中心负责，BOM 由研发自治中心负责，交付事实由交付自治中心负责，财务事实由财经自治中心负责。

EDP 负责保存：

- Object 引用
- Event
- Result
- Evidence
- Audit
- Metric Value
- Value Ledger
- Trace

第二，**跨系统不能直接写表。**

统一采用：

```text
API
Event
Result
Evidence
```

进行交互。

第三，**EBMS 不直接拼业务系统数据库。**

EBMS 原则上只读取：

```text
Result
Metric
Exception
Decision
Action
Evidence
```

第四，**Agent 不允许自由访问数据库。**

必须通过：

```text
Agent
  ↓
Tool API
  ↓
Guard
  ↓
EDP
```

第五，**所有关键结果必须有证据。**

没有 Evidence 的 Result 不得作为正式经营事实。

第六，**代码完成不等于业务完成。**

必须完成：

```text
Fact
→ Event
→ Decision
→ Action
→ Result
→ Verify
→ Evidence
```

才视为闭环完成。

第七，**第一阶段坚持模块化单体。**

暂不为了“先进”过早拆微服务。

第八，**优先闭环，后做规模化。**

先跑通一条完整业务链，再复制到其他领域。

---

# 四、新版核心数据脊柱

本轮迭代最重要的变化，是正式建立 AEOS 数据脊柱。

## 4.1 一级核心对象

```text
BusinessObject
Event
Result
Evidence
DecisionCase
Decision
Action
Verification
Trace
Metric
Value
```

完整关系：

```text
BusinessObject
      │
      ▼
    Event
      │
      ▼
DecisionCase
      │
      ▼
  Decision
      │
      ▼
   Action
      │
      ▼
Execution
      │
      ▼
   Result
      │
      ▼
Verification
      │
      ▼
 Evidence
      │
      ▼
   Trace
```

Goal 和 KPI 则通过：

```text
Goal
 ↓
Metric
 ↓
Result
 ↓
Variance
 ↓
DecisionCase
```

进入经营自治闭环。

---

# 五、Object Contract 迭代

所有正式业务对象统一至少包含：

```text
tenant_id
object_id
object_type
source_system
source_object_id
revision
status
owner_domain
occurred_at
created_at
updated_at
```

建议增加：

```text
schema_version
correlation_id
trace_id
confidence
data_quality_status
```

EDP 不复制全部业务系统字段。

EDP 保存的是：

> 标识 + 必要事实 + 引用 + 快照 + 证据。

这样避免中台重新成为“第二数据库”。

---

# 六、Event Contract 迭代

统一事件结构：

```text
event_id
event_type
tenant_id
object_ref
source_system
occurred_at
received_at
correlation_id
causation_id
schema_version
payload
evidence_refs
trace_id
```

事件名称统一采用：

```text
Domain.Object.Action
```

例如：

```text
Sales.Order.Created
Sales.Order.Confirmed
Delivery.Material.ShortageDetected
Quality.Inspection.Failed
Finance.AR.Overdue
RD.BOM.Released
```

事件禁止使用：

```text
event_01
update_data
status_changed
```

这种没有业务语义的名称。

---

# 七、Result Contract——本轮重点新增

Result 是本轮迭代的核心。

各自治中心不应该把内部表直接暴露给 EBMS。

必须输出标准 Result。

建议统一结构：

```text
result_id
result_type
tenant_id
object_ref
domain
period
metric_refs
value
status
source_refs
evidence_refs
generated_by
generated_at
verified_status
verified_by
verified_at
version
```

示例：

```text
result_type:
Delivery.OrderDeliveryRisk

object_ref:
Order/2026-10025

status:
HIGH_RISK

value:
{
  "delay_days": 7,
  "shortage_items": 4
}

evidence_refs:
[
  material-shortage-evidence,
  capacity-evidence
]
```

EBMS 读取的是 Result，而不是 MRP 内部几十张表。

---

# 八、Evidence Chain 迭代

证据链升级为正式一级能力。

要求实现：

```text
Result
 ↓
Evidence
 ↓
Source Snapshot
 ↓
Source Record
 ↓
Source System
```

同时 Decision 和 Action 也必须具有 Evidence。

形成：

```text
Decision
 ├─ evidence_refs
 ├─ result_refs
 └─ trace_id
```

```text
Action
 ├─ decision_ref
 ├─ owner
 ├─ deadline
 ├─ verification_rule
 └─ evidence_refs
```

Evidence 建议增加：

```text
checksum
source_version
source_timestamp
captured_at
confidence
retention_policy
```

---

# 九、Decision 与 Action 的边界

Decision 的规则由 AEOS Kernel / DEH 控制。

EDP 负责：

> **存储 Decision 事实、Action 事实和证据，不负责自主产生最终管理决策。**

推荐关系：

```text
M01 / DEH
负责：
Decision Logic
Guard
Approval
Human-in-the-loop

M02 EDP
负责：
Decision Record
Action Record
Evidence
Trace
Result
```

这样可以避免 EDP 越来越像工作流系统。

---

# 十、Action 模块

Action 建议采用标准状态机：

```text
CREATED
 ↓
ASSIGNED
 ↓
ACCEPTED
 ↓
IN_PROGRESS
 ↓
COMPLETED
 ↓
VERIFYING
 ↓
VERIFIED
 ↓
CLOSED
```

异常分支：

```text
BLOCKED
REJECTED
CANCELLED
ESCALATED
```

每个 Action 必须具备：

```text
action_id
decision_ref
owner
owner_role
deadline
priority
status
expected_result
verification_rule
actual_result_ref
evidence_refs
created_at
completed_at
verified_at
```

没有 Owner、Deadline、Verification 的 Action 不允许成为正式任务。

---

# 十一、Metric Registry 迭代

增加统一指标注册中心。

解决目前最常见的问题：

> 销售额、准交率、毛利率、库存金额，在不同系统里算法不一样。

统一 Metric 定义：

```text
metric_id
metric_name
business_definition
formula
source
owner
period_rule
dimension
unit
version
effective_from
effective_to
```

例如：

```text
metric_id:
OTD_RATE

definition:
按承诺日期计算的准时交付订单比例

owner:
Delivery

period:
AEOS Operating Window
```

所有 EBMS 指标必须引用 Metric Registry。

禁止在前端临时写公式。

---

# 十二、AEOS经营时间窗口

EDP 必须原生支持 AEOS 经营周期：

> **上月16日 ～ 当月15日**

同时支持：

```text
自然日
自然周
自然月
AEOS周期
自定义周期
滚动7天
滚动30天
```

时间维度不能硬编码在 EBMS 页面里。

统一由 EDP Period Service 提供。

---

# 十三、Value Ledger 新增

为了支持未来“按结果收费”和外部企业价值评定，本轮建议建立 Value Ledger 基础版。

统一记录：

```text
value_id
tenant_id
baseline_ref
initiative_ref
metric_ref
before_value
after_value
delta
financial_value
evidence_refs
verified_by
verified_at
```

例如：

```text
改善前库存：
8,500,000

改善后库存：
6,900,000

释放资金：
1,600,000

Evidence：
库存账龄报告
ERP快照
财务确认
```

这会成为 AEOS 后续对外服务商业模式的重要基础。

---

# 十四、Adapter 架构迭代

现有 Adapter 框架保留。

统一升级成：

```text
Source Connector
      ↓
Raw Record
      ↓
Normalizer
      ↓
Business Object Mapper
      ↓
Event Generator
      ↓
Evidence Capture
      ↓
EDP
```

第一阶段 Connector 优先级：

1. ERP
2. MES
3. PLM
4. CRM
5. 品质系统
6. 财务系统
7. Excel / CSV
8. 外部 API

所有 Connector 都必须实现统一接口：

```text
connect()
healthcheck()
pull()
normalize()
checkpoint()
retry()
replay()
```

---

# 十五、数据质量模块

增加独立 Data Quality。

至少检测：

```text
Completeness
Accuracy
Consistency
Timeliness
Uniqueness
Traceability
```

每批同步生成：

```text
DataQualityReport
```

示例：

```text
订单总数：1058
成功同步：1053
失败：5
覆盖率：99.53%
重复：0
孤儿对象：2
延迟记录：3
```

低于门禁自动产生：

```text
DataQuality.Exception
```

---

# 十六、Agent Tool API

增加专门面向 Agent 的只读数据层。

不要允许 Agent 自由执行 SQL。

建议提供结构化工具：

```text
get_order()
get_customer()
get_product()
get_delivery_risk()
get_quality_issues()
get_ar_status()
get_metric()
get_result()
get_evidence()
search_business_objects()
```

所有调用形成：

```text
Agent Trace
```

---

# 十七、Agent Trace

Trace 建议成为正式模块。

统一记录：

```text
trace_id
tenant_id
agent_id
session_id
goal_ref
input_refs
tool_calls
result_refs
decision_refs
action_refs
evidence_refs
started_at
completed_at
status
```

工具调用进一步记录：

```text
tool_name
arguments
authorization
result
duration
error
timestamp
```

未来所有 AI 判断必须能解释：

> 谁调用了什么工具、读取了哪些事实、最后基于哪些 Evidence 得到什么结果。

---

# 十八、EBMS 数据接口重构

EBMS 与 EDP 的接口建议标准化为六类：

```text
GET /results
GET /metrics
GET /exceptions
GET /decisions
GET /actions
GET /evidence
```

EBMS 首页不再从各系统分别取数据。

推荐：

```text
EBMS
 ↓
Management Query API
 ↓
EDP Result Layer
 ↓
各自治中心
```

这样 EBMS 才是真正的“管理工作面”。

---

# 十九、前端控制台定位

EDP 控制台继续保留，但只面向：

- 平台管理员
- 数据管理员
- 系统管理员
- 集成工程师
- 数据治理人员

主要页面建议收敛为：

```text
运营总览
数据源
业务对象
事件
结果
证据
指标
数据质量
Connector
Audit
Trace
Tenant
System Registry
```

不建议 EDP 控制台增加：

- 销售经营驾驶舱
- 财务驾驶舱
- 生产驾驶舱
- CEO经营驾驶舱

这些应该属于 EBMS 或专业自治中心。

---

# 二十、新版模块结构

建议最终后端模块形成：

```text
backend/apps/api/edp_api/modules/
│
├── platform
├── tenantmgmt
├── registry
├── ingest
├── events
├── evidence
├── result
├── metric
├── value
├── audit
├── trace
│
├── decision_record
├── action_record
│
├── quality
├── adapters_admin
│
├── toolapi
└── ebms_api
```

同时：

```text
backend/packages/
│
├── adapters
├── contracts
├── common
└── sdk
```

注意：

Decision 与 Action 在 EDP 中是 **Record 模块**。

决策规则、审批和 Guard 不放进 EDP。

---

# 二十一、Contract Pack 迭代

现有：

```text
contracts/openapi.json
```

升级为：

```text
contracts/
│
├── object/
│   └── business-object.schema.json
│
├── event/
│   └── event.schema.json
│
├── result/
│   └── result.schema.json
│
├── evidence/
│   └── evidence.schema.json
│
├── decision/
│   └── decision-record.schema.json
│
├── action/
│   └── action-record.schema.json
│
├── trace/
│   └── trace.schema.json
│
├── metric/
│   └── metric.schema.json
│
├── value/
│   └── value-ledger.schema.json
│
└── openapi/
```

所有 Contract 必须进入 CI Gate。

---

# 二十二、第一条正式业务闭环

本轮迭代禁止同时开发六个自治中心。

第一条完整链路固定为：

> **销售 → 订单 → 交付 → 应收**

场景：

```text
Sales.Order.Confirmed
        ↓
EDP Event
        ↓
交付检查
        ↓
Delivery Risk Result
        ↓
DecisionCase
        ↓
Decision
        ↓
Action
        ↓
执行
        ↓
Delivery Result
        ↓
Shipment
        ↓
Finance.AR
        ↓
Cash Result
        ↓
Evidence
```

至少跑通以下异常：

```text
物料缺料
产能不足
交期风险
品质异常
出货延期
应收逾期
```

---

# 二十三、轻版 / 重版设计

延续 AEOS 双版本策略。

## 轻版

用于快速验证：

```text
Mock Connector
PostgreSQL
Modular Monolith
Outbox
基础 Event
基础 Result
基础 Evidence
基础 Action
基础 EBMS API
```

不引入：

```text
Kafka
Lakehouse
K8s
复杂实时计算
向量数据库集群
大型 MDM 产品
```

目标：

> 快速证明 AEOS 闭环有效。

---

## 重版

在轻版证明有效后逐步增加：

```text
CDC
Event Bus
MQ
Lakehouse
Vector Store
Streaming
复杂 DQ
HA
PITR
Observability
高级租户治理
跨企业数据空间
```

重版不得反过来拖慢轻版验证。

---

# 二十四、6周迭代计划

## W1：边界与契约冻结

完成：

```text
System Boundary
Data Ownership
Object Contract
Event Contract
Result Contract
Evidence Contract
```

Gate：

**G0 / G1**

---

## W2：Result + Evidence

新增：

```text
result module
result API
evidence chain
verification
```

验收：

```text
Result → Evidence
100%可追溯
```

---

## W3：Decision / Action / Trace

增加：

```text
Decision Record
Action Record
Action State Machine
Trace
```

验收：

```text
Decision → Action → Result
```

可以完整追踪。

---

## W4：Metric + EBMS API

增加：

```text
Metric Registry
Period Service
EBMS Query API
```

打通：

```text
EDP → EBMS
```

---

## W5：Agent Tool + Connector

完成：

```text
Agent Tool API
ERP Adapter
MES Adapter
CRM Adapter
```

Agent 只能通过 Tool API 读取正式数据。

---

## W6：经营闭环验收

完成：

```text
销售
→订单
→交付
→应收
```

完整 UAT。

同时完成：

```text
Gate
Evidence
Owner Verify
```

---

# 二十五、Gate机制

## G0 — 架构门禁

检查：

```text
边界
Owner
数据所有权
禁止跨域写表
```

---

## G1 — Contract门禁

检查：

```text
Object
API
Event
Result
Evidence
```

---

## G2 — Data门禁

检查：

```text
数据完整性
时效
一致性
追溯
```

---

## G3 — Closed Loop门禁

检查：

```text
Decision
Action
Result
Verify
Evidence
```

---

## G4 — Agent/EBMS门禁

检查：

```text
EBMS可用
Agent可用
Guard有效
Trace完整
```

---

## G5 — Self Evolution

后续阶段：

```text
Memory
Skill
经验沉淀
自动优化
```

---

# 二十六、第一阶段验收标准

EDP 进入 L4 必须至少满足：

| 项目                |     标准 |
| ----------------- | -----: |
| 关键Object覆盖率       |   ≥95% |
| Event入库可靠性        | ≥99.9% |
| Event幂等           |   100% |
| Result→Evidence   |   100% |
| Decision→Evidence |   100% |
| Action有Owner      |   100% |
| Action有Deadline   |   100% |
| Action有Verify     |   100% |
| 跨租户越权             |      0 |
| Agent直接写DB        |      0 |
| EBMS跨域直查          |      0 |
| Contract Gate通过率  |   100% |
| 核心API P95         |    <2秒 |
| 失败同步可重放           |   100% |
| 审计覆盖              |   100% |

---

# 二十七、迭代后的成熟度目标

当前：

```text
L2.5 ～ L3
```

本轮目标：

```text
L4
```

定义：

```text
L0 数据散落
L1 数据接入
L2 数据统一
L3 Event + Evidence
L4 Decision + Action + Result闭环
L5 Agent自治
L6 Memory + Skill + Self-Evolution
```

本轮明确：

> **不直接追 L5/L6。**

先把 L4 做扎实。

---

# 二十八、需要立即停止的事项

本轮迭代期间建议暂缓：

1. 大量新增 EDP 页面；
2. 为展示效果增加重复 Dashboard；
3. 提前建设 Kafka；
4. 提前引入复杂 Lakehouse；
5. EDP 自己实现 ERP/CRM 功能；
6. Agent 直接访问数据库；
7. EBMS 直接访问业务系统内部表；
8. 没有 Contract 就增加跨系统接口；
9. 没有 Evidence 就发布经营指标；
10. 为每个场景单独写一套临时代码。

---

# 二十九、最终目标形态

本轮完成后，EDP 应形成如下能力：

```text
                AEOS Data Foundation
                        │
      ┌─────────────────┼─────────────────┐
      │                 │                 │
 Business Objects     Events           Metrics
      │                 │                 │
      └────────────┬────┴─────┬──────────┘
                   │          │
                Results    Evidence
                   │          │
                   └────┬─────┘
                        │
               Decision Records
                        │
                  Action Records
                        │
                     Trace
                        │
               Value / Verification
                        │
        ┌───────────────┼───────────────┐
        │               │               │
      EBMS            Agent         自治中心
```

这才是 AEOS 数据中台真正应该成为的样子。

---

# 三十、最终结论

本轮 EDP 不需要重新选型，也不需要大规模重构。

正确路线是：

> **保留现有技术底座，收紧系统边界，补齐 Result / Decision Record / Action Record / Trace / Metric / Value 六个关键能力，把现有 Object + Event + Evidence 基础打成一条真实经营闭环。**

完成本轮后，EDP 将从：

> **“数据与事件平台”**

正式升级成：

> **“AEOS 企业事实、结果与证据基础设施”。**

并具备支撑：

```text
EBMS
+
专业自治中心
+
岗位微系统
+
Agent
+
未来跨企业复制
```

的统一数据基础。

**本方案建议作为 EDP 下一轮开发、整改、验收的正式执行基线。**


---

# 三十一、V1.1 新增：数据治理总原则

V1.1 将“数据清洗、标准化、多维分类、审核准入、归档”提升为 EDP 一级核心能力。

EDP 的数据治理主原则正式冻结为：

> **Clean → Standardize → Classify → Source Review → Management Review → Archive → Serve → Automate**

中文解释：

> **先清洗 → 再标准化 → 再多维分类 → 本系统人机共审 → 管理系统人机共审 → 正式归档 → 数据服务 → 自动化/自治。**

任何尚未完成上述准入流程的数据，不得作为 AEOS 正式经营事实提供给 EBMS、Agent、Metric、Result、Decision 使用。

---

# 三十二、V1.1 新增：企业数据处理主链

EDP 数据处理主链升级为：

```text
Enterprise Sources
ERP / MES / CRM / PLM / Finance / Quality / Excel / API / Device
                           │
                           ▼
                    Data Acquisition
                           │
                           ▼
                       RAW Zone
                           │
                           ▼
                   Data Profiling
                           │
                           ▼
                    Data Cleaning
                           │
                           ▼
                  Standardization
                           │
                           ▼
                 Entity Resolution
                           │
                           ▼
             Classification / Taxonomy
                           │
                           ▼
                     Tag Engine
                           │
                           ▼
              Source System Review
                  Machine + Human
                           │
                           ▼
             Management System Review
                  Machine + Human
                           │
                           ▼
                  OFFICIAL Fact
                           │
                           ▼
                      Archive
                           │
                           ▼
        Object / Event / Metric / Result / Evidence
                           │
             EBMS / Agent / Autonomous Centers
```

原则：

1. 原始数据必须先留存后处理；
2. 清洗不得覆盖 RAW；
3. 标准化规则必须版本化；
4. 分类和标签必须可追溯；
5. 正式数据必须经过两级人机共审；
6. 未归档数据不得成为企业正式事实。

---

# 三十三、V1.1 新增：RAW / CLEAN / STANDARD / CURATED 四层数据模型

EDP 将数据处理层正式划分为四层：

## 33.1 RAW

保存源系统原始数据，原则上永久不可修改。

至少记录：

```text
source_system
source_record_id
source_timestamp
raw_payload
received_at
batch_id
checksum
schema_version
```

## 33.2 CLEAN

用于纠错、去重、缺失处理、格式修复和异常处理。

不得覆盖 RAW，只能产生新版本。

## 33.3 STANDARD

完成统一编码、单位、币种、名称、日期、主数据映射、实体识别后的标准数据。

## 33.4 CURATED / OFFICIAL

完成分类、标签、本系统审核、管理系统审核后形成的正式企业事实。

只有 CURATED / OFFICIAL 层允许被：

```text
EBMS
Agent
Metric
Result
Decision
Action
Value
```

正式消费。

---

# 三十四、V1.1 新增：Data Cleaning 数据清洗模块

新增一级模块：

```text
data_profiling
data_cleaning
standardization
entity_resolution
classification
tagging
data_quality
```

清洗能力至少覆盖：

- 空值检测与处理；
- 重复数据识别；
- 格式统一；
- 日期标准化；
- 编码标准化；
- 名称标准化；
- 单位换算；
- 币种标准化；
- 异常值识别；
- 别名/错别字映射；
- 字段类型纠正；
- 主外键孤儿识别；
- 业务规则校验；
- 历史脏数据修复；
- 多源冲突识别与处理。

典型实体解析示例：

```text
宁波恒剑光电
宁波恒剑光电科技有限公司
恒剑光电
HJGD
        ↓
Entity Resolution
        ↓
Canonical Entity
        ↓
宁波恒剑光电科技有限公司
```

别名必须保留，不得直接删除历史来源值。

---

# 三十五、V1.1 新增：Data Cleaning Rule Registry

建立统一数据清洗规则中心。

标准字段：

```text
rule_id
rule_name
object_type
field
rule_type
condition
transformation
severity
owner
version
effective_from
effective_to
auto_fix
review_required
```

规则类型至少包括：

```text
FORMAT
NORMALIZATION
DEDUPLICATION
MAPPING
RANGE_CHECK
REFERENTIAL_CHECK
BUSINESS_RULE
UNIT_CONVERSION
CURRENCY_NORMALIZATION
ENTITY_RESOLUTION
```

所有自动修复必须记录：

```text
before_value
after_value
rule_id
rule_version
executed_at
confidence
```

---

# 三十六、V1.1 新增：多维分类体系

EDP 不再只按 Sales / Delivery / Quality / Finance / R&D 等业务域分类。

正式采用：

> **Dimension + Taxonomy + Tag**

三层分类体系。

## 36.1 Dimension

稳定分析维度至少包括：

```text
Customer
Product
Material
Supplier
Region
Channel
Organization
Time
Finance
Risk
Quality
Lifecycle
Project
Order
```

## 36.2 Taxonomy

每个维度允许建立结构化分类树。

例如：

```text
Product
├─ Lighting
│  ├─ Work Light
│  │  ├─ Magnetic Work Light
│  │  ├─ Inspection Light
│  │  └─ Headlamp
│  └─ Outdoor Light
```

## 36.3 Tag

动态标签用于表达跨维度、变化快的状态。

例如：

```text
high-risk
new-customer
new-product
late-delivery
high-margin
low-margin
slow-moving
quality-alert
cash-risk
```

同一个对象可同时具备多个维度和多个标签。

订单示例：

```text
Order A
├─ 客户维度：战略客户
├─ 地区维度：北美
├─ 产品维度：工作灯
├─ 渠道维度：Amazon
├─ 金额维度：大额订单
├─ 风险维度：高风险
├─ 毛利维度：低毛利
├─ 交付维度：延期风险
├─ 生命周期：新客户首单
└─ 时间维度：AEOS-P10
```

---

# 三十七、V1.1 新增：分类治理标准

分类来源分为三类：

```text
Rule-based
Human-maintained
AI-assisted
```

正式主数据分类必须有业务 Owner。

AI 只能：

```text
AI Suggest
   ↓
Confidence
   ↓
Rule Validation / Human Review
   ↓
Official Classification
```

AI 不允许直接修改：

- 战略客户等级；
- 合格供应商等级；
- 财务科目；
- 产品正式分类；
- 品质正式等级；
- 重大风险正式状态。

分类必须支持版本：

```text
classification_id
dimension_id
taxonomy_id
object_ref
label
source
rule_ref
confidence
version
effective_from
effective_to
approved_by
approved_at
```

---

# 三十八、V1.1 新增：AEOS 企业数据准入与归档流程

正式定义：

> **AEOS Data Admission & Archive Pipeline**

中文名称：

> **AEOS 企业数据准入与归档流程**

主流程：

```text
数据获取
  ↓
G1 原始数据留存
  ↓
数据画像
  ↓
数据清洗
  ↓
标准化
  ↓
多维分类/标签
  ↓
G2 本系统机器预审
  ↓
G2 本系统人工审核
  ↓
G3 管理系统机器复审
  ↓
G3 管理系统人工确认
  ↓
OFFICIAL
  ↓
G4 最终归档
```

---

# 三十九、V1.1 新增：G1 数据获取与原始留存标准

数据来源包括：

- ERP；
- MES；
- CRM；
- PLM；
- 财务系统；
- 品质系统；
- Excel / CSV；
- 外部 API；
- 设备数据；
- 人工录入。

G1 原则：

> **先完整获取，后处理；原始数据永久保留，不允许先修改后落库。**

初始状态：

```text
RECEIVED
```

G1 输出必须包括：

```text
source_system
source_record_id
source_timestamp
raw_payload
received_at
checksum
batch_id
```

---

# 四十、V1.1 新增：G2 本系统人机共审

“本系统”指数据来源所属专业自治系统。

例如：

```text
销售数据 → M05 销售自治中心
研发数据 → M04 研发自治中心
交付数据 → M06 交付自治中心
品质数据 → M08 品控自治中心
财务数据 → M09 财经自治中心
```

机器预审至少检查：

- 完整性；
- 格式；
- 字段类型；
- 重复；
- 异常值；
- 业务规则；
- 主数据匹配；
- 分类与标签；
- 数据质量分数。

机器输出：

```text
PASS
WARNING
FAIL
quality_score
confidence
exception_list
suggested_fix
```

人工负责确认：

- 数据是否符合真实业务；
- 异常是否合理；
- 机器修改建议是否接受；
- 分类是否正确；
- 是否允许进入企业管理层审核。

状态：

```text
SOURCE_PENDING_REVIEW
SOURCE_APPROVED
SOURCE_REJECTED
SOURCE_RETURNED
SOURCE_ESCALATED
```

只有 SOURCE_APPROVED 才能进入 G3。

---

# 四十一、V1.1 新增：G3 管理系统人机共审

管理系统审核不得简单重复专业系统审核。

其职责是站在企业整体角度进行复核。

机器复审重点：

- 跨系统一致性；
- 指标口径一致性；
- 时间窗口一致性；
- Business Object 关联；
- 跨域冲突；
- Evidence 完整性；
- 历史合理性；
- 经营规则；
- 权限与合规。

例如：

```text
销售系统：订单已完成
        ↓
管理系统复审
        ├─ 是否已发货
        ├─ 品质是否放行
        ├─ 是否已开票
        ├─ 是否形成应收
        └─ Evidence 是否齐全
```

G3 判断的是：

> **该数据是否有资格成为“企业正式事实”。**

状态：

```text
MANAGEMENT_PENDING_REVIEW
MANAGEMENT_APPROVED
MANAGEMENT_REJECTED
MANAGEMENT_RETURNED
MANAGEMENT_ESCALATED
```

只有 MANAGEMENT_APPROVED 才允许转为 OFFICIAL。

---

# 四十二、V1.1 新增：G4 正式归档

通过 G2 与 G3 后的数据进入：

```text
OFFICIAL
   ↓
ARCHIVED
```

归档记录至少包括：

```text
archive_id
object_id
source_system
source_record_id

raw_version
clean_version
standard_version
classification_version

source_machine_result
source_human_reviewer
source_reviewed_at

management_machine_result
management_human_reviewer
management_reviewed_at

dimensions
classifications
tags
quality_score

evidence_refs
checksum
version
archived_at
```

正式归档后形成 AEOS 可消费的企业事实版本。

---

# 四十三、V1.1 新增：数据审核结果标准

两级审核统一支持六种结果：

```text
APPROVED
APPROVED_WITH_WARNING
RETURN_FOR_CORRECTION
REJECTED
SUSPENDED
ESCALATED
```

含义：

- APPROVED：正式通过；
- APPROVED_WITH_WARNING：允许继续流转，但保留非关键异常；
- RETURN_FOR_CORRECTION：退回修正；
- REJECTED：数据不接受进入正式链路；
- SUSPENDED：暂缓等待外部信息或证据；
- ESCALATED：升级至更高责任人处理。

---

# 四十四、V1.1 新增：数据准入状态机

正式状态机：

```text
RECEIVED
   ↓
PROFILED
   ↓
CLEANED
   ↓
STANDARDIZED
   ↓
CLASSIFIED
   ↓
SOURCE_REVIEW
   ↓
SOURCE_APPROVED
   ↓
MANAGEMENT_REVIEW
   ↓
MANAGEMENT_APPROVED
   ↓
OFFICIAL
   ↓
ARCHIVED
```

异常状态：

```text
RETURNED
REJECTED
SUSPENDED
ESCALATED
```

任何状态变化必须产生 Event 和 Audit。

---

# 四十五、V1.1 新增：数据血缘与可追溯性

每条正式数据必须能够追溯：

```text
Source
 ↓
Raw Record
 ↓
Cleaning Rule
 ↓
Standardization Rule
 ↓
Entity Resolution
 ↓
Classification Rule
 ↓
Source Review
 ↓
Management Review
 ↓
Official Version
 ↓
Archive
```

建议统一记录：

```text
lineage_id
source_record_id
transformation_id
cleaning_rule_version
standardization_rule_version
classification_version
source_review_ref
management_review_ref
official_version
timestamp
operator
```

这样必须能够回答：

- 数据从哪里来；
- 为什么被修改；
- 哪条规则修改；
- 为什么被这样分类；
- 谁审核；
- 哪个版本成为正式事实；
- 哪些 Result / Decision 使用过该数据。

---

# 四十六、V1.1 新增：面向 Agent 的多维数据查询能力

Tool API 除对象查询外，增加多维查询模型：

```text
search_objects(
  dimensions = {},
  classifications = [],
  tags = [],
  time_range = {},
  official_only = true
)
```

典型管理问题：

> 最近三个月，新客户、低毛利、高延期风险、订单金额超过20万的订单有哪些？

应通过：

```text
时间维度
+
客户生命周期分类
+
毛利分类
+
风险标签
+
订单金额
```

完成查询，而不是让 Agent 自由生成 SQL。

默认仅允许读取 OFFICIAL / ARCHIVED 数据。

---

# 四十七、V1.1 新增：必须冻结的数据治理红线

1. RAW 原始数据禁止覆盖；
2. 未清洗的数据不得进入正式 Metric；
3. 未标准化的数据不得进入跨系统比较；
4. 未分类的数据不得作为企业多维分析正式输入；
5. 未完成本系统审核的数据不得进入管理系统审核；
6. 未完成管理系统审核的数据不得成为 OFFICIAL；
7. 未归档数据不得作为关键经营决策正式 Evidence；
8. AI 不得直接修改正式主数据分类；
9. 清洗规则、标准规则、分类规则必须版本化；
10. 每条正式事实必须具有完整 Lineage 和 Evidence；
11. 所有审核动作必须有责任人和 Audit；
12. EBMS 与 Agent 默认仅消费 OFFICIAL / ARCHIVED 数据。

---

# 四十八、V1.1 调整后的阶段优先级

原 W1/W2 优先级调整。

## W1：数据治理基线

```text
Data Source Inventory
Data Ownership
Data Profiling
Cleaning Rule Registry
Standard Dictionary
Dimension Model
Taxonomy Model
Object Contract
```

## W2：清洗、标准化与分类

```text
RAW → CLEAN → STANDARD
Entity Resolution
Master Mapping
Classification
Tagging
Data Quality
Source Review
Management Review
Archive
```

## W3：企业事实与事件

```text
Official Business Object
Event
Evidence
Lineage
Audit
```

## W4：经营结果层

```text
Metric
Result
EBMS API
Period Service
```

## W5：决策执行层

```text
Decision Record
Action Record
Trace
Agent Tool API
```

## W6：闭环验收

```text
销售
→订单
→交付
→应收
→双层审核
→归档
→Result
→Decision
→Action
→Evidence
```

---

# 四十九、V1.1 最终原则补充

企业数据中台不是“把所有数据集中起来”。

真正目标是：

> **把来源不同、质量不同、口径不同的数据，经过清洗、标准化、实体解析、多维分类和双层人机审核，变成可信、可追溯、可复用、可归档的企业正式事实。**

AEOS 后续的：

```text
Metric
Result
Evidence
Decision
Action
Agent
Skill
Value
```

全部必须建立在这些正式企业事实之上。

因此 EDP 的建设优先级正式调整为：

> **数据可信 > 数据流动 > 数据分析 > 决策闭环 > Agent 自治。**
