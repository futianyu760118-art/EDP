# EDP V1.2 治理最小闭环实施计划（Phase 2：T08–T16）

Spec: docs/superpowers/specs/2026-10-10-edp-v12-governance-design.md
方案: docs/AEOS_企业数据与证据中台_EDP_迭代版总体方案_V1.2.md
Branch: feat/v12-governance（自 master 切出）
约定：每任务独立提交；契约 openapi 变更集中到收口任务（T09 收口重导出 + SDK regen）。

## 任务表

| Task | 内容 | 验证 |
| --- | --- | --- |
| T1（对应 T08） | 0014 迁移：governance schema + 10 表 + RLS + 3 权限码 | 一次性容器 upgrade→downgrade→upgrade exit 0；表/索引/策略存在性 SQL 断言 |
| T2（T08） | ingest RAW 留存：process_record 入口落 raw_records（checksum/幂等） | 集成测试：重放 raw 行数不增；checksum 与 evidence 一致；既有测试全绿 |
| T3（T08/T09） | governance 模块骨架 + cleaning 引擎 + clean_records 留痕；ingest 接清洗 | 单元：各 rule_type 恒等/修复/违规；管道 cleaned_payload 生效而证据存原 payload |
| T4（T10） | cleaning_rules 注册 API（POST/GET + 版本化生效区间） | 集成：注册→管道应用→留痕可查；越权 403 |
| T5（T11） | entity_aliases API + 清洗引擎 ENTITY_RESOLUTION 接别名归一 | 集成："宁波恒剑光电"类样例归一 + 别名保留 |
| T6（T12） | dimensions/taxonomies/tags API + object_classifications 挂接 API | 集成：四维度最小树 + 挂接/查询 |
| T7（T15） | admission 模块：状态机服务 + 列表/详情 + 管道推进至 CLASSIFIED | 单元：TRANSITIONS 全对/错边 409；集成：管道后 admission=CLASSIFIED |
| T8（T13） | A2 source-review：机器预审 + 人工 decision（Human-Only） | 集成：PASS/FAIL 推进路径 + GUARD_DENIED 审计 |
| T9（T14） | A3 management-review + T16 门禁：FAIL→DataQuality.Exception 事件阻断 | 集成：OFFICIAL 达成 + FAIL 阻断 + 异常事件落库 |
| T10（T14/T15） | A4 archive + OFFICIAL→ARCHIVED 收尾 | 集成：全链 RECEIVED→ARCHIVED |
| T11（收口） | demo 脚本（治理全链演示）+ 契约重导出 + SDK regen + verify-all + 台账 | make verify-all 全绿；缺口清单更新 |

## 依赖顺序

T1 → T2 → T3 →（T4/T5/T6 并行）→ T7 → T8 → T9 → T10 → T11

## 评审约定

每任务完成后独立评审（对照 spec + 契约逐字段核对），评审意见以新提交修复；
整分支终审在 T11 后执行。测试基线：backend-test 当前全量 ≈700（W6 收口 695+），
目标 Phase 2 收口 ≥ 780。
