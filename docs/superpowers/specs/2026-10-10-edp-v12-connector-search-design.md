# EDP V1.2 连接器与多维查询设计（Phase 5 无外部依赖部分）

> 配套方案 V1.2 第六节收缩范围；T28/T29（真实 ERP/MES 连接器）依赖 T03
> 外部对接资源（字段清单/接口文档），本阶段不实施，留待对接；T31 真实数据
> 准入以 Excel/CSV 通道（T30）先行验证。

## 1. 范围

- T30：Excel/CSV 导入通道——`POST /admin/ingest/file`（multipart CSV 模板
  校验 → RAW → 管道全链）；模板列 object_type/source_id/occurred_at + 其余
  列=payload 字段；
- T32：worker 调度——admission 机器预审编排任务（CLASSIFIED → SOURCE_REVIEW
  自动推进：PASS/WARNING 推进、FAIL 留态 + DataQuality.Exception）；API
  source_review 兼容 SOURCE_REVIEW 起态（跳过内联复检）；
- T33：search_objects 多维查询——object_tags 挂接表（0017）+ 标签挂接 API
  + tools search-objects（object_type/classification/dimension/tag/
  official_only 过滤）；
- T34：tools 全端点回归（official_only 门禁 + 新增 search-objects）。

## 2. 数据模型（迁移 0017_v12_object_tags）

governance.object_tags：object_tag_id PK / tenant_id / object_id FK
business_objects / tag_id FK governance.tags / created_at/by；
UNIQUE(tenant_id, object_id, tag_id) + RLS + 授权。

## 3. 端点

```text
POST /admin/ingest/file              adapters:write    CSV 导入（≤1000 行）
POST /governance/object-tags         governance:manage 标签挂接
GET  /governance/object-tags         governance:read
GET  /tools/search-objects           tools:read        object_type/classification/
                                                       dimension/tag/official_only
```

## 4. worker 调度（T32）

outbox 循环旁挂 admission_job：每 60s 对每活跃租户执行
`governance.auto_source_machine_review(batch=100)`（PASS/WARNING 推进
SOURCE_REVIEW + machine_result 落库；FAIL 留 CLASSIFIED + DQ 事件）。
事务边界：逐租户独立会话/事务；异常隔离（单租户失败不致死循环）。

## 5. 测试

- 集成：CSV 导入（模板校验 400 / 正常导入 RAW+管道全链 / 幂等重导）；
  object-tags 挂接 + search-objects 各过滤组合 + official_only；
  auto_source_machine_review（PASS 推进 / FAIL 阻断 + DQ 事件）；
- 回归：tools 全端点 + 全量 backend-test 不降（基线 718）。

## 6. 出口条件

CSV 历史数据可入 RAW 并跑通管道（A1 语义）；CLASSIFIED 可由 worker 自动
预审推进；search_objects 支持四维过滤且默认 official_only。
