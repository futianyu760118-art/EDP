# EDP V1.2 经营结果层设计（Phase 4：T23–T27）

> 配套方案 V1.2 第五/六节 + V1.1 第十一~十三节；契约 metric / value-ledger
> 本阶段冻结（T27）。

## 1. 范围

- T23：Metric Registry（`modules/metric`）：口径定义注册（版本化生效区间 +
  definition_owner/definition_source/target_owner 边界字段，V1.2 第五节）+ 计量值；
- T24：Period Service（`modules/period`）：AEOS 经营窗口（上月16日～当月15日）
  + 自然日/周/月/自定义/滚动7/30 天——纯函数 + 只读 API；
- T25：Value Ledger 基础版（`modules/value`）：改善前后价值事实
  （before/after/delta/evidence_refs + 人工核验）；
- T26：EBMS 指标全量走 Registry（`_latest_kpis` 改读 metric schema；前端零公式）；
- T27：冻结 contracts/metric/metric.schema.json、contracts/value/
  value-ledger.schema.json（schema-gate 11→13）。

## 2. 数据模型（迁移 0016_v12_metric_value）

- `metric.metrics`：metric_id PK / tenant_id / code（UNIQUE(tenant, code)）/
  name / business_definition / formula / source / owner / definition_owner /
  definition_source / target_owner / snapshot_policy / period_rule /
  dimension JSONB / unit / version / effective_from / effective_to + 审计
  四件套（V1.1 第十一节 + V1.2 第五节边界字段）；
- `metric.metric_values`：value_id PK / tenant_id / metric_id FK / period /
  value NUMERIC(18,4) / source / computed_at；UNIQUE(tenant, metric, period)；
- `value.value_ledger`：value_id PK / tenant_id / baseline_ref /
  initiative_ref / metric_ref / before_value / after_value / delta /
  financial_value NUMERIC(18,4) / evidence_refs UUID[] / verified_by /
  verified_at + 审计（V1.1 第十三节）；
- 全表 RLS + 授权 edp_app；权限码：metric:read → 四角色、
  metric:manage → PLATFORM_ADMIN/ADMIN（value ledger 复用 metric 轨道：
  读 metric:read、写 metric:manage——记偏差，独立 value 码 W 后评估）。

## 3. 模块与端点

```text
POST /metrics                      metric:manage   注册（新版本收旧 effective_to）
GET  /metrics                      metric:read     列表（code 过滤 + 游标分页）
POST /metrics/{id}/values          metric:manage   记计量值（period 唯一 upsert）
GET  /metrics/{id}/values          metric:read
GET  /periods/aeos                 metric:read     AEOS 当前/指定日期窗口
GET  /periods/kinds                metric:read     周期枚举（含边界说明）
POST /value-ledger                 metric:manage   创建（evidence_refs 可选）
GET  /value-ledger / {id}          metric:read
POST /value-ledger/{id}/verify     metric:manage   Human-Only 核验
```

## 4. Period 纯函数口径

- AEOS 周期：day≥16 → 周期=当月（窗口 上月16~当月15）；day<16 → 周期=上月
  （窗口 前月16~上月15）；label = `AEOS-{YYYY}-{MM}`；
- 自然周 = ISO 周（YYYY-Www）；滚动 = [date-6d, date] / [date-29d, date]。

## 5. demo seed 扩展 + EBMS 切换

- seed 在 management 段后同事务镜像 metric.metrics（owner 域映射：
  on_time_delivery/inventory_turnover→DELIVERY、risk_closure_rate→MANAGEMENT；
  definition_source=DOMAIN、target_owner=M01_KERNEL）+ metric.metric_values
  （同 MGMT_KPI_VALUES 值/期）；
- ebms `_latest_kpis` 改读 metric schema（响应形状不变：code/name/value/
  unit/period）；management.* 保留供 objectives 与既有兼容；
- purge 增 metric/value 段（先 values 后 metrics；value_ledger 独立）。

## 6. 测试

- 单元：period 纯函数（15/16 日边界、ISO 周、滚动窗）；
- 集成：metric 注册/版本化/计量值 upsert；seed 后 ebms reports kpis 来自
  registry（值与既有断言一致）；value ledger 创建/核验/权限矩阵；
  analyst metric:manage 403；
- 回归：test_ebms/test_ebms_reports/test_demo_seed 全绿（seed 双写）；
  全量 backend-test 不降（基线 706）。

## 7. 出口条件

EBMS 指标 100% 引用 Registry；AEOS 周期聚合正确（单元断言）；metric/value
契约冻结入 CI（schema-gate 13/13）。
