# AEOS 企业数据与证据中台 EDP 迭代版总体方案 V1.3（修订稿）

**上位框架：** AEOS V7.2  
**中台编号：** M02  
**工程简称：** EDP / Data Foundation  
**方案版本：** V1.3  
**基准版本：** V1.2（本稿为 V1.2 的修订稿，未在本文列出的章节沿用 V1.2 原文）  
**修订依据：** 《数据中台对接其他系统方案》（CDC 实时链路选型）+《AEOS_企业数据与证据中台_EDP_迭代行动计划_V1.3.md》  
**目标版本阶段：** 从 L4 迭代至 L4+（数据接入实时化）

---

# 〇、修订说明

V1.2 收官后，出现两个新的确定性事实：

1. **供应链系统为自研系统，数据库为 PostgreSQL，具备开启逻辑复制的条件**，核心业务对象（订单/库存/工单/物料）存在实时入库诉求；
2. **V1.2 第十一节"轻版不引入 Kafka"的冻结条款与上述诉求冲突**，需局部解冻。

本修订稿变更清单如下（延续 V1.2 的 C 编号）：

| 编号 | 变更点 | 对应 V1.2 章节 | 性质 |
| --- | --- | --- | --- |
| C17 | "轻版不引入 Kafka"条款**局部解冻**：仅引入 Kafka + Debezium（CDC 专用），其余冻结项不变 | 第十一节 | 修订 |
| C18 | 新增 CDC 实时链路架构章节（技术基线 / 数据流 / topic 规范 / 兼容性基线 / 双轨对账） | 新增 | 新增 |
| C19 | Connector 优先级增补：供应链 PostgreSQL CDC 连接器（Debezium）列为第四项 | 第六节 | 修订 |
| C20 | 迭代计划增补第二阶段（W7 真实连接器收口 + W8 实时链路） | 第十二节 | 增补 |
| C21 | 验收标准增补实时链路指标；Gate 机制增补 G5 实时链路门禁 | 第十四 / 十五节 | 修订 |
| C22 | "需要立即停止的事项"增补防蔓延条款 | 第十七节 | 增补 |

---

# 一、解冻裁决：轻版 / 重版（修订 V1.2 第十一节）

V1.2 第十一节"轻版不引入：Kafka、Lakehouse、K8s、实时计算、向量集群、重型 MDM/图谱治理产品"自本版起**局部修订**为：

```text
轻版引入（新增，仅 CDC 专用）：
Kafka（仅承载 Debezium CDC 变更事件 topic，不做通用消息总线）
Debezium Connector（PostgreSQL Connector / pgoutput）

轻版仍不引入（冻结保持）：
Lakehouse、K8s、Flink 等实时计算平台、向量集群、重型 MDM/图谱治理产品
```

解冻边界条款：

1. Kafka 仅作为 CDC 变更事件的传输通道，topic 命名与消费侧契约由 EDP 冻结（第二节）；
2. 不得借 CDC 解冻引入流计算平台或变更数据湖架构；
3. 引入后运维成本（部署 / 监控 / 对账）由 MQ/CDC 运维负责人承担，slot 堆积监控前置；
4. 解冻为书面裁决（行动计划 T41），超出上述范围即回退冻结。

---

# 二、新增：CDC 实时链路架构

## 2.1 技术基线

```text
Debezium PostgreSQL Connector（pgoutput）
        ↓ 变更事件（before/after + ts_ms）
Kafka（CDC 专用 topic：edp.{tenant}.{system}.{table}）
        ↓ aiokafka 消费
EDP stream 端口（on_event → SourceRecord）
        ↓ occurred_at=源 ts_ms；source_id=业务主键；UUIDv5 幂等
RAW（raw_payload / batch_id / checksum）
        ↓ 复用既有管道
CLEAN → STANDARD → 准入 A1–A4 → OFFICIAL（血缘 source=capture 分支）
```

## 2.2 端口与时间语义

- `edp_adapters` 新增 **stream 端口**（`on_event`），与既有拉取端口（`fetch_full` / `fetch_incremental`）并存，不改动拉取侧任何既有实现；
- `occurred_at` 一律取源系统时间戳（Debezium `ts_ms`），**禁止 now() 生成**，与既有适配器端口约定一致（确定性重放）；
- `source_id` 取源表业务主键；落库沿用 UUIDv5 幂等语义，保证消费重放 0 重复；
- 消费失败进 DLQ 可重放；offset 提交语义保证不丢不重。

## 2.3 兼容性基线（多库解耦）

流消费端口、topic 命名、SourceRecord 管道与数据库类型**完全解耦**：

| 数据库 | Connector | 状态 |
| --- | --- | --- |
| PostgreSQL（供应链系统实际库） | Debezium PostgreSQL（pgoutput） | 首期部署 |
| MySQL | Debezium MySQL（binlog） | 预留扩展（仅 Connector 配置） |
| SQL Server | Debezium SQL Server（内置 CDC） | 预留扩展 |

## 2.4 双轨与对账

- **实时轨**：订单 / 库存 / 工单 / 物料等高频变更走 CDC 实时链路；
- **兜底轨**：物料 / 供应商 / 客户等低频主数据保留定时 `fetch_incremental` 拉取（ops.tasks 互斥保护）；
- **对账**：双轨同源同口径，定期对账偏差须为 0；CDC 漏数可由拉取轨补偿；快照可重建 CDC 基线。

---

# 三、修订：Connector 优先级（V1.2 第六节）

第一阶段交付范围更新为：

```text
1. ERP 真实 Connector（首链路必需，V1.2 延续，待外部资源）
2. MES 真实 Connector（首链路必需，V1.2 延续，待外部资源）
3. Excel / CSV 导入通道（V1.2 已完成，T30）
4. 供应链 PostgreSQL CDC Connector（Debezium，本版新增，实时链路）
```

明确后移第二阶段的（保持不变）：PLM、CRM、品质、财务、外部 API、设备数据。统一接口 `connect() / healthcheck() / pull() / normalize() / checkpoint() / retry() / replay()` 保留；stream 端口为独立新增接口，不与拉取接口合并。

---

# 四、增补：迭代计划第二阶段（V1.2 第十二节后）

V1.2 的 W1–W6 已收官。本版增补：

## W7：真实连接器收口（V1.2 遗留）

```text
T28 ERP 真实 Connector（connect/healthcheck/pull/checkpoint/retry/replay；数据落 RAW）
T29 MES 真实 Connector（同上）
T31 真实数据抽样跑通 A1–A4 准入管道，双审留痕；UAT 复跑补齐 V1.2 #9 项
```

## W8：CDC + Kafka 实时链路

```text
T41 解冻裁决（书面）
T42 供应链 PostgreSQL 对端条件（wal_level=logical / publication / slot / 只读账号 / 主键+updated_at 盘点）
T43 Debezium Connector 部署 + topic 规范 + slot 监控告警
T44 中台 stream 端口（on_event → SourceRecord；ts_ms 时间语义；UUIDv5 幂等；DLQ）
T45 RAW 落库管道（复用 CLEAN/STANDARD/准入/血缘全链；source=capture 分支）
T46 主数据定时增量兜底双轨
T47 对账与补数（双轨对账偏差 0；断点恢复不丢不重）
T48 验收与演练（P99 延迟 / 0 重复 / 故障演练 / 源库负载）
```

Gate：**G5**（实时链路门禁）

---

# 五、修订：验收标准增补（V1.2 第十四节）

V1.2 验收标准表 21 项保留，新增实时链路 6 项：

| 项目 | 标准 |
| --- | ---: |
| 订单/库存变更端到端延迟 P99 | 达标（数值随 T48 压测定基线） |
| CDC 事件幂等 | 100%（0 重复落库） |
| 断点恢复（Kafka/消费者故障演练） | 不丢不重 |
| CDC 与拉取双轨对账偏差 | 0 |
| Debezium slot 堆积告警积压 | 0 |
| 源库负载（wal_level=logical 开启后） | 不超标（指标随 T42 定基线） |

---

# 六、修订：Gate 机制增补（V1.2 第十五节）

架构门禁 G0–G4、数据准入门禁 A1–A4 保留原义，**新增 G5**：

```text
G5 实时链路门禁：
端到端 P99 达标；幂等 0 重复；断点恢复演练通过；
CDC 与拉取对账偏差 0；slot 堆积无告警积压；
stream 端口契约入 CI（与 G1 契约门禁同一轨道）。
```

---

# 七、修订：需要立即停止的事项（V1.2 第十七节）

原 15 条保留，增补：

```text
16. 借 CDC 解冻蔓延至 Flink / Lakehouse / 实时计算平台 / 通用消息总线改造；
17. CDC 事件绕过 RAW 留存直写 STANDARD / OFFICIAL（必须走 A1–A4 管道）；
18. 为 CDC 单独另建一套质量 / 对账 / 监控系统（复用 quality + ops.tasks + health 轨道）；
19. 对供应链生产库高频直连 SQL 轮询（CDC 上线后拉取轨仅限低频主数据）。
```
