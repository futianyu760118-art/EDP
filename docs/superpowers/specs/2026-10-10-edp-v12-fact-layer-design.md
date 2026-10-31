# EDP V1.2 事实与结果层设计（Phase 3：T17–T22）

> 配套方案 V1.2 第九节/第十节；契约 contracts/result/result.schema.json、
> contracts/governance/lineage.schema.json（T02 已冻结）+ 本阶段冻结
> contracts/decision|action|trace/*.schema.json（T22）。

## 1. 范围

- T17：`result` 独立模块（迁移 + API + 证据关联 + verify）；
- T18：decisions/actions/traces 增 result_refs（evidence 已有 links RESULT 机制）；
- T19：business_objects 增 layer_status / official_version / lineage_id，
  OFFICIAL/ARCHIVED 转换时回写；
- T20：lineage 模块（写入口 = 准入 OFFICIAL 转换；读 API）；
- T21：tools（Agent Tool API）全端点 official_only（默认 true）；
- T22：冻结 decision/action/trace 域契约（对账导出自现有代码形状）。

## 2. 数据模型（迁移 0015_v12_fact_layer）

- `result.results`（新 schema result，RLS + 授权 edp_app）：result_id PK /
  tenant_id / result_type / object_id FK business_objects / domain /
  period / metric_refs JSONB DEFAULT '[]' / value JSONB / status TEXT /
  source_refs JSONB DEFAULT '[]' / evidence_refs UUID[] DEFAULT '{}' /
  generated_by / generated_at / verified_status / verified_by /
  verified_at / version / created_at / updated_at / created_by /
  updated_by；索引 (tenant_id, result_type, generated_at DESC)。
- ALTER decision.cases / action.actions / trace.traces ADD result_refs
  UUID[] NOT NULL DEFAULT '{}'（evidence 经 links ref_type=RESULT，无列变更）。
- ALTER master.business_objects ADD layer_status TEXT NULL CHECK IN
  ('RAW','CLEAN','STANDARD','CURATED','ARCHIVED')、official_version TEXT
  NULL、lineage_id UUID NULL（FINAL=official_version 指针语义：存
  admission_id 文本）。
- `governance.lineage`（契约 lineage.schema.json 逐字段）+ RLS。
- 权限码：result:read → PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST；
  result:write → PLATFORM_ADMIN/ADMIN/MANAGER（SERVICE 走 readonly /
  write:result scope 轨道）。

## 3. result 模块

```text
POST /results             result:write   创建（evidence_refs 必填非空——Result→
                                          Evidence 100% 验收硬约束；ensure RESULT
                                          links + 对象存在性校验）
GET  /results             result:read    result_type/status 过滤 + 游标分页
GET  /results/{id}        result:read    详情 + evidence 投影
POST /results/{id}/verify result:write   Human-Only 核验（verified_* 落库；
                                          evidence 存在性重校验）
```

无 Evidence 的 Result 不得创建（400 VALIDATION_ERROR）——"先数据可信再进入经营闭环"。

## 4. OFFICIAL 转换回写（T19/T20，治理服务扩展）

management_review APPROVED 路径（MANAGEMENT_APPROVED → OFFICIAL）后：
1. lineage 行写入（source_record_id=对象 source_id、source_review_ref/
   management_review_ref=最新 review_id、official_version=admission 版本）；
2. business_objects 回写 layer_status='OFFICIAL'、official_version=
   str(admission_id)、lineage_id=lineage 行 id（纯 SQL UPDATE + 显式
   OBJECT_OFFICIAL 审计——切面对 raw SQL 不可见）；
3. archive：layer_status='ARCHIVED' 回写（同审计口径 OBJECT_ARCHIVED）。

## 5. tools official_only（T21）

- 7 端点增 query 参数 `official_only`（缺省 true）：对象须满足
  master.business_objects.layer_status IN ('OFFICIAL','ARCHIVED')；
- 详情端点未命中 official → 404（Agent 读不到非 OFFICIAL 数据，与不存在同义）；
- 列表端点仅返回 official 对象子集；official_only=false 为过渡期开关
  （既有测试/演练显式传 false，记偏差，Phase 6 UAT 收口为全 OFFICIAL）。

## 6. T22 契约对账导出

contracts/decision/decision-record.schema.json、action/action-record.schema.json、
trace/trace.schema.json 以现有 pydantic schemas（decisions/actions/traces
schemas.py）+ ORM 列为唯一事实来源逐字段对账导出，不反向改代码语义。

## 7. 测试

- 集成：result 创建（无证据 400 / 有证据 201 + RESULT links）/ verify /
  权限矩阵 / OFFICIAL 回写（business_objects 三列 + lineage 行 + 审计）/
  tools official_only 门禁（默认空 + 审核后可见 + false 全量）；
- 迁移：0015 全周期 upgrade→downgrade→upgrade；
- 回归：既有 tools/m3/m4 用例显式 official_only=false 适配（记偏差）；
  全量 backend-test 不降（基线 702）。

## 8. 出口条件

Result→Evidence 100%（创建硬约束）；Decision→Action→Result→Evidence 全链
可查询（result_refs + links）；Agent 读不到非 OFFICIAL 数据（tools 门禁）；
decision/action/trace 契约冻结入 CI（schema-gate）。
