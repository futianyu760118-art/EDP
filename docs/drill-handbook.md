# EDP 演练手册（W6 汇编，EDP-035）

> 三演练实测读数原文：`docs/demo/w5-drills.md`（W5 实测）、`docs/demo/staging-drill.md`（W4 switchover）；
> 记录数据源：`deploy/drills/drill-records.json`（`GET /admin/drills` 只读 API；前端演练回放页）。

## 1. 前置检查单（通用）

- [ ] staging 栈健康：`deploy-staging.ps1 -Action deploy` 完成且 `/healthz` 200；
- [ ] Patroni leader 可确认（8008/8009 restapi `/cluster`）；
- [ ] pgbackrest 最近全量备份成功（容器内 `pgbackrest info`）；
- [ ] 演练窗口内无其他压测/试运行任务；读数与结论**实测归档，不虚报**。

## 2. 主从切换（switchover）

- 命令：`deploy-staging.ps1 -Action drill`（Patroni switchover + 中断/lag 读数）；
- 通过判据：双向切换成功；api 经 HAProxy 自动跟随（W5 实测：healthz 80/80 零中断，写面 120/120 经代理）；
- 读数归档：staging-drill.md + drill-records.json（`rto_seconds=0` 为 healthz 零中断口径，DB 写面 3.6s 见 readings）。

## 3. PITR 整库恢复

- 命令：`deploy/scripts/pitr-drill.ps1`（标记行写入 → 全量+WAL → 目标时点恢复新实例 → 断言）；
- 通过判据：标记行存在 + 对账复跑一致；W5 实测 RTO=22.1s / RPO=0s（目标 ≤2h / ≤5min）；
- 注意：`-target-timeline=current` + 演练后 `archive_mode=off` 加固（W5 经验）。

## 4. 租户级恢复

- 命令：`deploy/scripts/tenant-restore-drill.ps1`（模拟误删 → 按 tenant_id 逻辑导出 → 隔离库校验 → 回放）；
- 通过判据：行数/checksum 抽样全对；W5 实测 RTO=23.8s（目标 ≤4h）。

## 5. 记录维护

演练完成后回填 `deploy/drills/drill-records.json`（drill_type/executed_at/topology/rto/rpo/result/readings/manual_url），
前端演练回放页与 W6 运营报告（HA 指标）自动消费；新增演练类型须同步 `quality/service.py` 读取口径与前端卡片。
