# EDP 生产部署设计（W6 留档，二期实施，W5-06 缺口延续）

> 状态：**仅设计文档，不实施**。范围：HAProxy 生产形态、prod 试运行窗口、staging→prod 差异清单。

## 1. HAProxy 双实例 + keepalived/VIP

```
        VIP 10.x.x.x:5432 (keepalived)
        ├── haproxy-a (MASTER, priority 150) ──┐
        └── haproxy-b (BACKUP, priority 100)   │  健康检查 8008 /primary 选主
                                               ▼
                    Patroni 集群（pg1 leader / pg2 replica / ...）
```

- 每台 haproxy 实例配置与 staging 相同（`deploy/haproxy/haproxy.cfg`：5432→主库、`option httpchk GET /primary`）；
- keepalived：VRRP 抢占式，MASTER 故障时 VIP 漂移至 BACKUP；两实例互为备份（staging 当前单实例为最小版，W5-04 已登记）；
- 应用侧 `EDP_DATABASE_URL` 指 VIP，天然跟随选主（W5 已实测零改配跟随）；
- 读写分离（PgBouncer/replica 读）作为后续优化项，不在一期。

## 2. prod 试运行窗口建议

- 环境：独立 prod 拓扑（同构 staging，独立 PG 卷 + 独立对象存储桶）；
- 窗口：≥1 周观察期；每日 `trial-patrol.ps1`（30min 周期）+ 每周 `backup-verify`；
- 门控：连续 3 天 0 P0/0 P1 + 备份可恢复性连续通过 → 转正式运行；
- 缺陷分级沿用 `docs/demo/w6-trial-run.md` 协议（P0~P3）。

## 3. staging → prod 差异清单

| 项 | staging | prod 要求 |
|---|---|---|
| DB 写入口 | HAProxy 单实例 | 双实例 + keepalived/VIP |
| 密钥 | compose 演示值（EDP_JWT_SECRET 64+ 字符） | secret manager 注入（禁止仓库明文） |
| 对象存储 | MinIO 单实例 | 生产对象存储（S3 兼容，独立桶 + 生命周期） |
| 备份 | 每日全量 + 手动 verify | 每日全量 + WAL 归档 + 每日自动 verify + 异地副本 |
| 限流/缓存 | 进程内单副本 | 视 QPS 决策（Redis 重启触发条件见 redis-evaluation.md §7） |
| 副本数 | api×1 | api×2 滚动更新（发布流程见 ops-runbook） |
| 监控 | trial-patrol 瞬时探测 | 持续告警栈（Prometheus/Grafana 类） |
| 试运行 | staging 兼任（W5-06 偏差） | 独立 prod 试运行窗口（本文件 §2） |
