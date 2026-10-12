# EDP 运维手册（W6 归档，EDP-035）

## 1. 拓扑

| 环境 | 拓扑 | 入口 |
|---|---|---|
| dev | Docker Compose 单库（db/api/worker/web） | api 8000（宿主占用时 override 18000）、web 9080 |
| staging | Patroni×2 + etcd + HAProxy + MinIO + pgbackrest + api/worker/web | api 18010（/healthz 探活）、web 9090、patroni restapi 8008/8009 |

部署/回滚：`powershell -File deploy/scripts/deploy-staging.ps1 -Action deploy|rollback`（HA 层→账号→迁移→应用层→健康探测，失败自动回滚）。dev：`docker compose -f deploy/docker-compose.dev.yml up -d --build`。

**staging 部署前置（W6 安全剔除后）**：创建 `deploy/.env`（gitignored，模板见 `deploy/.env.example`）提供 `MINIO_ROOT_PASSWORD`/`EDP_JWT_SECRET`——compose 无默认值，缺失将拒绝启动；密钥经 `PGBACKREST_REPO1_S3_KEY_SECRET` 环境变量注入备份链路（配置文件中不再含密钥）。

## 2. 日常操作

- **迁移**：`cd backend && uv run alembic upgrade head`（迁移账号 `edp_migrator`；发布流程=迁移先行→滚动更新 api×2→worker→web）；
- **备份**：pgbackrest 容器内 cron 每日 02:00 全量 → S3（MinIO）；手动验证 `deploy/scripts/backup-verify.ps1`（check+抽样恢复+行数断言，日志 deploy/logs/backup-verify.log）；
- **恢复演练**：PITR `deploy/scripts/pitr-drill.ps1`；租户级 `deploy/scripts/tenant-restore-drill.ps1`（读数见 w5-drills.md）；
- **试运行巡检**：`deploy/scripts/trial-patrol.ps1 -Cycles 3 -IntervalMin 30`（探活/深健康/outbox/覆盖；P0~P3 分级见 w6-trial-run.md）；
- **演示数据**：`make seed-demo`（`RESET=1` 复位；`--scale N` 压测放大；`--anchor ISO` 视觉基线固定锚）。

## 3. 监控与告警判据

- `/healthz`（无认证）：非 200 = 服务不可用（P0）；
- `/api/v1/health?deep=true`：status≠OK = P0；outbox_pending 持续增长 = worker 停摆嫌疑（P1）；
- `/api/v1/admin/outbox/status`：pending/dlq/oldest 龄；`last_published_at` 不推进 = P1；
- `/api/v1/admin/quality/coverage`：覆盖率周报数据源（≥95% 门槛）。

## 4. 故障处置表

| 症状 | 处置 |
|---|---|
| api 探活失败 | 查容器日志 → 回滚上一版镜像（deploy-staging.ps1 -Action rollback） |
| DB 主库故障 | Patroni 自动选主；HAProxy 自动跟随（W5 实测零改配）；确认 leader：`/cluster` |
| outbox 积压 | 查 worker 存活与日志；确认 DLQ（FAILED）计数；必要时重启 worker |
| 429 配额打满 | 平台面 `PATCH /tenants/{id}/quotas` 临时提额（reason 必填，审计留痕；压测先例 100→20000） |
| 慢查询 | `pg_stat_statements` top（mean_exec_time desc）；>500ms 建索引（tenant_id 前缀） |
| 任务互斥 409 TASK_CONFLICT | 同 task_type 已有任务执行中（advisory lock）；等待或查 ops.tasks RUNNING 行 |
| 全栈重启后 staging api 连库 500（haproxy 无可用后端） | haproxy 先于 patroni 就绪时健康检查卡在「Connection refused」不自动回挂（W6 跟进实测）——**重启顺序：先 patroni 节点、后 haproxy**；或对 haproxy 再执行一次 `restart`（≤10s 恢复） |

## 5. 关键约束

- 迁移失败阻断发布；契约变更走 `make contract-export` + api-sdk regen + `make contract-gate`；
- 限流/缓存为单副本进程内语义（Redis 决策终局见 redis-evaluation.md §7，不引入）；
- 备份「连续 3 天」以任务化连续 N≥3 次等价（W5-07 偏差口径）。

---

## V1.2 新增运维面（2026-10 迭代）

- **schema**：governance(11 表)/result(1)/metric(2)/value(1)；迁移 0014~0017。
- **worker**：outbox 分发与 admission 预审并发常驻（dmission_job.py，
  60s 周期；governance.auto_source_machine_review 批量 100）。单租户异常
  隔离，失败日志 edp.worker.admission。
- **权限码**：governance:read/manage、admission:review、result:read/write、
  metric:read/manage（矩阵见 rbac.py 0014~0016 注释）。
- **门禁**：schema-gate（make schema-gate，13 份域契约 Draft 2020-12
  校验）+ 既有 openapi 双门禁；verify-all 已含 schema-gate。
- **审计新增动作**：ADMISSION_REVIEW / OBJECT_OFFICIAL / OBJECT_ARCHIVED。
- **演示/验收**：	ests/integration/test_v12_*.py（治理/事实/经营/连接器/
  闭环五组）；docs/V1.2_门禁复检与验收标准核对.md（21 项核对）。
- **已知偏差**：tools official_only 过渡期开关（official_only=false）；
  CSV 通道仅 CSV（xlsx 先另存）；value ledger 复用 metric 权限轨道。
