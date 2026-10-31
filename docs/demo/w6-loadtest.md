# W6 压测读数汇总（T6 / EDP-033）

- 环境：dev compose 栈（`deploy/docker-compose.dev.yml` + 端口 override：api→宿主 18000、db→15432、web→9080；宿主 8000 被 spc-v2 容器占用，W5 备忘的 override 方案）；api 单副本 uvicorn，db postgres:16-alpine。
- 数据规模：`demo.cli seed --scale 116`，实测 5051 业务对象 / 49571 事件 / 10101 证据（含少量基线重放与压测写入）。
- 工具：locust 2.46.6（headless），AdminUser/AnalystUser 权重 1:1，`wait_time = between(0.5, 2)`，三档 20/50/100 VU 各 180s（locustfile `STAGES`；单档读数经 `EDP_LOCUST_STAGE` 覆盖）。
- 配额前提：压测期间经 B.14 临时提额将 default 租户 `api_rate_limit` 100→20000 req/min（PATCH `/tenants/{id}/quotas`，审计留痕），测后已恢复 100。首轮 20 VU 未提额时 87.45% 请求被 429（STANDARD 计划 100 req/min 进程内令牌桶）——限流器按设计生效，非异常；该轮读数作废重跑。
- 断言口径：`status_code < 500` 为通过；4xx（如 429）与连接异常均计 failure（locust 默认 ≥400 即失败）。
- 日期：2026-09-22。

## 1. P95 表（接口 × 三档 VU）

| 接口 | 20 VU P95 | 50 VU P95 | 100 VU P95 |
|---|---:|---:|---:|
| GET /api/v1/health | 89 ms | 110 ms | 260 ms |
| GET /api/v1/objects?limit=20 | 31 ms | 46 ms | 370 ms |
| GET /api/v1/events?risk_level=P1（含游标翻页） | 34 ms | 42 ms | 210 ms |
| GET /api/v1/tools/orders?limit=20 | 36 ms | 46 ms | 530 ms |
| GET /api/v1/decisions/cases/{id} | 32 ms | 46 ms | 97 ms |
| GET /api/v1/admin/quality/reports | 69 ms | 77 ms | 420 ms |
| GET /api/v1/admin/quality/coverage | 41 ms | 43 ms | 710 ms |
| GET /api/v1/audit-logs?limit=20 | 31 ms | 39 ms | 650 ms |
| POST /api/v1/events/batch（2 条小批量） | 84 ms | 100 ms | 1000 ms |

## 2. 吞吐与错误率

| 档位 | 请求总数 | 失败数 | 错误率 | 实测吞吐 |
|---|---:|---:|---:|---:|
| 20 VU × 180s | 3397 | 0 | 0.00% | 18.9 req/s |
| 50 VU × 180s | 8424 | 0 | 0.00% | 46.9 req/s |
| 100 VU × 180s | 4568 | 5 | 0.11% | 25.3 req/s（回落） |
| 全三档连跑（归档 locust.json） | 11830 | 93 | 0.79% | 22.6 req/s |

- 100 VU 出现吞吐回落与 30s+ 长尾（max≈32s）：api 日志证实为 DB 连接池打满——`QueuePool limit of size 10 overflow 20 reached, connection timed out, timeout 30.00`（`core/db.get_engine` 的 pool_size=10 + max_overflow=20 在 100 并发下不足）；5 例失败即池超时后连接异常。
- 全三档连跑叠加的 0.79% 失败与 ~60s 极端长尾同源（饱和窗口内池排队），P95 仍全部 <2s。

## 3. RLS 双轨差值（rls_probe.py，200 次/模式）

| 模式 | edp_app P95（RLS 生效） | edp_migrator P95（BYPASSRLS） | 差值 |
|---|---:|---:|---:|
| events risk 过滤一页（页查询+count，三表 join） | 6.78 ms | 3.44 ms | +97.1%（绝对 +3.3 ms） |
| objects 类型过滤一页（单表） | 2.00 ms | 2.58 ms | -22.4%（噪声内） |
| audit 过滤一页（platform.audit_logs，控制面无 RLS） | 1.55 ms | 2.12 ms | -26.6%（零开销对照，负差为噪声） |

- 结论：RLS 开销集中在多表 join 的 events 查询（每表 policy 谓词 `tenant_id = current_setting('app.tenant_id')::uuid`），绝对开销 +3.3 ms/次，相对翻倍但量级个位数毫秒；单表查询与无 RLS 控制面表开销在噪声（<1 ms）内。三模式最大相对差 +97.1%（events 模式）。
- **显式双判定（T6 评审 I-1/裁定 b）**：相对口径 **不达标**（+97.1% > 5% 设计阈值）；绝对口径 **无实际影响**（+3.3 ms，含 RLS 的端到端 P95 全部 <2s）。
- 归因：events 查询 4 表 policy 谓词（页查询三表 join + count 回访 events）为固定求值成本，小规模基线（毫秒级）下占比高；`tenant_id` 索引前缀使各表扫描有界，开销不随数据量线性放大。
- 口径建议：5% 相对阈值在毫秒级基线下低于 ±0.5 ms 测量噪声地板，数学上不可判；建议 Go/No-Go 门禁改采绝对口径（或占 2s 预算百分比），阈值重校准留给设计文档修订。

## 4. 结论

- **达标判定：全部 9 个接口在三档 VU 下 P95 均 <2s，达标。** 100 VU 档最慢为 POST /events/batch 1000 ms 与 admin/quality/coverage 710 ms（均受池排队长尾抬升；50 VU 及以下全部 ≤110 ms）。
- **T12 输出口径（Go/No-Go RLS 行）**：按双口径呈现——相对口径不达标（+97.1% > 5%）/ 绝对口径无实际影响（+3.3 ms）；门禁判定采绝对口径（P95 <2s 含 RLS 全达标），不触发「按租户组拆库」条款（设计文档 V2.0 L420）。
- **Redis 决策输入（热点接口 QPS 观测）**：峰值可持续吞吐 ≈47 req/s（50 VU）；按量排序热点为 events risk 过滤（≈18 req/s）、objects（≈9 req/s）、tools/orders 与 health（≈6 req/s）。health 的 ops_metrics 每调用固定执行四条 count/percentile 聚合 SQL（pg_stat 中 3713 次调用组、mean 3.2~10 ms，其中 24h 小时桶 max 聚合 mean 10.03 ms——**T7 勘误**：该 mean 10 ms 原误归因于「events 列表全量 count」，复核证实 events 列表 count 为索引仅扫描 ≈0.1 ms、未入 top20，详见 §5.1）——若 QPS 上探（>100 req/s），health ops_metrics 聚合（随 events 总量线性放大，见 §5.2 条目 5）是 Redis 缓存的首选候选；当前 47 req/s 峰值下 DB 未过载（除池容量），暂无必须引入缓存的读数依据。
- **T7 治理线索（pg_stat_statements top20，见 `deploy/loadtest/pg_stat_top20.txt`；处置决策见 §5.2）**：
  1. `platform.tenant_usage_daily` 计量 upsert 为总耗时第一（37267 次 / 359.7 s / mean 9.65 ms）——api_calls 逐请求独立会话写入在压测流量下成为最大单点，建议合并批量/异步化；
  2. DB 连接池 10+20 在 100 并发打满（30s 超时排队）——建议按目标并发上调 pool 或引入池排队度量；
  3. quality reports/coverage 的覆盖率/孤儿聚合（mean 12~13 ms）与 health 的 ops_metrics count 查询为均值最慢的读路径。

## 5. T7 复核与治理（慢查询收口）

### 5.1 勘误：events count 归因（§4「Redis 决策输入」段）

§4 原句「events 列表每次执行全量 count（mean 10 ms）」归因有误，T7 复核（T6 评审 Minor-2）证实如下：

- **调用次数对账**（locust 三份单档 + 全三档归档 vs `pg_stat_top20.txt`）：
  - events 列表请求合计 10653 次（1306+3218+1627+4502），每次页查询 + 同过滤 count 各一条；其页查询两形态（首页 / 游标页）在 pg_stat 中为 5407+5330 = 10737 次（含少量基线重放），与之吻合；**count 查询（≈10653 次）不在 top20**——top20 按 mean DESC 排序、末位 mean 3.23 ms，即 events count mean <3.23 ms。
  - health 请求合计 3660 次（439+1075+584+1562）+ 作废首轮 429 放行部分（估 ≈50）≈ **3713 次**，与 top20 中四条 calls=3713 的查询组精确吻合（`_ingest_peak` 10.03 / `_p95_latency` 8.40 / events_24h count 5.14 / audit_7d count 3.23，`health/service.py:195-229`）——即 health ops_metrics 每调用固定执行的四条聚合，mean 10 ms 者为 `_ingest_peak`（24h 小时桶 max）。
- **EXPLAIN (ANALYZE, BUFFERS) 实测**（dev 栈 51059 行，edp_app + 事务级 `app.tenant_id` 绑定，原始输出归档 `deploy/loadtest/explain-t7-count.txt`）：
  - events 列表 count（`WHERE risk_level='P1'`）：Index Only Scan `idx_events_risk`（tenant_id+risk_level 条件），Execution **0.096 ms**、shared hit 2——亚毫秒，未入 top20 属实；
  - health `_ingest_peak`：**Seq Scan**（created_at 无索引，全表 1778 块顺序扫描），Execution **28.8 ms**（pg_stat mean 10.03 ms 为压测窗口多次调用均值，含表更小/缓存更热阶段）。
- **勘误结论**：mean 10 ms 的 count 属 health ops_metrics 的 `_ingest_peak`，非 events 列表；§4 该句已按此改写。对 §4 结论无影响（缓存候选判定本就以 QPS 上探为条件，且 health 聚合线性放大的判断因此更成立）。

### 5.2 慢查询治理决策

| # | 事项 | 判定 | 依据 |
|---|---|---|---|
| 1 | 0014 索引迁移（计划条件项：pg_stat 出现 mean>500 ms 查询才建） | **不建——条件不触发** | top20 无 mean>500 ms 查询：最大为 seed 放大单次 UPDATE 76.6 ms（1 次）与批量 INSERT 55.99 ms（44 次，均为写入瞬态）；稳态最大 mean = health `_ingest_peak` 10.03 ms |
| 2 | `tenant_usage_daily` upsert（总耗时第一：37267 次 / 359.7 s / mean 9.65 ms）是否索引缺失 | **非索引问题，不建** | 表自 0001 baseline 即有唯一索引 `uq_usage_daily(tenant_id, usage_date)`（`backend/migrations/versions/platform/0001_platform_baseline.py:127-130`），upsert ON CONFLICT 走该索引；mean 9.65 ms 为**逐请求独立短会话 + 立即 commit**（`ratelimit.py:145-164` record_api_call，W3R-02 权衡的既定代价——避免行锁串行互等）的固定开销 ×37267 次累计 |
| 3 | upsert 计量批量 / 异步化 | **不做，留痕 W6+** | 结构性改动（攒批窗口、崩溃丢计量的口径变化），超出 W6 最小治理范围；P95 已达标且 DB 未过载，仅总耗时长 |
| 4 | DB 连接池 10+20 调大（100 VU 饱和） | **不动代码，留痕** | `core/db.py:37` 硬编码，`core/config.py` 无 `EDP_DB_POOL_SIZE` 类现成 env——按最小动作原则（env 已存在才调默认值，新增配置面超范围）不动代码；100 VU 池饱和定性为容量规划项（编排层调参或引入池排队度量，W7+） |
| 5 | health ops_metrics 24h 聚合 Seq Scan（created_at 无索引） | **不建索引，留痕** | mean 10 ms << 500 ms 阈值；但随 events 总量线性放大（5.1 万行 ≈10~29 ms，50 万行外推 ≈100~300 ms 量级），数据规模上台阶后与「QPS>100 引缓存」（§4）一并复评 |

### 5.3 复测归档

- 本轮治理**无代码 / 迁移改动**（全部为「不做 + 留痕」），无复测项；唯一实测为 §5.1 的 count 归因 EXPLAIN，原始输出归档 `deploy/loadtest/explain-t7-count.txt`（2026-09-22，dev 栈 51059 行）。

## 附：产物清单（deploy/loadtest/）

- `locust.json` / `locust.html`——全三档连跑（20→50→100 VU）归档；
- `locust-20vu.json|.html`、`locust-50vu.json|.html`、`locust-100vu.json|.html`——单档读数（报告表格数据源，P95 由 response_times 直方图计算）；
- `rls-probe.txt`——RLS 双轨探针原始输出；
- `pg_stat_top20.txt`——压测后 pg_stat_statements top20 快照（mean_exec_time DESC）；
- `explain-t7-count.txt`——T7 count 归因复核 EXPLAIN (ANALYZE, BUFFERS) 归档（events count vs health `_ingest_peak`）。
