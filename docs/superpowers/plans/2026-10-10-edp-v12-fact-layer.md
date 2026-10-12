# EDP V1.2 事实与结果层实施计划（Phase 3：T17–T22）

Spec: docs/superpowers/specs/2026-10-10-edp-v12-fact-layer-design.md
Branch: feat/v12-governance（续用）

| Task | 内容 | 验证 |
| --- | --- | --- |
| T1（0015迁移） | result schema + 3 表 ALTER（result_refs）+ business_objects 三列 + governance.lineage + 2 权限码 | 一次性容器全周期 exit 0 |
| T2（T17） | result 模块（models/schemas/service/dependencies/router + main 挂载） | 集成：无证据 400 / 有证据 201 + RESULT links / 列表 / 详情 |
| T3（T17） | verify 端点（Human-Only） | 集成：verify 落库 + SERVICE 403 |
| T4（T20） | lineage 模块（写入口 + 读 API，复用 governance:read） | 集成：OFFICIAL 转换产生 lineage 行 + 查询 |
| T5（T19） | 治理服务 OFFICIAL/ARCHIVED 回写 business_objects 三列 + OBJECT_OFFICIAL/ARCHIVED 审计 | 集成：三列回写 + 审计行 |
| T6（T21） | tools 7 端点 official_only（默认 true） | 集成：默认空 / 审核后可见 / false 全量；既有用例显式 false 适配 |
| T7（T22） | contracts/decision|action|trace 三份 schema + README 补目录 | schema-gate 11/11 |
| T8（收口） | 契约导出 + SDK regen + rbac/测试计数同步（26→28）+ 全量回归 + 台账 | verify-all 等价全绿；backend-test ≥ 702 + 新增 |

依赖：T1 → T2/T4 → T3/T5/T6 → T7 → T8
