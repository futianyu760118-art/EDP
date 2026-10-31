# AEOS 企业数据与证据中台 EDP 迭代行动计划（V1.3）

**配套方案：** `docs/AEOS_企业数据与证据中台_EDP_迭代版总体方案_V1.3.md`（修订稿，变更清单 C17–C22）  
**上游依据：** 《数据中台对接其他系统方案》（CDC 实时链路选型）、《AEOS_企业数据与证据中台_EDP_迭代行动计划_V1.2.md》
**执行基线：** V1.2 收官状态（40 任务完成 35；T28/T29/T31 待外部资源）
**目标：** 收口 V1.2 遗留（真实 ERP/MES 连接器 + 真实数据准入），并建设供应链系统 CDC+Kafka 实时链路，进入 EDP 数据接入的"实时化"阶段
**执行铁律：** 已实现模块不重建；Contract First；治理随闭环走；门禁未过不进下一阶段；冻结条款解冻必须书面裁决

---

# 一、目标与范围

| 维度 | 内容 |
| --- | --- |
| 总目标 | ① 真实 ERP/MES 连接器落地，真实数据跑通准入闭环；② 供应链 PostgreSQL 经 Debezium CDC → Kafka → 中台流消费端口 → RAW 管道，实现核心业务对象（订单/库存/工单/物料）实时入库 |
| 建设范围 | V1.2 遗留（T28/T29/T31）+ CDC+Kafka 实时链路（T41~T48）+ 主数据定时增量兜底双轨 |
| 解冻裁决 | V1.2 冻结条款"不引入 Kafka"**局部解冻**：仅引入 Kafka + Debezium Connector（CDC 专用），**不引入** Lakehouse / Flink 实时计算 / 重型流处理平台 / 向量集群 |
| 兼容性基线 | 流消费端口、topic 命名、SourceRecord 管道与数据库类型解耦；首期 PostgreSQL（pgoutput），MySQL（binlog）/ SQL Server（内置 CDC）为预留扩展项，换库仅换 Connector 配置 |
| 成功判据 | 第七节验收标准表全部通过 |

---

# 二、角色分工

| 角色 | 职责 |
| --- | --- |
| PM / 方案负责人 | 计划推进、门禁组织、解冻裁决组织、跨系统协调 |
| 平台负责人（EDP 后端） | stream 消费端口、RAW 落库管道、血缘 capture 分支 |
| 治理负责人 | CDC 数据入 RAW 后的清洗/准入复用确认、对账口径 |
| 连接器负责人 | 真实 ERP/MES Connector（V1.2 遗留）、stream 端口实现、主数据兜底双轨 |
| 供应链系统 DBA / 对接人（新增） | `wal_level=logical`、publication/slot、只读账号、主键与 updated_at 基线盘点 |
| MQ/CDC 运维负责人（新增） | Kafka/Debezium 部署、slot 堆积监控、topic 规范执行、故障演练 |
| 前端负责人 | 适配器管理页 stream 模式展示（如有页面需求） |
| QA / 验收 | CI Gate 扩展、延迟/幂等/对账实测、UAT 用例 |
| 数据 Owner（业务域代表） | 真实数据 A2/A3 抽检确认、口径确认 |

---

# 三、任务总表（按阶段直列，不分周）

## 阶段一：真实连接器收口（V1.2 遗留）

| 编号 | 任务 | 产出物 | 验收标准 | 依赖 | 责任 |
| --- | --- | --- | --- | --- | --- |
| T28 | ERP 真实 Connector | `edp_adapters` 真实 ERP 实现 | connect/healthcheck/pull/checkpoint/retry/replay 全实现；数据落 RAW | T03（V1.2 字段清单/接口文档） | 连接器 |
| T29 | MES 真实 Connector | 同上 | 同上 | T03（V1.2） | 连接器 |
| T31 | 真实数据跑通准入管道 | 抽样数据集（首链路对象） | A1–A4 全链路跑通，抽样双审留痕 | T28/T29 | 治理 |

**阶段验收：** 真实系统抽样数据 100% 走完 `RECEIVED → ARCHIVED`；UAT 复跑（V1.2 门禁复检中待真实数据的 #9 项补齐）。

## 阶段二：CDC+Kafka 实时链路（新）

技术基线：**Debezium（PostgreSQL Connector / pgoutput）→ Kafka → 中台 Python 流消费者（aiokafka）→ SourceRecord → RAW 管道**。

| 编号 | 任务 | 产出物 | 验收标准 | 依赖 | 责任 |
| --- | --- | --- | --- | --- | --- |
| T41 | 解冻裁决 | 书面裁决记录（"不引入 Kafka"条款局部解冻） | 解冻范围/理由/配套成本（运维/监控/对账）书面确认；仅限 CDC 专用，不得蔓延至实时计算/Lakehouse | 无 | PM |
| T42 | 供应链 PostgreSQL 对端条件 | 对端基线清单（wal_level/publication/slot/只读账号/主键+updated_at 盘点） | `wal_level=logical` 开启；publication+slot 建立；只读账号权限最小化；核心表白名单含主键与增量标识（无主键表先补） | T41 | 供应链 DBA + 连接器 |
| T43 | Debezium Connector 部署 | Kafka 单机/最小拓扑 + PostgreSQL Connector 配置 + topic 命名规范 | 表白名单（订单/库存/工单/物料变更）生效；topic 规范 `edp.{tenant}.{system}.{table}` 落地；变更事件含 before/after + `ts_ms`；slot 堆积监控 + 告警 | T42 | MQ/CDC 运维 |
| T44 | 中台流消费端口 | `edp_adapters` 新增 stream 端口（`on_event → SourceRecord`，与拉取端口并存） | `occurred_at` 取源系统时间戳（ts_ms，禁用 now()）；source_id 取业务主键；UUIDv5 幂等落库；消费失败进 DLQ 可重放；并发消费不丢不重（offset 语义） | T43 | 平台 + 连接器 |
| T45 | RAW 落库管道 | 消费 → RAW（raw_payload/batch_id/checksum）→ 复用 CLEAN/STANDARD/准入/血缘全链 | CDC 数据与拉取数据同管道同治理；血缘补 `source=capture` 分支；对账计数含 RAW | T44 | 平台 + 治理 |
| T46 | 主数据定时增量兜底 | 物料/供应商/客户等低频主数据保留 `fetch_incremental` 双轨 | 双轨同源同口径；CDC 漏数可由拉取补偿；兜底任务受 ops.tasks 互斥保护 | T45 | 连接器 |
| T47 | 对账与补数 | 对账任务 + 快照兜底补漏流程 | CDC 与拉取双轨对账偏差 0；中断恢复（Kafka/消费者故障演练）不丢不重；快照可重建 CDC 基线 | T46 | 治理 + 平台 |
| T48 | 验收与演练 | 延迟/幂等/对账实测报告 + 故障演练记录 | 订单/库存变更端到端延迟 P99 达标；0 重复落库；Kafka 中断恢复演练通过；源库负载不超标 | T47 | QA + MQ/CDC 运维 |
| T49 | 供应链主数据真实拉取连接器（回执 SPC-V2-INT-EDP-01 触发，2026-10-15 增补） | `edp_adapters` SPC 拉取实现（直连 `150.158.13.110:15432`） | 10 张主数据表可拉取入库；**自定义增量列 `update_time`**（非 updated_at）；无时间列表（scm_process/scm_organization）走全量；敏感字段拉取时排除（scm_supplier 联系方式四列 / scm_customer.credit_code）；owner_domain 按 T42 清单映射 | T42 回执 + T46 | 连接器 |
| T50 | 适配器前端可配置化（2026-10-15 增补，T49 泛化升级） | 迁移 0019 + DbPullAdapter + catalog CRUD + 动态注册表 + 前端弹窗字段 | 前端「新增适配器」真实可用：DB 拉取适配器零代码接入（DSN+表配置）；PUT/DELETE/test 探活；多租户 (tenant,name) 隔离 | T49 | 平台 + 前端 |
| T51 | 个人设置 + 适配器编辑/删除 UI（2026-10-15 增补） | /auth/profile + /auth/change-password + ProfilePage + 适配器行编辑/删除 | 个人资料/改密/主题偏好/会话权限四卡可用；改密强度校验 + 审计；动态适配器可编辑（GET 预填→PUT）与危险确认删除 | T50 | 平台 + 前端 |

**阶段验收：** 供应链订单/库存变更从源库 commit 到中台 RAW 可见，端到端可测、可对账、可恢复；主数据双轨对账偏差 0。

---

# 四、门禁清单

| 门禁 | 内容 | 通过条件 |
| --- | --- | --- |
| G0 | 架构门禁 | 边界/Owner/数据所有权冻结无异议，禁止跨域写表 |
| G1 | Contract 门禁 | 契约 schema 全部入库，CI 双门禁通过（stream 端口契约同过） |
| G2 | Data 门禁 | Result → Evidence 100% 可追溯，数据完整性/时效/一致性达标 |
| G3 | Closed Loop 门禁 | Decision → Action → Result → Verify → Evidence 全链可追踪 |
| G4 | Agent/EBMS 门禁 | EBMS/Agent 可用，Guard 有效，Trace 完整，official_only 生效 |
| **G5** | **实时链路门禁（新增）** | 端到端 P99 达标；幂等 0 重复；断点恢复演练通过；CDC 与拉取对账偏差 0；slot 堆积无告警积压 |

---

# 五、风险与应对

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 真实 ERP/MES 对接资源不到位（V1.2 延续） | T28/T29 阻塞 | 对接人与文档时间表锁定；允许先以接口模拟器完成联调框架 |
| PostgreSQL 逻辑复制权限拿不到（需 REPLICATION/超级用户） | T42 阻塞 | 提前与 DBA 书面确认；备选：只读库定时增量拉取兜底替代 |
| 源库无主键/无 updated_at 表 | CDC 增量难做稳 | T42 盘点先行；无主键表先补主键或排除出白名单 |
| Kafka/Debezium 运维成本 | 团队负担 | 单机/最小拓扑起步，仅 CDC 专用 topic；监控告警前置 |
| slot 堆积/源库 WAL 膨胀 | 源库性能风险 | slot 监控 + 消费延迟告警；超限自动处置流程 |
| 解冻范围蔓延（借机上 Flink/Lakehouse） | 范围失控 | G5 门禁限制：仅 Kafka+Debezium 专用，超出即否决 |
| CDC 与拉取双轨口径冲突 | 数据不一致 | occurred_at/主键统一语义；T47 对账任务兜底 |

---

# 六、完成定义（DoD）

每任务"完成"必须同时满足：

1. 代码合入对应 `feat/*` 分支并通过 CI（lint + 测试 + 契约双门禁）；
2. 迁移文件按版本规范编号，可 upgrade/downgrade；
3. 涉及接口的任务：契约 schema 已更新并过 CI；
4. 涉及状态/审核的任务：Event + Audit 留痕可演示；
5. 验收标准栏逐项有实测证据（截图/日志/测试结果），不允许"口头完成"。

---

# 七、进度跟踪表

| 任务 | 状态 | 阻塞项 | 备注 |
| --- | --- | --- | --- |
| T28 | 待外部资源 | V1.2 T03 字段清单/接口文档 | 延续 V1.2 |
| T29 | 待外部资源 | 同上 | 延续 V1.2 |
| T31 | 部分 | 依赖 T28/T29 | CSV 通道已先行验证 |
| T41 | 完成（待签） | 签字栏 | docs/V1.3_解冻裁决.md（V13-UNFREEZE-01，书面裁决 + 边界 + 回退条款） |
| T42 | dev 基线完成 | 真实对端确认（DBA） | docs/V1.3_对端条件清单.md；dev 等价物 pg-init-realtime/（wal_level=logical + scm_pub + 只读账号） |
| T43 | dev 基线完成 | 真实环境部署（运维） | deploy/docker-compose.realtime.yml（scm-db/kafka/connect）+ runbook 注册命令；Connector 注册命令入 ops-runbook |
| T44 | 完成 | - | 契约 realtime/debezium-event.schema（gate 14/14）+ edp_adapters.stream 纯端口（14 单测）+ 迁移 0018 realtime（4 集成测试）+ worker stream_consume（15 单测，aiokafka，PG 位点/DLQ/退避重试） |
| T45 | 完成 | - | process_record via/batch_id 通道标记（2 集成测试）；RAW batch_id=capture 坐标，事件/审计 via='capture' |
| T46 | 完成 | - | worker masterdata_job（7 单测）：逐租户×适配器 incremental + adapter_sync 同键互斥 |
| T47 | 完成 | - | ingest.reconcile_capture 双轨对账（2 集成测试）+ CLI reconcile-capture 子命令 |
| T48 | 完成（dev/CI 级） | 真实环境 P99/压测基线 | test_v13_realtime_e2e：真实 Kafka 容器全链（消费/DLQ/位点/幂等重放/断点续传不丢不重）；全量 770 passed；迁移升降级循环通过。真实 Debezium 链路（wal_level 快照→流式）待 T42 真实对端 + T43 真实部署后补验 |
| T49 | 完成（dev/演练级） | spc_db 生产账号 | 通用化并入 T50；spc_test 实跑验证 |
| T50 | 完成（dev/演练级） | 前端编辑/删除 UI 后续 | 适配器前端可配置化：迁移 0019（systems.adapter_config）+ 通用 DbPullAdapter（配置驱动，替换硬编码 SpcPullAdapter）+ catalog CRUD（POST/PUT/DELETE /systems + /test 探活）+ adapters_admin 动态注册表（(tenant,name) 键、RLS 隔离、静态 demo 回退）+ worker 主数据兜底 DB 装配；前端弹窗接入方式/DSN/表配置；契约导出+SDK 重生成+指纹绿；实跑：API 注册 spc → 清单 real/OK → 同步 → 测试连接 ok |
| T51 | 完成 | - | 个人设置（PUT /auth/profile + POST /auth/change-password + MeResponse 扩 display_name/email + ProfilePage 四卡 + 路由/入口）+ 适配器编辑弹窗（GET 预填→PUT）与危险确认删除；后端 793 + 前端 264 全绿；实跑冒烟通过 |

**执行基线（2026-10-14，分支 feat/v13-realtime）：** 后端 770 passed（725 基线 + 45 新增：单测 36 + 集成 9）；ruff / lint-imports 绿；schema-gate 14/14；alembic 0018 up/down/up 循环通过。**偏差记录：** ① realtimes.* 两表不启用 RLS（基础设施坐标，0018 docstring 裁定）；② Debezium Connector 本体不进 CI（消费侧以契约信封直注覆盖，Connector 由 dev compose/运维验证）；③ masterdata 兜底不落 ops.tasks 行（日志可观测，任务轨道后续评估）；④ stream 管道失败为头部阻塞重试（不丢不重优先，吞吐让位）。

**技术基线（并入方案）：** Debezium PostgreSQL Connector（pgoutput）→ Kafka（CDC 专用 topic）→ 中台 aiokafka 消费者 → `SourceRecord`（occurred_at=源 ts_ms）→ RAW → CLEAN/STANDARD → 准入 A1–A4 → OFFICIAL；兼容 MySQL/SQL Server 等常用库，仅 Connector 配置不同。**本行动计划与 V1.3 方案同库维护，任何变更必须同步修订两处。**
