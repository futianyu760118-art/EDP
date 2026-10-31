# staging 主从切换演练记录（EDP-021 / T14）

- 演练时间：2026-09-18 08:19:22
- 演练命令：powershell -File deploy/scripts/deploy-staging.ps1 -Action drill
- 拓扑形态：双节点（未降级）

## 拓扑（ASCII）

~~~
              +----------------------+
   应用层      |  api :18010          |
   (复用 dev   |  worker              |
    build)     |  web :9090           |
              +----------+-----------+
                         |  DATABASE_URL（单写入口，最小版不自动跟随）
                         v
              +----------------------+         流复制         +----------------------+
   HA 层      |  patroni1/staging-pg1| <--------------------> |  patroni2/staging-pg2|
              |  PG16  restapi :8008 |                       |  PG16  restapi :8009 |
              +----------+-----------+                       +----------+-----------+
                         |  leader 仲裁（etcd v3.5，QUOTA 4GB，单节点）
                         +------------------+----------------------------------+
                                            |
                              +-------------+-------------+
                              | pgbackrest（repo 卷 keeper）|
                              +---------------------------+
~~~

## 镜像与版本（实测）

- patroni 节点镜像：edp-staging/patroni:pg16（自建：postgres:16-bookworm + patroni 4.1.5 + pgbackrest 2.59.1 + curl）
- PostgreSQL：16.15 (Debian 16.15-1.pgdg12+2)
- api 镜像：f340af9fdb31（edp-staging-api，backend/apps/api/Dockerfile 构建产物）

## 切换前 primary

    GET :8008/primary -> 200 ; GET :8009/primary -> 503  （200=主，503=从）
    - staging-pg1  role=leader  state=running  timeline=5  lag=
        - staging-pg2  role=replica  state=streaming  timeline=5  lag=0

## 演练 1：switchover staging-pg1 -> staging-pg2

patronictl 输出：
    Current cluster topology
+ Cluster: edp_staging (7686661137746374688) --+----+-------------+-----+------------+-----+
| Member      | Host     | Role    | State     | TL | Receive LSN | Lag | Replay LSN | Lag |
+-------------+----------+---------+-----------+----+-------------+-----+------------+-----+
| staging-pg1 | patroni1 | Leader  | running   |  5 |             |     |            |     |
| staging-pg2 | patroni2 | Replica | streaming |  5 |   0/408E438 |   0 |  0/408E438 |   0 |
+-------------+----------+---------+-----------+----+-------------+-----+------------+-----+
2026-09-18 00:19:26.21290 Successfully switched over to "staging-pg2"
+ Cluster: edp_staging (7686661137746374688) +----+-------------+-----+------------+-----+
| Member      | Host     | Role    | State   | TL | Receive LSN | Lag | Replay LSN | Lag |
+-------------+----------+---------+---------+----+-------------+-----+------------+-----+
| staging-pg1 | patroni1 | Replica | stopped |    |     unknown |     |    unknown |     |
| staging-pg2 | patroni2 | Leader  | running |  5 |             |     |            |     |
+-------------+----------+---------+---------+----+-------------+-----+------------+-----+

api /healthz 连续探测（20×1s，与 switchover 并行）：
    [08:19:23.421] +  0.0s  /healthz -> 200
    [08:19:24.452] +  1.0s  /healthz -> 200
    [08:19:25.506] +  2.1s  /healthz -> 200
    [08:19:26.534] +  3.1s  /healthz -> 200
    [08:19:27.586] +  4.2s  /healthz -> 200
    [08:19:28.690] +  5.3s  /healthz -> 200
    [08:19:29.757] +  6.3s  /healthz -> 200
    [08:19:30.846] +  7.4s  /healthz -> 200
    [08:19:31.937] +  8.5s  /healthz -> 200
    [08:19:33.060] +  9.7s  /healthz -> 200
    [08:19:34.134] + 10.7s  /healthz -> 200
    [08:19:35.229] + 11.8s  /healthz -> 200
    [08:19:36.298] + 12.9s  /healthz -> 200
    [08:19:37.371] + 14.0s  /healthz -> 200
    [08:19:38.475] + 15.1s  /healthz -> 200
    [08:19:39.526] + 16.1s  /healthz -> 200
    [08:19:40.679] + 17.3s  /healthz -> 200
    [08:19:41.728] + 18.3s  /healthz -> 200
    [08:19:42.777] + 19.4s  /healthz -> 200
    [08:19:43.825] + 20.4s  /healthz -> 200

- 非探测窗口：0/20
- 集群收敛：已收敛（staging-pg2=leader，staging-pg1=running replica）

切换后角色/延迟读数：
    GET :8008/primary -> 503 ; GET :8009/primary -> 200  （200=主，503=从）
    - staging-pg1  role=replica  state=streaming  timeline=6  lag=0
        - staging-pg2  role=leader  state=running  timeline=6  lag=
    pg_stat_replication（新主 staging-pg2 上查询）：
    staging-pg1 state=streaming sync=async replay_lag=00:00:00.003182

## 演练 2：switchover 回切 staging-pg2 -> staging-pg1

patronictl 输出：
    Current cluster topology
+ Cluster: edp_staging (7686661137746374688) --+----+-------------+-----+------------+-----+
| Member      | Host     | Role    | State     | TL | Receive LSN | Lag | Replay LSN | Lag |
+-------------+----------+---------+-----------+----+-------------+-----+------------+-----+
| staging-pg1 | patroni1 | Replica | streaming |  6 |   0/50002A0 |   0 |  0/50002A0 |   0 |
| staging-pg2 | patroni2 | Leader  | running   |  6 |             |     |            |     |
+-------------+----------+---------+-----------+----+-------------+-----+------------+-----+
2026-09-18 00:19:48.43313 Successfully switched over to "staging-pg1"
+ Cluster: edp_staging (7686661137746374688) +----+-------------+-----+------------+-----+
| Member      | Host     | Role    | State   | TL | Receive LSN | Lag | Replay LSN | Lag |
+-------------+----------+---------+---------+----+-------------+-----+------------+-----+
| staging-pg1 | patroni1 | Leader  | running |  6 |             |     |            |     |
| staging-pg2 | patroni2 | Replica | stopped |    |     unknown |     |    unknown |     |
+-------------+----------+---------+---------+----+-------------+-----+------------+-----+

api /healthz 连续探测（20×1s，与 switchover 并行）：
    [08:19:45.718] +  0.0s  /healthz -> 200
    [08:19:46.785] +  1.1s  /healthz -> 200
    [08:19:47.836] +  2.1s  /healthz -> 200
    [08:19:48.895] +  3.2s  /healthz -> 200
    [08:19:49.952] +  4.3s  /healthz -> 200
    [08:19:51.010] +  5.3s  /healthz -> 200
    [08:19:52.093] +  6.4s  /healthz -> 200
    [08:19:53.147] +  7.5s  /healthz -> 200
    [08:19:54.192] +  8.5s  /healthz -> 200
    [08:19:55.253] +  9.6s  /healthz -> 200
    [08:19:56.332] + 10.6s  /healthz -> 200
    [08:19:57.414] + 11.7s  /healthz -> 200
    [08:19:58.437] + 12.7s  /healthz -> 200
    [08:19:59.504] + 13.8s  /healthz -> 200
    [08:20:00.559] + 14.9s  /healthz -> 200
    [08:20:01.616] + 15.9s  /healthz -> 200
    [08:20:02.680] + 17.0s  /healthz -> 200
    [08:20:03.735] + 18.0s  /healthz -> 200
    [08:20:04.783] + 19.1s  /healthz -> 200
    [08:20:05.851] + 20.2s  /healthz -> 200

- 非探测窗口：0/20
- 集群收敛：已收敛（staging-pg1=leader，staging-pg2=running replica）

切换后角色/延迟读数：
    GET :8008/primary -> 200 ; GET :8009/primary -> 503  （200=主，503=从）
    - staging-pg1  role=leader  state=running  timeline=7  lag=
        - staging-pg2  role=replica  state=streaming  timeline=7  lag=0
    pg_stat_replication（回切后主 staging-pg1 上查询）：
    staging-pg2 state=streaming sync=async replay_lag=NULL

## pgbackrest 备份命令演练

- stanza-create 退出码：0
~~~
2026-09-18 00:20:07.434 P00   INFO: stanza-create command begin 2.59.1: --exec-id=206-429af0a2 --log-level-console=info --log-level-file=off --pg1-path=/var/lib/postgresql/data/pgdata --pg1-port=5432 --pg1-user=postgres --repo1-path=/pgbackrest/repo --stanza=edp
2026-09-18 00:20:07.442 P00   INFO: stanza-create for stanza 'edp' on repo1
2026-09-18 00:20:07.442 P00   INFO: stanza 'edp' already exists on repo1 and is valid
2026-09-18 00:20:07.442 P00   INFO: stanza-create command end: completed successfully (10ms)
~~~
- 全量备份退出码：0
~~~
2026-09-18 00:20:07.743 P00   INFO: backup command begin 2.59.1: --exec-id=213-e4002291 --log-level-console=info --log-level-file=off --pg1-path=/var/lib/postgresql/data/pgdata --pg1-port=5432 --pg1-user=postgres --process-max=2 --repo1-path=/pgbackrest/repo --repo1-retention-full=2 --stanza=edp --type=full
2026-09-18 00:20:07.752 P00   INFO: execute backup start: backup begins after the next regular checkpoint completes
2026-09-18 00:20:07.876 P00   INFO: backup start archive = 000000070000000000000007, lsn = 0/7000028
2026-09-18 00:20:07.876 P00   INFO: check archive for prior segment 000000070000000000000006
2026-09-18 00:20:15.991 P00   INFO: execute backup stop and wait for all WAL segments to archive
2026-09-18 00:20:16.008 P00   INFO: backup stop archive = 000000070000000000000007, lsn = 0/7000138
2026-09-18 00:20:16.023 P00   INFO: check archive for segment(s) 000000070000000000000007:000000070000000000000007
2026-09-18 00:20:16.141 P00   INFO: new backup label = 20260918-002007F
2026-09-18 00:20:16.234 P00   INFO: full backup size = 32.3MB, file total = 1565
2026-09-18 00:20:16.234 P00   INFO: backup command end: completed successfully (8493ms)
2026-09-18 00:20:16.234 P00   INFO: expire command begin 2.59.1: --exec-id=213-e4002291 --log-level-console=info --log-level-file=off --repo1-path=/pgbackrest/repo --repo1-retention-full=2 --stanza=edp
2026-09-18 00:20:16.235 P00   INFO: expire command end: completed successfully (1ms)
~~~
- pgbackrest info：
~~~
stanza: edp
    status: ok
    cipher: none

    db (current)
        wal archive min/max (16): 000000010000000000000003/000000070000000000000007

        full backup: 20260918-002007F
            timestamp start/stop: 2026-09-18 00:20:07+00 / 2026-09-18 00:20:16+00
            wal start/stop: 000000070000000000000007 / 000000070000000000000007
            database size: 32.3MB, database backup size: 32.3MB
            repo1: backup set size: 4.1MB, backup size: 4.1MB
~~~

## 结论

1. **双节点拓扑成立，未触发降级**：etcd×1 + patroni×2（PG16）+ pgbackrest + 应用层全量 `deploy` 一次通过；演练当日 timeline 从 5 推进到 7（两轮 switchover 各 +1，符合预期）。
2. **切换成功率 2/2**：`patronictl switchover` 双向往返（pg1→pg2→pg1）均返回 `Successfully switched over`，切换后 `/primary` 角色翻转正确（503↔200），集群在秒级完成收敛（两段均在等待窗口内达成 leader=running + replica=streaming）。
3. **api 探测零中断**：两段各 20×1s、共 40 次 `/healthz` 全部 200，非 200 次数 0，最长中断 0s（探测粒度 1s）。口径说明：`/healthz` 为无 DB 依赖的存活探针，证明应用进程面零中断；DB 写面（单写入口固定 patroni1:5432，最小版不自动跟随）在 leader 翻转窗口内不可写，受影响时长 ≈ 集群收敛时长（秒级）。
4. **复制延迟**：切换后 replica 立即恢复 streaming、lag=0；`pg_stat_replication` replay_lag 实测 3.2ms（第二段读数为 NULL——新 streaming 会话尚未采样，属正常）。
5. **备份链路实测可用**：`stanza-create` 幂等成功；全量备份 32.3MB / 1565 文件 / 8.5s 完成（压缩后 4.1MB）；WAL 归档自 timeline 1 起连续（pgbackrest info 区间 `...0003`~`...0007`），满足 RPO ≤ 5min 的归档前提（恢复演练 W5）。
6. **回滚路径实测**：`-Action rollback` 将应用层按记录的 `:rollback` 镜像 `--force-recreate`，api `/healthz` 第 2 次探测恢复 200；最小回滚语义（本机 tag 链、迁移不回滚）已在脚本注释留痕。
7. **镜像说明**：`ghcr.io/zalando/patroni` 与 Docker Hub 用户命名空间在本机网络不可拉取（实测 pull denied/manifest unknown；quay.io 可直连），patroni 节点改用 `deploy/patroni/Dockerfile` 自建等价镜像（postgres:16-bookworm + patroni 4.1.5 + pgbackrest 2.59.1 + curl），行为与官方镜像一致（`patroni /etc/patroni.yml`，replicator 角色由 Patroni 自动创建）。

## 降级预案与后续项

- 降级预案（本次未触发）：宿主资源不足 -> 去 patroni2 单节点，演练改为「拓扑编排冒烟 + 备份命令演练」，双节点切换演练记「未执行-W5 补」。
- 后续项：单写入口不自动跟随（W5 引入 HAProxy/Pgbouncer）；pgbackrest 备份仍在本机 repo 卷（W5 迁对象存储 + PITR/租户级恢复演练，见设计 9.2）；回滚为本机 tag 链最小语义（W5 接镜像仓库做版本化）。
