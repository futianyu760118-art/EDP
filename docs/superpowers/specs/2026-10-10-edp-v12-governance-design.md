# EDP V1.2 治理最小闭环设计（Phase 2：T08–T16）

> 本设计为 EDP V1.2 迭代 Phase 2（治理最小闭环）的实施规格，对应方案
> `docs/AEOS_企业数据与证据中台_EDP_迭代版总体方案_V1.2.md` 与行动计划
> T08–T16。契约见 `contracts/governance/*.schema.json`（T02 已冻结）。
> 设计文档：`docs/V1.2_A1-A4准入状态机设计.md`、`docs/V1.2_清洗规则与分类维度设计.md`、
> `docs/V1.2_四层模型映射表.md`。

## 1. 范围与红线

- 范围：RAW 留存（T08）→ 清洗引擎（T09/T10）→ 实体解析（T11）→ 分类/标签（T12）→
  A2/A3 审核（T13/T14）→ 准入状态机落地（T15）→ 质量门禁（T16）；仅首链路关键对象。
- 红线：RAW 不可覆盖；已实现模块不重建；EDP 只存审核任务与记录，不实现审批流引擎；
  所有状态变化产生 Event + Audit；未 OFFICIAL 数据不进消费面（T21 属 Phase 3，不在本阶段）。

## 2. 数据模型（迁移 0014）

单次迁移 `0014_v12_governance_baseline.py`（versions/platform/，风格同 0013），
新建 schema `governance`，10 张表全 RLS（tenant_isolation）+ 授权 edp_app：

| 表 | 关键列 | 说明 |
| --- | --- | --- |
| raw_records | raw_record_id PK / tenant_id / source_system / source_record_id / object_type / source_timestamp / raw_payload JSONB / received_at / batch_id / checksum / schema_version / created_at | RAW 层；UNIQUE(tenant_id, source_system, source_record_id, source_timestamp) + ON CONFLICT DO NOTHING 幂等；索引 (tenant_id, object_type, received_at) |
| clean_records | clean_record_id PK / tenant_id / object_id / raw_record_id / before JSONB / after JSONB / rule_refs JSONB / executed_at / confidence / created_at | CLEAN 留痕（fixAudit） |
| cleaning_rules | rule_id PK / tenant_id / rule_name / object_type / field / rule_type CHECK(10 值) / condition / transformation / severity CHECK / owner / version / effective_from / effective_to / auto_fix / review_required + 审计四件套 | 契约 cleaning-rule.schema.json |
| entity_aliases | alias_id PK / tenant_id / object_type / alias / canonical_ref UUID / source / confidence / approved_by / approved_at + 审计四件套 | UNIQUE(tenant_id, object_type, alias) |
| dimensions | dimension_id PK / tenant_id / code / name + 审计 | UNIQUE(tenant_id, code) |
| taxonomies | taxonomy_id PK / tenant_id / dimension_id / parent_id / label + 审计 | 分类树 |
| tags | tag_id PK / tenant_id / code / name + 审计 | UNIQUE(tenant_id, code) |
| object_classifications | classification_id PK / tenant_id / object_id / dimension_id / taxonomy_id / label / source CHECK(3 值) / rule_ref / confidence / version / effective_from / effective_to / approved_by / approved_at + 审计 | 契约 classification.schema.json |
| admission_records | 见 `docs/V1.2_A1-A4准入状态机设计.md` 第二节草案 | 状态机 15 态 CHECK + review_result 6 值 CHECK；UNIQUE(tenant_id, object_id)；乐观锁 version |
| review_records | review_id PK / tenant_id / admission_id / stage CHECK(SOURCE_REVIEW|MANAGEMENT_REVIEW) / machine_result JSONB / human_decision CHECK(6 值) / human_reviewer / comment / reviewed_at / evidence_refs UUID[] + 审计 | 审核留痕 |

权限码（uuid5 命名空间同 0012/0013）：

```text
governance:read   → PLATFORM_ADMIN / ADMIN / MANAGER / ANALYST
governance:manage → PLATFORM_ADMIN / ADMIN
admission:review  → PLATFORM_ADMIN / ADMIN / MANAGER
```

## 3. 状态机（T15）

15 态与转移表照抄 `contracts/governance/admission-state.schema.json`
definitions.transitions（单一事实来源）。服务层 TRANSITIONS dict 同 actions
模块模式；非法转移 → 409 CONFLICT（extra.allowed_to）。

阶段一推进方式（无 worker 调度，同步管线）：

```text
process_record 内：RAW 落库(RECEIVED) → 清洗执行(→CLEANED) → 对象 upsert+投影
(→STANDARDIZED) → 分类挂接(→CLASSIFIED)；admission 行创建/推进随同一事务。
SOURCE_REVIEW 起由人工 API 驱动（T13/T14）。
```

状态推进事件：`governance.admission.{State}`（复用 events.ingest_batch
internal=True 写通道，actor=service:governance）；**事件口径（实施裁定，偏离
§3 初稿）：同步管线段（RECEIVED→CLASSIFIED）不产生状态事件**——记录级审计
由审计切面自动留痕（admission 行 ORM 写入），避免 5 事件/记录污染既有
SNAPSHOT 事件计数基线与对账口径；事件自人工审核段（SOURCE_REVIEW 起）产生。
审核动作审计 AUDIT_ADMISSION_REVIEW（record_explicit）。

## 4. ingest 管道改造（T08/T09）

process_record 增加（保持既有三元组/幂等/对账逻辑不变）：

1. **RAW 留存**：入口先 INSERT governance.raw_records（ON CONFLICT DO NOTHING；
   checksum = evidence_service.compute_checksum(payload)；batch_id 缺省 NULL）；
   幂等命中（rowcount=0）不阻断既有流程（RAW 已有该版本）。
2. **清洗执行**：`governance.cleaning.apply(sess, tenant_id, object_type, payload)`
   → (cleaned_payload, fixes)。初始无规则 = 恒等变换，**既有 400+ 测试零影响**；
   每条应用规则写 clean_records 留痕。cleaned_payload 用于对象 upsert 与投影，
   evidence 快照仍存原始 payload（证据=源快照）。
3. **admission 推进**：create/advance 至 CLASSIFIED（见 §3）。

对账口径不变（三计数齐等）；新增 RAW 计数仅展示（governance 查询面）。

## 5. 治理模块 API（T10–T15，`modules/governance`）

```text
POST   /governance/cleaning-rules          gov:manage   规则注册（版本 +1 覆盖旧生效区间）
GET    /governance/cleaning-rules          gov:read     列表（object_type 过滤 + 游标分页）
POST   /governance/entity-aliases          gov:manage   别名注册（approval 由 manage 承担）
GET    /governance/entity-aliases          gov:read
POST   /governance/dimensions|taxonomies|tags   gov:manage
GET    /governance/dimensions|taxonomies|tags   gov:read
POST   /governance/object-classifications  gov:manage   挂分类（source=HUMAN_MAINTAINED/RULE_BASED）
GET    /governance/classifications?object_id=  gov:read
GET    /governance/raw-records             gov:read     RAW 只读（含 checksum；不可改）
GET    /admission                          gov:read     列表（state 过滤 + 游标分页）
GET    /admission/{id}                     gov:read     详情 + review 记录
POST   /admission/{id}/source-review       admission:review  A2：机器预审执行 + 人工 decision
POST   /admission/{id}/management-review   admission:review  A3：机器复审执行 + 人工 decision
POST   /admission/{id}/archive             admission:review  A4：OFFICIAL→ARCHIVED
```

Human-Only 守卫：review/archive 端点 principal.kind != HUMAN → 复用
decisions.record_guard_denied 模式落 GUARD_DENIED 审计 + 403。

## 6. A2/A3 机器检查（T13/T14，最小可执行版）

A2（SOURCE_REVIEW 入口执行）：完整性（payload 关键字段非空）、格式（已注册
FORMAT 类规则有无违规）、重复（同 source_record_id 历史计数）、业务规则
（RANGE/REFERENTIAL/BUSINESS_RULE 违规清单）、主数据匹配（order.customer_code
命中 master.customers）、分类/标签（是否存在 classification）、quality_score
（100 起点，逐项扣分）。输出 PASS/WARNING/FAIL + exception_list + suggested_fix。

A3（MANAGEMENT_REVIEW 入口执行）：跨系统一致性（订单 customer 存在 + 交付
窗口 ≥ 今天 + BOM 引用物料存在）、Evidence 完整性（该对象 evidence.records
计数 ≥1）、历史合理性（occurred_at ≤ now）。

FAIL → 写 `DataQuality.Exception` 事件（T16 门禁），状态禁止推进到 APPROVED；
WARNING 允许人工裁决推进（APPROVED_WITH_WARNING）。

## 7. 测试策略

- 迁移：upgrade→downgrade→upgrade 全周期（一次性容器）；
- 单元：状态机转移表、清洗引擎各 rule_type、质量评分纯函数；
- 集成：RAW 幂等（重放 raw 行数不增）、管道端到端（raw→clean→admission
  CLASSIFIED）、A2/A3 端点全链（RECEIVED→ARCHIVED）、Human-Only 守卫、
  越权矩阵（governance:read/manage、admission:review 三码）、跨租户 404/403。

## 8. 出口条件（Phase 2）

mock 订单数据集 100% 走完 RECEIVED → ARCHIVED（demo 脚本可演）；血缘要素
（raw/clean/rule/审核记录）可查询；既有测试全绿（backend-test 不降）；契约
指纹不变（无 openapi 变更？新增路由会变更 openapi → 重导出 + SDK regen 在
收口任务做，指纹顺延）。
