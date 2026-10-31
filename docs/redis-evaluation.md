# Redis 外置评估（W5 / T17）

| 项 | 内容 |
|---|---|
| 状态 | 评估稿（**仅文档，不写代码**）——**W6 决策已收口（终），见 §7** |
| 触发 | 多副本部署（设计 9.5 api×2 / worker×2）为既定路线 + W5 T16 HAProxy 单写入口落地后，应用进程内状态的单副本语义从「隐含假设」变为「真实风险面」 |
| 上游缺口 | W3R-01（限流单副本）、W4-03（进程内单副本语义三处同类）、W5-04（异步任务执行互斥单副本） |
| 设计口径 | 9.4（Redis 作为优化预留而非首期依赖；缓存键必须含 tenant_id）、9.5（api×2 / worker×2）、3.5（网关 + 应用双层令牌桶） |
| 决策时点 | W6 压测（EDP-033）后 |

## 1. 背景与触发

W1~W5 有三处能力依赖**进程内状态**实现，其正确性以单副本为前提：

| # | 点位 | 缺口编号 | 代码位置 |
|---|---|---|---|
| 1 | 租户限流令牌桶 | W3R-01 | `backend/apps/api/edp_api/modules/tenantmgmt/ratelimit.py` |
| 2 | 审计策略 ACTIVE 缓存 | W4-03 | `backend/apps/api/edp_api/modules/audit_policies/service.py` |
| 3 | 后台任务执行互斥 | W5-04 | `backend/apps/api/edp_api/modules/quality/service.py`（同类：`evidence/service.py`、`adapters_admin/service.py`） |

现状 staging 实际以单 api 副本运行（W4/W5 演练口径），单副本语义正确。但：

- 设计 9.5 部署拓扑明确 **api×2 副本、worker×2 副本**（`EDP数据平台系统设计文档_V2.0.md:770-772`）；设计 3.6 容量假设 QPS 总 500 req/s 峰值、app 无状态横向扩副本（同文档 9.5/3.6）；
- W5 T16 已落地 HAProxy 单写入口（commit `5b69c89`）：api/worker 的 `EDP_DATABASE_URL` 统一指向 `haproxy:5432`，经 Patroni REST API 健康检查自动跟随主库切换（`deploy/haproxy/haproxy.cfg`；`deploy/docker-compose.staging.yml` 顶部「单写入口约定」）。**但 HAProxy 是数据库侧（`mode tcp`，5432）的单写入口**——解决的是 PG 主从切换面，不覆盖应用进程内状态；
- 三点位后台任务在 api 进程内以 `asyncio.create_task` 派发执行（W5 实现口径），**api×2 即两个执行域**；设计 9.5 的 worker×2 侧 Outbox 分发为 `SKIP LOCKED` 天然安全，不在本文范围。

即：**应用进程内状态与「可水平扩副本」的设计目标相矛盾**。本文档对三点位逐一分析现状与后果，给出 A（Redis）/ B（PG）/ C（维持单副本约束）三方案对比，并输出 W6 决策建议。

## 2. 三点位现状分析

### 2.1 点位 1：租户限流令牌桶（W3R-01）

| 项 | 内容 |
|---|---|
| 现状实现 | 模块级 `_buckets: dict[UUID, _Bucket]`（`ratelimit.py:48`）；`check_rate_limit` 惰性补充（`ratelimit.py:56-91`）：capacity = `tenant_quotas.api_rate_limit`（默认 100 req/min），refill = limit/60 每秒；取不到令牌返回 Retry-After，调用方（tenant_scoped）经独立会话落 `RATE_LIMITED` 审计 + `throttled_429` 计数；水位首次 ≤20% 落 `RATE_LIMIT_WARNING` |
| 单副本假设 | 模块 docstring 明文：「单副本语义：多副本部署下实际速率 ≈ limit×副本数，网关层全局限流兜底」（`ratelimit.py:11-13`） |
| 多副本后果 | 双 api 副本各持独立桶：**租户配额 100 req/min 实际放行 ≈ 200 req/min**（N 副本 ≈ N×）；429 判定随请求落点漂移（同租户连续请求在两副本间交替，可能在 A 被拒、在 B 放行）；80% 水位告警按副本各算各的，`RATE_LIMIT_WARNING` 审计噪音随副本数放大 |
| 兜底 | 网关层全局限流样例 `deploy/nginx-limit-req.conf.example`——全局维度而非租户维度（租户分键需鉴权后信息，nginx 无法分键），只能缓解不能替代 |
| 严重度 | **中高**：不损坏数据，但 noisy neighbor 防护在多副本下失效（配额被放大 N 倍），与设计 3.5「按租户维度」的防护目标直接冲突 |

### 2.2 点位 2：审计策略 ACTIVE 缓存（W4-03）

| 项 | 内容 |
|---|---|
| 现状实现 | 模块级 `_ACTIVE_POLICIES: dict[UUID, list[ActivePolicy]]`（`service.py:83`）；本模块写路径（create/update/delete）flush 后 `_invalidate(tenant_id)`（`service.py:86-88`，调用点 `:119`、`:198`、`:214`）；未命中且有 `sync_session` 时惰性加载回填（`service.py:221-256`）；缓存值供审计切面 `matching` 打 `policy_hits`（`service.py:259-281`） |
| 单副本假设 | 模块 docstring 明文：「缓存为模块级 dict，仅本进程可见——多副本/多 worker 部署下写路径失效不同步，需外置（Redis 等，W5+ 评估）；单副本（dev / 单 api pod）语义正确，多副本前外置」（`service.py:16-18`） |
| 多副本后果 | 副本 A 上更新/停用策略 → 仅 A 的缓存失效；副本 B **无 TTL、无跨进程失效通道，陈旧窗口无上界**（直到 B 自己处理到该租户的写路径才失效）。后果：审计行 `policy_hits` 打标与实际 ACTIVE 策略不一致——新策略漏标、已停用策略继续命中；打标面仅切面 ORM 写路径（`record_explicit` 不参与，W4-04 已限定） |
| 严重度 | **中**：不影响业务数据与权限判定（策略仅用于审计打标/通知路由匹配），但属审计留痕正确性面；「陈旧无上界」非有界抖动，合规口径上不可长期存在 |

### 2.3 点位 3：后台任务执行互斥（W5-04）

| 项 | 内容 |
|---|---|
| 现状实现 | `start_recheck` 在请求事务内登记 RUNNING 行（`quality/service.py:510-543`）→ 202，`asyncio.create_task` 派发进程内后台执行体 `_run_recheck`（`quality/service.py:553`）；状态落库多副本安全（ops.tasks 行级回写、终态幂等），但**执行互斥不保证**（docstring `quality/service.py:76-79`）。同类：evidence reindex（`evidence/service.py:319-322`，读侧任务）、adapter sync（`adapters_admin/service.py:14-17`：「同一适配器并发触发 = 两行 RUNNING 并发执行、无互斥」） |
| 单副本假设 | 同一进程串行语义下，两次触发同一任务实际串行；多副本下无任何互斥原语 |
| 多副本后果 | 双副本并发同租户触发 recheck → 两行 RUNNING、两套四段聚合并行执行：重复计算/IO、`stats` 互不感知；checksum 失配事件经 UUIDv5 幂等（`quality/service.py:433-446`）不重复落数，但抽检/对账自身经 ingest 产生重复计量副作用（W5-09 已登记）。adapter sync 并发全量拉取由 registry 幂等去重兜底（`adapters_admin/service.py:14-17`） |
| 严重度 | **低-中**：幂等通道兜底使数据面无重复落数；主要是重复算力/IO 浪费与任务统计口径混乱（同任务两行 RUNNING 的运营观感） |

## 3. 方案对比（三方案 × 三点位）

### 3.1 方案 A：引入 Redis

| 点位 | 实现机制 |
|---|---|
| 限流 | Lua 脚本原子「补充 + 取令牌」（`EVALSHA`，key 含 tenant_id）——单键原子无竞态；Retry-After 由脚本返回值计算 |
| 缓存 | pub/sub 失效通道（写路径 PUBLISH 租户失效消息，各副本订阅后清本地缓存）或版本号键（缓存值携带版本，读时比对）；**键必须含 tenant_id**（设计 9.4 明文防串租户） |
| 任务互斥 | `SET lock:{tenant_id}:{task_type} <token> NX PX <ttl>` + Lua 校验 token 释放；长任务定期续租防过期 |

- 优点：业界标准做法；延迟低（亚毫秒）；限流/缓存/锁三面共用一套组件；Lua/NX 原子性免除应用层竞态。
- 缺点：
  - 新组件运维面（部署、持久化、监控、升级、凭据）；
  - 一致性模型引入（锁过期/续租、缓存失效竞态、pub/sub 消息丢失需兜底）；
  - **依赖故障面**：Redis 不可用时三面各自的降级策略都要定义（见 §5）；
  - 与设计口径的关系：9.4 明确「缓存：W6 视压测结果引入 Redis……作为优化预留而非首期依赖」——A 是「按需引入」，W6 压测结论是前提。

### 3.2 方案 B：PG 承载（无新组件）

| 点位 | 实现机制 |
|---|---|
| 任务互斥 | `pg_try_advisory_lock` / `pg_advisory_xact_lock`（键由 `(tenant_id, task_type)` 派生）；执行体取锁失败即跳过/提前退出。注意：事务级锁仅覆盖单事务，而 recheck 逐段提交（`quality/service.py:591-614`）——跨段长任务需会话级锁并持有独立连接，或锁粒度取「段」 |
| 缓存 | 三选一：① 表 + `LISTEN/NOTIFY`（写路径 NOTIFY，各副本 LISTEN 失效——需专连接）；② **短 TTL 轮询**（如 5~10s，去掉跨进程失效通道，陈旧窗口有界）；③ 直接读 DB（策略表小、查询索引化，最简单、正确性最高，成本是每请求一次 SELECT） |
| 限流 | 限流表 UPSERT 原子扣减（`INSERT ... ON CONFLICT DO UPDATE ... RETURNING`，行锁串行化）或原子条件 `UPDATE`。注意：现状 `record_api_call` 已按请求经独立短会话写 usage 行（`ratelimit.py:145-164`），PG 限流是把每请求写放大一档，但并非从零引入写路径 |

- 优点：复用 PG 事务与既有连接/备份/HA 体系；零新组件；RLS 天然覆盖（缓存表/限流表可按 tenant 隔离）；advisory lock 成本极低。
- 缺点：热点行写压力（单租户高频请求在限流行上串行）；延迟高于 Redis（一次 DB 往返）；占用连接池；`check_rate_limit` 从同步函数变异步，调用路径改动面比 A 大（若选 PG 限流）。

### 3.3 方案 C：维持单副本 + 显式化约束

| 点位 | 实现机制 |
|---|---|
| 全部 | 不写代码：把「单副本」从隐含假设变显式部署约束——api 只起 1 副本；或网关按租户 key 一致性哈希路由（同租户固定落同一副本，进程内状态按租户聚合后语义恢复）；DB 侧继续由 HAProxy 单写入口（T16）保证切换可用性 |

- 优点：零代码/零新组件；T16 已落地的 HAProxy 单写入口保证数据库切换面可用性。
- 缺点：
  - 丧失 api 水平扩展（与设计 9.5 api×2、3.6 QPS 500 的演进路线冲突）；
  - api 单副本 = 应用层 SPOF：发布/故障即全站中断（数据库侧 HA 覆盖不到应用层）；
  - 一致性哈希路由：滚动更新/扩缩容时租户重映射，进程内状态随迁移丢失（限流桶重建、缓存冷启动）；且「同租户单副本」不闭环后台任务——任务在 api 进程内执行，副本漂移时旧任务仍在旧进程运行，互斥语义仍不保证；
  - worker 侧本无此问题（SKIP LOCKED 天然安全，设计 9.5），C 只解决 api 面。

### 3.4 对比总表

| 维度 | A. Redis | B. PG | C. 单副本约束 |
|---|---|---|---|
| 正确性（多副本） | 高（原子 Lua / NX 锁 / 失效通道） | 高（advisory lock / 行锁 / 短 TTL 有界陈旧） | 单副本内正确；多副本依赖路由约束且任务面不闭环 |
| 复杂度 | 高（新组件 + 一致性模型 + 三面降级） | 中（SQL 原语 + 调用路径异步化） | 低（配置/编排） |
| 运维成本 | 高（新组件生命周期/监控/HA） | 低（复用 PG 体系） | 低，但可用性成本高（SPOF） |
| 延迟 | 低（亚毫秒） | 中（一次 DB 往返） | 最低（进程内） |
| 水平扩展 | 支持 | 支持（限流热点行是瓶颈） | **不支持** |
| 与设计口径 | 9.4「W6 视压测引入、优化预留」 | 无冲突 | 与 9.5 api×2 冲突 |
| 工作量（人日，粗估） | 5~8 | 2~4 | 0（+编排/文档 0.5） |

（工作量估计含实现 + 测试 + 文档；不含 W6 压测本身；分解见 §4.2。）

## 4. 建议（W6 决策输入）

### 4.1 分点位建议

| 点位 | 建议 | 理由 |
|---|---|---|
| 任务互斥（W5-04） | **B（PG advisory lock）优先，不等待 Redis** | 低成本高收益：约 0.5~1 人日；消除「同任务多副本并发执行」的重复算力与运营歧义；无需新组件、无降级面；即使 W6 最终引入 Redis，advisory lock 仍可作为锁面的兜底/替代 |
| 限流（W3R-01） | **W6 压测后定 A 或 B**：租户级配额需精确执行且热点租户 QPS 高 → A；否则 B（UPSERT 原子扣减）或维持现状 + 文档化 N× 放大 | 设计 9.4 口径即「W6 视压测结果引入 Redis」；当前 staging 单副本语义正确，无立即风险 |
| 审计策略缓存（W4-03） | **B 的轻量变体先行（短 TTL 或直读 DB）**；若 A 落地再迁 pub/sub | 策略表小、读路径低频（仅切面写时匹配）；「陈旧无上界」比「陈旧 5s」是质变；直读 DB 彻底消除缓存一致性面，压测可量化其成本 |

若 W6 压测结论为「引入 Redis」（A 落地），三点位可统一迁 A，B 的 advisory lock 可与 Redis 锁共存（锁面兜底）。若结论为「暂不引入」，B 的限流/缓存部分可作为过渡实现（记为 W6+ 工作项）。

### 4.2 工作量估计（人日）

| 方案 | 限流 | 缓存 | 任务互斥 | 合计 |
|---|---|---|---|---|
| A. Redis | 2~3（Lua + 客户端 + 降级 + 测试） | 1~2（pub/sub 或版本号 + TTL + 测试） | 1~2（NX 锁 + 续租 + 测试） | **5~8**（另含编排/监控 0.5~1） |
| B. PG | 1~2（UPSERT + 调用路径异步化 + 测试） | 0.5~1（TTL/直读 + 测试） | 0.5~1（advisory lock + 测试） | **2~4** |
| C. 约束 | — | — | — | 0（编排 + 文档 0.5） |

（人日为量级估计，供 W6 排期；不含压测与灰度观察窗口。）

## 5. 风险与开放问题

| # | 项 | 说明 |
|---|---|---|
| 1 | Redis 故障降级路径 | 限流：fail-open（放行 + 告警）还是 fail-closed（拒绝）？业务面建议 fail-open + 告警（网关全局限流兜底），需 W6 确认；缓存：Redis 不可用回退本地短 TTL 缓存或直读 DB；任务锁：不可用时回退 PG advisory lock 或「允许执行 + 告警」，不可静默并发 |
| 2 | 缓存键 tenant_id 强制 | 设计 9.4 明文「缓存键必须含 tenant_id，防止跨租户串数据」——Redis 方案下键规范（`{domain}:{tenant_id}:...`）需评审；B 方案下 RLS 会话已 `bind_tenant`，天然隔离 |
| 3 | 迁移与回滚 | 三面均须保持现有函数签名（`check_rate_limit`、`active_policies`/`matching`、任务执行入口）作为接缝，实现可经环境变量切换（如 `EDP_REDIS_URL` 未设 → 进程内实现）；回滚 = 回退环境变量/版本，无数据迁移 |
| 4 | Redis 自身 HA | 单 Redis 实例 = 新 SPOF；sentinel/集群的运维复杂度未评估（A 方案工作量未含）；dedicated 部署形态是否随附 Redis 需产品确认 |
| 5 | advisory lock 长任务语义 | 会话级锁需持有连接至任务结束（连接池占用）；事务级锁只覆盖单事务，而 recheck 逐段提交——锁粒度（整任务 vs 逐段）与连接策略需实现时定稿 |
| 6 | 限流写路径口径 | PG 限流与现有 `record_api_call` 独立短会话（`ratelimit.py:145-164`）是否合并？合并可省一次往返但重新引入长锁窗口（W3R-02 已登记该权衡） |
| 7 | 网关按租户头限流 | W3R-01 提到「网关按租户头限流」为另一选项——依赖网关注入可信租户头（鉴权后信息），与设计 3.5「网关 + 应用双层」的职责切分需 W6 一并评估 |

## 6. 参考

| 引用 | 位置 |
|---|---|
| W3R-01 限流为单副本语义 | `docs/demo/m2-demo.md:253` |
| W4-03 进程内单副本语义三处同类 | `docs/demo/m2-demo.md:275` |
| W5-04 异步任务执行互斥单副本 | `docs/demo/m2-demo.md:292` |
| 设计 9.4 性能与租户防护（Redis 优化预留 / 缓存键含 tenant_id） | `EDP数据平台系统设计文档_V2.0.md:756-762` |
| 设计 9.5 部署拓扑（api×2 / worker×2 / 单写入口背景） | `EDP数据平台系统设计文档_V2.0.md:764-780` |
| 设计 3.5 租户级防护（api_rate_limit 默认 100 req/min） | `EDP数据平台系统设计文档_V2.0.md:400-411` |
| 设计 3.6 容量假设（QPS 500 峰值 / 横向扩副本） | `EDP数据平台系统设计文档_V2.0.md:413-420` |
| 限流实现 | `backend/apps/api/edp_api/modules/tenantmgmt/ratelimit.py:11-13,48,56-91,145-164` |
| 审计策略缓存实现 | `backend/apps/api/edp_api/modules/audit_policies/service.py:16-18,83,86-88,119,198,214,221-256` |
| 质量任务执行 | `backend/apps/api/edp_api/modules/quality/service.py:76-79,510-543,553,591-614` |
| 同类：evidence reindex | `backend/apps/api/edp_api/modules/evidence/service.py:319-322` |
| 同类：adapter sync | `backend/apps/api/edp_api/modules/adapters_admin/service.py:14-17` |
| HAProxy 单写入口（W5 T16） | `deploy/haproxy/haproxy.cfg`；`deploy/docker-compose.staging.yml` 顶部「单写入口约定」 |
| W5 spec T17 范围 | `docs/superpowers/specs/2026-09-20-edp-w5-design.md:152-154` |
| W5 计划 T17 条目 | `docs/superpowers/plans/2026-09-20-edp-w5.md:329-337` |

## 7. W6 决策（终）

决策时点 2026-09-22（W6 T7，EDP-033 压测后收口）；数据依据 `docs/demo/w6-loadtest.md`（P95 表 §1、吞吐与池饱和 §2、热点 QPS 与 pg_stat §4/§5）。

| 点位 | 决策 | 依据 |
|---|---|---|
| 任务互斥（W5-04） | **已落 PG advisory lock（§4.1 建议的方案 B），点位关闭** | W6 T3 落地（commit `cafc0d1`）：会话级 `pg_try_advisory_lock`，键 `ops.task:{task_type}[:{ref}]`（adapter_sync 附适配器名，`quality/service.py:173-177` 单一实现），覆盖 quality recheck / evidence reindex / adapter sync 三处；会话断开自动解锁（无 Redis 锁的续租/过期故障面），被占即 409/跳过 |
| 限流（W3R-01） | **维持单副本 + 进程内令牌桶 + HAProxy 单写入口语义，不引入外置限流**；N× 放大注意事项按 §2.1 文档化（多副本实际放行 ≈ limit×副本数，网关全局限流兜底，扩副本前须重启本评估） | 压测峰值可持续吞吐 46.9 req/s（50 VU、0 失败；100 VU 回落系 DB 池容量非限流器）；未出现「热点租户 QPS 高到需外置精确计数」的形态（§2/§4.1 判据）；限流器本身经压测验证按设计生效（首轮未提额 87.45% 429，`w6-loadtest.md` 配额前提段） |
| 缓存（设计 9.4 读路径） | **本轮不引入**——按设计 9.4「W6 视压测结果引入」条款，条件不触发 | 9 接口 P95 三档全部 <2s（最差 events/batch 1000 ms @100 VU；50 VU 及以下 ≤110 ms）；pg_stat top20 无 mean>500ms 查询（稳态最大 mean 10 ms，`w6-loadtest.md` §5） |

三行结论：**互斥已闭环（PG advisory lock）、限流维持进程内（单副本约束显式化）、缓存不引入（P95 达标）——W6 不引入 Redis。**

- 附带口径：W4-03 审计策略 ACTIVE 缓存的多副本陈旧面，继续由「单副本部署约束」兜底（与限流同一约束），多副本启动时与本评估一并重启；
- 重启触发条件（任一）：多副本部署实际启动（限流 N× 放大 + 缓存失效面同时生效）、单租户 QPS 上探 >100 req/s（health ops_metrics 等热点读外置候选，`w6-loadtest.md` §4）、容量假设（设计 3.6 QPS 500）逼近；届时按 §3 方案对比与 §4.2 工作量估计重启评估。

---

（T17 交付物：仅评估，不实施；W6 决策输入。）
