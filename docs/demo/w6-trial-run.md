# W6 试运行记录（EDP-035，M6 出口）

| 项 | 内容 |
|---|---|
| 日期 | 2026-09-22 |
| 环境 | staging 同构栈（`deploy-staging.ps1 -Action deploy`）：Patroni×2 + etcd + HAProxy + MinIO + pgbackrest + api(18010) + worker + web(9090)；leader=staging-pg1 |
| 数据 | `seed --reset` 基线十场景（43 对象 / 53 事件 / 53 证据，案例已建） |
| 巡检 | `deploy/scripts/trial-patrol.ps1 -Cycles 3 -IntervalMin 2`（协议缺省 30min/周期，见偏差登记） |
| 结论 | **连续 3/3 周期 0 P0/0 P1 → 等价收口**（W5「连续 3 天」先例口径） |

## 1. 缺陷分级协议（P0~P3）

| 级别 | 判据 | 处置 |
|---|---|---|
| P0 | 服务不可用（探活失败）/ 数据丢失 / 安全越权 | 立即修复并重新计数 |
| P1 | 核心接口 5xx / 功能不可用 / outbox 积压单调增长（worker 停摆嫌疑） | 修复后重新计数 |
| P2 | 次要端点异常 / 体验缺陷 | 登记，不影响等价收口 |
| P3 | 改进建议 | 登记 |

## 2. 巡检项与判据（脚本 `deploy/scripts/trial-patrol.ps1`）

1. `GET /healthz`（无认证探活）——非 200 = P0；
2. `GET /api/v1/health?deep=true`——HTTP 非 200 = P1；`status != OK` = P0；
3. `GET /api/v1/admin/outbox/status`——HTTP 非 200 = P1；`pending_count` 跨周期单调增长 = P1；
4. `GET /api/v1/admin/quality/coverage`——HTTP 非 200 = P2；
5. worker 推进——有积压且 `last_published_at` 不推进 = P1。

每周期一行 TSV 追加 `deploy/logs/trial-run.log`（日志按 W5 惯例 gitignore；本文档为归档读数）。

## 3. 实测读数（3 周期）

| 周期 | healthz | health?deep | outbox pending | last_published_at | coverage | 判定 |
|---|---|---|---|---|---|---|
| 1（16:21:28） | 200 / 57ms | 200 / OK / 117ms | 0 | 2026-09-22T08:16:28Z | 200 / 76ms | OK |
| 2（16:23:28） | 200 / 18ms | 200 / OK / 59ms | 0 | 2026-09-22T08:16:28Z | 200 / 28ms | OK |
| 3（16:25:29） | 200 / 20ms | 200 / OK / 44ms | 0 | 2026-09-22T08:16:28Z | 200 / 21ms | OK |

汇总行：`clean=3/3; verdicts=OK,OK,OK; verdict=PASS`（16:25:29）。

## 4. 缺陷登记

| # | 级别 | 描述 | 处置 |
|---|---|---|---|
| — | — | 无 P0/P1/P2/P3 平台缺陷 | — |

（准备期插曲：巡检脚本首跑因 PS 5.1 `[string]$Body=$null` 转空串致 GET 带空 body 报错——工具缺陷，修复后正式执行，不计平台缺陷。）

## 5. 偏差登记

1. **「≥3 天」以连续 N≥3 巡检周期等价**（spec §10.1）：协议缺省 30min/周期；收口窗口以 2min 间隔连跑 3 周期为等价证据（W5「连续 3 天」备份验证先例）；日历 3 天后续由常驻巡检自然累计；
2. **试运行环境 = staging 兼任**（W5-06 延续）：prod 环境搭建与真实试运行窗口留二期（`docs/prod-deploy-design.md` 设计稿）；
3. **巡检粒度**：周期内为瞬时探测（非持续监控），异常窗口短于探测间隔时可能漏检；告警栈（Prometheus 类）留二期。
