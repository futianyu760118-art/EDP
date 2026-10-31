# W5 演练线实测读数归档

- 演练时间：2026-09-21 10:37~10:41（容器日志为 UTC 02:37~02:41）
- 拓扑基线：W4 staging 栈原地增量（etcd/patroni×2/api/worker/web 连续运行未动，`Up 3 days`），仅新增 minio/init-minio 与 pgbackrest 依赖链重建
- 相关 commit：staging-drill.md（W4 主从切换）/ 本文件 T14 段（MinIO + pgbackrest 迁 S3）

## T14 — MinIO + pgbackrest 迁 S3（EDP-031 前置）

- 改动：`deploy/docker-compose.staging.yml` 新增 minio（S3 API :19000 / console :19001，命名卷 minio-data）与 init-minio 一次性 job；`deploy/pgbackrest/pgbackrest.conf` repo1 迁 S3（W4 本地 repo 卷保留为降级预案）；新增 `deploy/scripts/init-minio.sh`（幂等建 bucket）。
- 演示凭据：`edp_minio` / 32 hex 随机密码（compose 与 pgbackrest.conf 同值，注释「演示值，生产经 secret manager」）。

### 镜像与版本（实测拉取可用）

- minio：`quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z`（digest sha256:14cea493...；镜像内含 curl/mc，healthcheck 用 `curl -fsS /minio/health/ready`）
- mc：`quay.io/minio/mc:RELEASE.2025-08-13T08-35-41Z`（`mc version RELEASE.2025-08-13T08-35-41Z`，go1.24.6）
- pgbackrest：2.59.1（自建 patroni 镜像内，未变）

### 关键实测发现：endpoint 必须带 http:// 前缀

pgbackrest 2.59.1 对 S3 默认强制 TLS——`repo1-s3-verify-ssl=n` 只跳过证书校验、不降级为明文。实测（CLI 临时 conf，不动挂载配置）：

    # endpoint=minio:9000（无 scheme）+ verify-ssl=n → 仍走 TLS：
    stanza: edp
        status: error (other)
                [ServiceError] TLS error [1:167772427] wrong version number

    # endpoint=http://minio:9000 → 明文 http，bucket 查询成功：
    stanza: edp
        status: error (missing stanza path)   # bucket 在、stanza 未建，符合预期

结论：内网 MinIO 明文方案须写 `repo1-s3-endpoint=http://minio:9000`（另需 `repo1-s3-uri-style=path`，MinIO 不支持 vhost-style）。

### 增量上栈与 bucket 初始化

`docker compose up -d minio init-minio`（未触碰既有 7 容器）；minio healthcheck 通过后 init job 输出：

    Bucket created successfully `local/edp-backups`.
    [2026-09-21 02:37:39 UTC]     0B edp-backups/

二次 up（幂等重跑，`--ignore-existing`）退出码 0。`up -d pgbackrest` 依赖链实测：minio Healthy → init-minio Exited(0) → pgbackrest 就绪。

### stanza-create（真实 conf，幂等）

~~~
2026-09-21 02:40:25.213 P00   INFO: stanza-create command begin 2.59.1: --exec-id=52375-ba0a8d53 ... --repo1-s3-endpoint=http://minio:9000 ... --repo1-type=s3 --stanza=edp
2026-09-21 02:40:25.226 P00   INFO: stanza-create for stanza 'edp' on repo1
2026-09-21 02:40:25.232 P00   INFO: stanza 'edp' already exists on repo1 and is valid
2026-09-21 02:40:25.232 P00   INFO: stanza-create command end: completed successfully (47ms)
~~~
（首次建 stanza 在验证 http:// 前缀时已完成，100ms，输出同形）

### 全量备份 → S3（实测）

`docker compose exec patroni1 pgbackrest --stanza=edp --type=full backup`：

~~~
2026-09-21 02:40:31.981 P00   INFO: backup command begin 2.59.1: ... --repo1-s3-bucket=edp-backups --repo1-s3-endpoint=http://minio:9000 ... --type=full
2026-09-21 02:40:32.009 P00   INFO: execute backup start: backup begins after the next regular checkpoint completes
2026-09-21 02:40:32.410 P00   INFO: backup start archive = 000000070000000000000009, lsn = 0/9000028
2026-09-21 02:40:41.521 P00   INFO: execute backup stop and wait for all WAL segments to archive
2026-09-21 02:40:41.597 P00   INFO: backup stop archive = 000000070000000000000009, lsn = 0/9000138
2026-09-21 02:40:41.678 P00   INFO: new backup label = 20260921-024032F
2026-09-21 02:40:41.802 P00   INFO: full backup size = 32.3MB, file total = 1565
2026-09-21 02:40:41.802 P00   INFO: backup command end: completed successfully (9902ms)
2026-09-21 02:40:41.802 P00   INFO: expire command begin 2.59.1: ...（retention-full=2）
2026-09-21 02:40:41.809 P00   INFO: expire command end: completed successfully (7ms)
~~~

- 备份集：**32.3MB / 1565 文件 / 压缩后 4.1MB**
- 执行时长：**9.9s**（pgbackrest 计时；宿主 wall clock 10.6s）
- 对比 W4 本地卷全量：同数据 32.3MB / 8.5s → S3 链路增加 ~1.4s（内网 MinIO，可接受）

### WAL 归档往返（check 实测）

~~~
2026-09-21 02:41:10.170 P00   INFO: check command begin 2.59.1: ...
2026-09-21 02:41:10.181 P00   INFO: check repo1 configuration (primary)
2026-09-21 02:41:10.205 P00   INFO: check repo1 archive for WAL (primary)
2026-09-21 02:41:10.510 P00   INFO: WAL segment 00000007000000000000000A successfully archived to '/pgbackrest/edp/archive/edp/16-1/0000000700000000/00000007000000000000000A-ae818ab023ec36367f72f011f8f871e3b2a5f660.gz' on repo1
2026-09-21 02:41:10.510 P00   INFO: check command end: completed successfully (348ms)
~~~

### pgbackrest info（repo keeper 容器，`-u postgres`）

~~~
stanza: edp
    status: ok
    cipher: none

    db (current)
        wal archive min/max (16): 000000070000000000000008/000000070000000000000009

        full backup: 20260921-024032F
            timestamp start/stop: 2026-09-21 02:40:32+00 / 2026-09-21 02:40:41+00
            wal start/stop: 000000070000000000000009 / 000000070000000000000009
            database size: 32.3MB, database backup size: 32.3MB
            repo1: backup set size: 4.1MB, backup size: 4.1MB
~~~

注：S3 repo 的 WAL 区间从 timeline 7 `...0008` 起（此前段落归档在 W4 本地 repo 卷）；PITR 基线以 S3 首个全量 20260921-024032F 为准。

### S3 对象存储读数（mc）

    $ mc du local/edp-backups
    4.8MiB	1576 objects	edp-backups
    $ mc ls local/edp-backups/pgbackrest/edp/
    [2026-09-21 02:41:27 UTC]     0B archive/
    [2026-09-21 02:41:27 UTC]     0B backup/

- 对象数：**1576**（备份集 1565 文件 + WAL/manifest 索引等）；占用 **4.8MiB**；结构 `pgbackrest/edp/{archive,backup}`
- console：宿主浏览器 http://localhost:19001（edp_minio / 演示密码）

## T15a — 备份调度 + 恢复验证任务化（EDP-031）

- 改动：`deploy/pgbackrest/backup-cron.sh`（容器内循环调度脚本）、`deploy/scripts/backup-verify.ps1`（check+抽样恢复+断言，追加式日志 `deploy/logs/backup-verify.log`，已 gitignore）、`deploy/docker-compose.staging.yml` pgbackrest 服务入口改挂脚本、`.gitignore` 增 `deploy/logs/`。
- 演练时间：2026-09-21 11:00~11:01（容器 UTC 03:00~03:01）。

### 调度机制（本地拷贝模式约束下的容器内 cron）

- 形态：pgbackrest repo keeper 容器（无状态）入口改 `/usr/local/bin/backup-cron.sh`——`while+sleep` 纯算术算距下一个 **02:00 UTC**（本地 10:00）的秒数，每日触发一次全量备份；容器内无 cron 服务，不依赖 `date -d` 解析。
- 执行路径：keeper 容器无 patroni 数据目录（本地拷贝模式备份必须在 patroni1 执行）——脚本经 `psql -h patroni1 -U edp_migrator` 用 `COPY (SELECT ...) TO PROGRAM 'pgbackrest --stanza=edp --type=full backup >> /tmp/backup-cron.log'`（superuser 同步等退出码）在数据库宿主上拉起本地备份。链路先经探针实测（keeper→psql→patroni1 落文件往返）再上栈。
- keeper 重建（`up -d pgbackrest`，仅该无状态容器）后循环存活读数：`loop mode: 每日 02:00 UTC 全量备份` / `next run in 23h3m`；主栈 7 容器 Up 3 days 零扰动。

### 调度路径实跑（--once 立即模式，2026-09-21 02:56 UTC）

    [backup-cron] backup begin: type=full exec=patroni1:local(pg1-path) via COPY TO PROGRAM
    COPY 1
    [backup-cron] backup OK: repo 最新备份集 -> full backup: 20260921-025634F

- 新备份集 **20260921-025634F**（02:56:34→02:56:43，≈9.3s，32.3MB/1565 文件/压缩 4.1MB），retention-full=2 自动保留双份（与 20260921-024032F 并存）。

### backup-verify 连续 3 次全绿（等价证据）

单次流程 = `pgbackrest check`（真实 WAL 归档往返）→ 一次性恢复容器（同 patroni 镜像，`--pg1-path=/tmp/verify` 从 S3 restore 最新备份集）→ 单用户模式（`postgres --single`）断言 `platform.tenants` 计数非零 → 拆容器。日志（`deploy/logs/backup-verify.log`，gitignore）：

    2026-09-21 11:00:24 | GREEN | check=exit:0(618ms) | restore=9.6s | tenants=1 | events=0 | GREEN
    2026-09-21 11:00:49 | GREEN | check=exit:0(970ms) | restore=9.7s | tenants=1 | events=0 | GREEN
    2026-09-21 11:01:16 | GREEN | check=exit:0(843ms) | restore=9.5s | tenants=1 | events=0 | GREEN

- 3/3 全绿：check 0.6~1.0s（pgbackrest 计时 179~372ms，含 WAL 往返）；S3 restore 9.5~9.7s（备份集 20260921-025634F）；断言 tenants=1 非零（events=0 为当时真值——业务数据尚未造，见 T15c）。
- **等价口径（用户批准）**：M5「连续 3 天」以任务化连续 N≥3 次全绿为等价证据；日历 3 天的每日调度累计读数后续补充（cron 已常驻，日志追加式可查）。
- 单用户模式侧证：恢复目录起 `postgres --single` 会走一遍 archive-get（S3 拉补 WAL）+ end-of-recovery——即断言同时覆盖「备份集可恢复 + WAL 链路可达」两级。

### 已知取舍

1. keeper 循环以 root 运行，repo 侧 `info` 需 `--allow-root`（只读不落文件）；备份本体在 patroni1 以 postgres 服务用户执行，无 root 写风险。
2. 触发口令 `edp_dev` 为演示值（compose 环境变量注入，与 deploy-staging.ps1 迁移账号同源；生产走 secret manager）。
3. 调度粒度：每日一次全量（无 incr/diff 分层），量级 32MB 下可接受；数据量增长后改 full+incr 组合（脚本 `BACKUP_TYPE` 已参数化）。

## T15b — PITR 整库恢复演练（EDP-027）

- 脚本：`deploy/scripts/pitr-drill.ps1`（七步全流程，一键真跑）；演练时间 2026-09-21 11:22~11:24（容器 UTC 03:22~03:24）。
- 读数归档：`deploy/drills/drill-records.json` pitr 项（SUCCEEDED / rto=22.1s / rpo=0s）。

### 流程与实测（脚本输出摘要）

1. **标记行**：`event.events` 插 `pitr-marker-20260921-112207`（edp_migrator BYPASSRLS；object_id 经 FK 需要 CTE 连造 `master.business_objects` marker 专用行），DB 时钟 `occurred_at=2026-09-21 03:22:07.999+00`，event_id=b40af9df-46d5-4969-8692-9db60f9b64ce。
2. **WAL 推进①**：`pg_switch_wal()` + 轮询 `pg_stat_archiver`——归档 `...001A -> ...001B`（marker 段落 S3，03:22:09）。
3. **目标时点** = marker+60s = `2026-09-21 03:23:07.999924+00:00`；睡 61s 跨过目标（窗口内无写入）。
4. **end-marker + WAL 推进②**：跨过目标后插 `pitr-marker-end-...`（commit ts > target，保证 recovery 有可停提交点）+ 再 switch——归档 `...001B -> ...001C`（03:23:12）。**end-marker 按时间点语义不应被重放——兼作负向断言**。
5. **恢复**（RTO 从冷启动计）：一次性容器 `edp-pitr-restore`（同 patroni 镜像，原生 postgres 单实例、**不走 patroni** 避免加入集群；宿主端口 15433）：

        restore OK 备份集=20260921-025634F（耗时 13.9s）
        promote 完成（到达目标时点 2026-09-21 03:23:07.999924+00:00），RTO=22.1s

6. **断言（4/4 通过）**：15433 TCP 可连；恢复库 `marker count=1`（目标前事务已重放）；`end-marker count=0`（时间点精度：目标后事务未重放）；`platform.tenants` 主库=恢复库=1。
7. **清理**：恢复容器删除；主库 marker 行（events + business_objects）清零复核。

### RTO / RPO 实测

- **RTO = 22.1s**（口径：冷启动恢复容器 → S3 restore（13.9s，备份集 20260921-025634F）→ WAL 重放至目标 → promote → 可连可断言）。
- **RPO = 0s**（目标时点前的提交零丢失：marker 行在恢复库存在）；WAL 归档覆盖余量 4.1s（最后归档 `...001C` @ 03:23:12 vs 目标 03:23:07.999）。
- 目标时点 vs marker 间隔 60s（演练参数 `TargetDelaySec`，可调）。

### 关键实测发现（踩坑记）

1. **恢复目录必须与原 pg1-path 同路径**：patroni 写入 postgresql.conf 的 `hba_file` 为绝对路径（`/var/lib/postgresql/data/pgdata/pg_hba.conf`）——恢复到任意目录（如 /tmp/verify）起原生 postgres 会 FATAL；恢复到同路径 `.../pgdata` 后正常起（T15a 单用户模式无 pg_hba 依赖故不受影响）。
2. **pgbackrest 2.59 时间点恢复用 `--target`**（与 `--type=time` 配套），`--target-time` 报 `restore command requires option: target`。
3. **宿主 15432 被常驻 edp-dev-db-1（dev 栈）占用**——不动 dev 栈，恢复实例端口改 15433（演练语义不变，脚本参数化 `param([int]$RestoreHostPort = 15433)`）。
4. PS 5.1 传参坑两则（已固化脚本注释）：`@()` 数组内跨行 `+` 不续行（拆参被 psql 忽略）；here-string 内 JSON 双引号会被剥（改 `jsonb_build_object`）。

## T15c — 租户级恢复演练（EDP-027）

- 脚本：`deploy/scripts/tenant-restore-drill.ps1`（八步一键真跑：造数→增量备份→误删→隔离恢复→COPY 回放→断言→清理；固定租户 UUID，幂等重跑）；演练时间 2026-09-21 13:11（容器 UTC 05:11）。
- 读数归档：`deploy/drills/drill-records.json` tenant_restore 项（SUCCEEDED / rto=23.8s / rpo=0s）。

### 流程与实测（脚本输出摘要）

1. **幂等清场 + demo 租户 b**：固定 UUID `b0000000-0000-4000-8000-00000000000b`（`platform.tenants` ON CONFLICT DO NOTHING，重跑安全）。
2. **造业务数据**：`master.business_objects`×12（source_system=t15c-drill）+ `event.events`×120 + `evidence.records`×40；留证计数 events=120 / evidence=40（edp_migrator BYPASSRLS 直连 patroni1）。
3. **增量备份**：`pgbackrest --type=incr` → `20260921-025634F_20260921-051115I`（05:11:15→05:11:20 UTC，5s，WAL ...0024；full+3 incr 链）。
4. **误删（RTO 计时起）**：`DELETE evidence.records/event.events WHERE tenant_id=b`（先计数留证）；误删后 0/0，`platform.tenants` 行保留（count=1）。
5. **隔离恢复**：一次性容器 `edp-tenant-restore`（同 patroni 镜像原生 postgres 单实例，宿主 :15434，不走 patroni）从 S3 restore 最新 incr 链（`--target-timeline=current`）。
6. **校验 + 回放**：隔离库计数 == 误删前（120/40）→ 容器内 `psql|psql` COPY 管道按 tenant_id 回插主库（CSV 不落宿主盘；主库行已删，UUID 直插无冲突）→ `COPY 120` / `COPY 40`。
7. **断言（RTO 计时止）**：主库计数 120/120/40 三段全等；evidence checksum 抽样 5/5 与隔离库一致；**RTO=23.8s**。
8. **清理**：恢复容器删除；租户 b 数据保留 = 演练成果。

日志（`deploy/logs/tenant-restore-drill.log`，gitignore）：

    2026-09-21 13:11:45 | b0000000-0000-4000-8000-00000000000b | events 120->120->120 | evidence 40->40->40 | checksum 5/5 | rto=23.8s | GREEN

### RTO / RPO 实测

- **RTO = 23.8s**（口径：误删 → 隔离恢复 → 回放 → 断言全过；含恢复容器冷启动 + S3 restore + 隔离实例启动 + 240 行 COPY 回放；目标 ≤4h）。
- **RPO = 0s**（整批找回：误删前/隔离库/回放后计数全等 + checksum 抽样 5/5 一致）。

### 等价口径与降级说明

1. **api 层断言 → DB 层等价**：tenant-b 成员账号/JWT 未配置，脚本以 migrator 直查 + checksum 抽样作等价断言；`api /healthz` 演练后实测 200（主栈零影响）；api 级查询断言记后续（readings 已注）。
2. **恢复实例不触主栈**：同 patroni 镜像但 `pg_ctl` 直起原生单实例（端口 15434 避开 dev 15432 / PITR 15433），不加入 patroni/etcd；主栈 8 容器（含 api/worker/web）零重启零中断。

### 关键实测发现（踩坑记）

1. **演练实例 timeline 污染（[058] 受控复现）**：恢复实例 promote 后若 archive_mode 开启，新 timeline 的 WAL/history 会回推共享 repo；后续 restore 默认 `latest` 选中该线时报 `[058] target timeline 8 forked from backup timeline 7 at 0/23000000 which is before backup lsn of 0/24000028`（开发期三次 RED 后加固；受控复现：向 repo 放入 fork 点早于最新备份的 `00000008.history` → 复现，删除后恢复）。处置：恢复实例一律 `-c archive_mode=off` + restore 显式 `--target-timeline=current`（=备份所在主线）；`pitr-drill.ps1` 同步加固（本 commit）。
2. **PS Stopwatch 无 TotalSeconds 属性**：`$sw.TotalSeconds` 静默取 `$null` → `[math]::Round` 恒 0（11:34 首次全绿 rto=0s 即此症状）；改 `.Elapsed.TotalSeconds` 后本次实测 23.8s。

## T14 结论与降级预案

1. **对象存储备份链路实测成立，未触发降级**：MinIO 起 → bucket 幂等初始化 → stanza-create → 全量备份 → WAL 推取往返（check）→ info/mc du 读数全部真跑通过；既有 7 容器（含 api/worker/web）零重启零中断。
2. **patroni 容器无需重启**：pgbackrest.conf 为只读 bind mount，宿主改写即热生效（archive_command 每次调用重读配置），S3 迁移对主从零扰动。
3. **降级预案（未触发，凭据已验在位）**：MinIO 不可用/资源不足时，将 pgbackrest.conf `[global]` 改回 `repo1-path=/pgbackrest/repo` 并删除 `repo1-type`/`repo1-s3-*` 各行（backups 卷仍挂载，W4 本地备份集实测仍在：`/pgbackrest/repo` 13M，含 20260918-002007F 全量）。
4. **已知取舍（记入后续项）**：内网明文 http（演示形态，生产走 TLS + secret manager 注入凭据）；MINIO_ROOT_USER 复用为 repo1-s3-key（生产应为独立最小权限 service account）；单副本 MinIO 无纠删码，对象存储冗余待 EDP-031 正式选型。

## T16 — HAProxy 单写入口 + switchover 复测（W4 T14 后续项）

- 改动：新增 `deploy/haproxy/haproxy.cfg`（frontend `pg` :5432 → backend `patroni_primary`；`option httpchk GET /primary` + `http-check expect status 200`；`inter 1s rise 1 fall 2`；`retries 3` + `option redispatch`；stats socket 经 compose tmpfs 可写）；compose 新增 `haproxy` 服务（`haproxy:3.0-alpine`，实测可拉取 digest `sha256:30860bc9...`，仅 compose 内网、不映射宿主端口），api/worker `EDP_DATABASE_URL` 改指 `haproxy:5432`（`depends_on: haproxy healthy`）。
- 演练时间：2026-09-21 13:22~13:24（容器 UTC 05:22~05:24）；增量上栈 `up -d haproxy` + `up -d api worker`，etcd/patroni×2/pgbackrest/minio/web 未动。
- 校验：`docker compose config` 退出码 0；`haproxy -c -f`（compose 网络内）退出码 0。

### 健康检查选主口径（实测）

    # 切换前 stats（socat show stat 摘录；截断列）
    patroni_primary,patroni1, ..., UP,   L7OK,  200   # leader
    patroni_primary,patroni2, ..., DOWN, L7STS, 503   # replica（GET /primary 503 → 摘除）

HAProxy 日志角色翻转（容器 UTC）：
- 段1（pg1→pg2，patronictl 05:22:47.256 成功）：patroni2 UP @05:22:47.861（+0.6s）→ patroni1 DOWN @05:22:48.314（+1.1s）；双 UP 重叠窗 ≈0.45s
- 段2（pg2→pg1，patronictl 05:24:22.872 成功）：patroni1 UP @05:24:22.785 → patroni2 DOWN @05:24:23.324（+0.5s）；双 UP 重叠窗 ≈0.54s

### 复测读数（W4 固定 patroni1 vs W5-T16 HAProxy）

| 读数 | W4（固定 patroni1:5432） | W5-T16（haproxy:5432） |
| --- | --- | --- |
| switchover 成功率 | 2/2（pg1→pg2→pg1） | 2/2（同往返） |
| api /healthz 探测 | 40/40 全 200（2×20×1s），0 中断 | **80/80 全 200（2×40×1s），0 中断** |
| DB 写面（新连接） | 未直接测；切换后需人工改 `DATABASE_URL` 并 recreate api/worker | **120/120 OK**（psql `SELECT pg_is_in_recovery()` → `f`，2×60×~1s）；切换窗口内单次探测最长 ≈3.6s（连接重试+重派），0 失败 |
| 自动跟随 | 否（人工改配） | 是（0 人工操作） |
| 切换后复制延迟 | lag=0，replay_lag 3.2ms | lag=0，replay_lag NULL（新会话未采样，同 W4 第二段） |
| timeline | 5 → 7 | 7 → 9 |

探测原始记录（摘录）：
- 段1 healthz：+0.3s~+39.5s 全 200（40/40）；db：+0.0~+59.0s 全 OK(f)（60/60），唯一次慢探 +7.0s 起耗时 3.6s
- 段2 healthz：+1.5s~+39.1s 全 200（40/40）；db：+0.0~+59.0s 全 OK(f)（60/60），唯一次慢探 +6.0s 起耗时 2.5s

patronictl 输出（两段，摘录）：

    段1: 2026-09-21 05:22:47.25640 Successfully switched over to "staging-pg2"
         staging-pg1 Replica stopped / staging-pg2 Leader running
    段2: 2026-09-21 05:24:22.87186 Successfully switched over to "staging-pg1"
         staging-pg1 Leader running / staging-pg2 Replica stopped

切换后角色/延迟读数：
- 段1 后：`GET :8008/primary -> 503 ; GET :8009/primary -> 200`；staging-pg2 leader TL8，staging-pg1 streaming lag=0；`pg_stat_replication`：staging-pg1 state=streaming sync=async replay_lag=NULL
- 段2 后：`GET :8008/primary -> 200 ; GET :8009/primary -> 503`；staging-pg1 leader TL9，staging-pg2 streaming lag=0；`pg_stat_replication`：staging-pg2 state=streaming sync=async replay_lag=NULL

- api 侧等价断言：api 容器内 asyncpg 经 `EDP_DATABASE_URL`（haproxy）查 `SELECT pg_is_in_recovery()` → False；`SHOW server_version` → 16.15（Debian 16.15-1.pgdg12+2）。
- worker 韧性：两段切换各 1 条 `dispatch failed ... connection is closed`（旧主 PG 重启断开池连接；05:22:49 / 05:24:24），均被循环捕获后自动恢复，`RestartCount=0` 无重启。

### 结论与降级预案

1. **单写入口成立、未触发降级**：两段 switchover 全程 0 人工配置改动；HAProxy 在新主 `GET /primary` 200 后 ≈0.6s 内回挂、旧主 2 次 503 后 ≈1.1s 摘除；新连接 120/120 零失败（慢探 1 次 3.6s 为窗口内重试/重派）。
2. **已建连接语义（如实记）**：切换时旧主 PG 重启会断开池中已建连接——worker 每段切换报 1 次 `connection is closed` 后自动恢复（asyncpg/SQLAlchemy 池重连）；`/healthz` 为无 DB 依赖探针，故 80/80 零中断不能单独证明写面，写面以上表 DB 探测为准。
3. **降级预案（本次未触发）**：haproxy 起不来/资源不足 → api/worker `EDP_DATABASE_URL` 回退 `patroni1:5432` + `up -d api worker`，恢复 W4 固定入口形态（compose 顶部注释已留痕）。
4. **后续项**：HAProxy 单点（staging 最小版）；生产形态为 HAProxy 双实例 + keepalived/VIP（或 PgBouncer 读写分离），纳入 W6+ 部署设计。
