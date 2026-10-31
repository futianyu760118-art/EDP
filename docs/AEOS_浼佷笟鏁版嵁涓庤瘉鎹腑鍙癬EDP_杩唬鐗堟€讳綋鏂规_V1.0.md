# AEOS 企业数据与证据中台 EDP 迭代版总体方案 V1.0

**上位框架：** AEOS V7.2  
**中台编号：** M02  
**建议正式名称：** AEOS Enterprise Data & Evidence Platform  
**中文名称：** AEOS 企业数据与证据中台  
**工程简称：** EDP / Data Foundation  
**方案版本：** V1.0  
**目标版本阶段：** 从当前 L2.5～L3 迭代至 L4  
**建设原则：** 不推倒重做、沿用现有技术栈、优先补齐契约和经营闭环

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
