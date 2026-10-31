# W6 Go/No-Go 指标表（M6，EDP-034 一键导出）

- 生成时间：2026-09-22T09:36:33+00:00
- 数据源：DB（BYPASSRLS 平台全量）、deploy\loadtest\locust.json、
  deploy\drills\drill-records.json、deploy\ops-report\e2e-result.json
- 结论：全指标达标

| 指标 | 门槛 | 实测 | 判定 | 依据 |
|---|---|---|---|---|
| 业务对象覆盖度 | ≥95% | 100.0% | 达标 | quality build_coverage（平台全量） |
| 证据可追溯率（P0/P1） | =100% | 100.0%（4/4） | 达标 | 证据→事件→对象链路存在性；E2E 脚本①内嵌断言另证 |
| 重大风险召回率 | ≥80%（误报 ≤20%） | 召回 100.0%（4/4），误报 0.0%（0/4） | 达标 | 十场景回放统计（放大实体排除） |
| Action 闭环率 | ≥90% | 100.0%（1/1） | 达标 | action.actions status=VERIFIED 口径 |
| AI 越权执行 | =0 | 越权成功 0；GUARD_DENIED 拦截 3 条（全量导出） | 达标 | 越权矩阵用例集（test_security_matrix）CI 佐证 |
| Action 审计完整率 | =100% | 100.0%（action 1/1、case 1/1、record 1/1） | 达标 | 实体级审计行存在性对账 |
| 接口响应（P95） | <2s | max P95 1100ms（9 接口） | 达标 | locust 三档 VU 实测（deploy/loadtest/locust.json） |
| 租户隔离 | 100% 拒绝 | E2E 闭环 3 轮 + 隔离 3 轮全绿 | 达标 | 跨租户用例集 + E2E tenant-isolation.spec.ts |
| 高可用/备份恢复 | RTO<5min；演练通过 | switchover RTO=0s/SUCCEEDED；pitr RTO=22.1s/SUCCEEDED；tenant_restore RTO=23.8s/SUCCEEDED | 达标 | W5 演练实测（drill-records.json） |

> 一键复现：`make ops-report`（backend 环境 + 真栈 DB；口径见 `backend/scripts/ops_report.py` 模块 docstring）。
> RLS 相对开销口径见 `docs/demo/w6-loadtest.md`（相对不达标/绝对无影响，门禁采绝对口径）。
