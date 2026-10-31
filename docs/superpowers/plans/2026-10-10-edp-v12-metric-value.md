# EDP V1.2 经营结果层实施计划（Phase 4：T23–T27）

Spec: docs/superpowers/specs/2026-10-10-edp-v12-metric-value-design.md
Branch: feat/v12-governance（续用）

| Task | 内容 | 验证 |
| --- | --- | --- |
| T1（0016迁移） | metric schema 2 表 + value schema 1 表 + RLS + 2 权限码 | 容器全周期 exit 0 |
| T2（T24） | period 模块（纯函数 + /periods/aeos + /periods/kinds） | 单元：15/16 边界 + API |
| T3（T23） | metric 模块（注册/版本化/计量值） | 集成：版本化生效区间 + upsert |
| T4（T25） | value 模块（创建/核验） | 集成：创建 + Human-Only 核验 |
| T5（T26） | demo seed 双写 metric + ebms _latest_kpis 切 registry | 集成：ebms kpis 与既有断言一致 |
| T6（T27） | contracts/metric + value 两份 schema + README | schema-gate 13/13 |
| T7（收口） | 契约导出 + SDK regen + rbac 计数（28→30）+ 全量回归 + 台账 | backend-test ≥ 706 + 新增 |

依赖：T1 → T2/T3/T4 → T5/T6 → T7
