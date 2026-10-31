# AEOS 企业数据与证据中台 EDP 迭代行动计划（V1.2 配套执行计划）

**配套方案：** `docs/AEOS_企业数据与证据中台_EDP_迭代版总体方案_V1.2.md`  
**执行基线：** 代码现状基线（2026-10-09 盘点，迁移至 `0013_w5_baseline`）  
**目标：** EDP 由 L2.5～L3 达到 L4，跑通"销售→订单→交付→应收"首条真实经营闭环（含数据准入 A1–A4）  
**执行铁律：** 已实现模块不重建；Contract First；治理随闭环走；门禁未过不进下一阶段

---

# 一、目标与范围

| 维度 | 内容 |
| --- | --- |
| 总目标 | L4：Decision + Action + Result 闭环 + 首链路数据可信（OFFICIAL 100%） |
| 建设范围 | 治理最小闭环（首链路关键对象）+ Result / Metric / Value / Period + 真实 ERP/MES 连接器 + official_only 改造 |
| 冻结范围 | 不重建 decisions/actions/traces/tools/ebms/memories；不引入 Kafka/Lakehouse/重型治理产品；不做自治中心；不做审批流引擎 |
| 成功判据 | V1.2 第十四节验收标准表 21 项全部通过 |

---

# 二、角色分工

| 角色 | 职责 |
| --- | --- |
| PM / 方案负责人 | 计划推进、门禁组织、跨系统协调、验收标准表核对 |
| 平台负责人（EDP 后端） | result / metric / value / period / lineage 模块与迁移 |
| 治理负责人 | RAW 四层、清洗/标准/分类/标签、A1–A4 状态机、审核工作台 |
| 连接器负责人 | ERP/MES 真实 Connector、Excel/CSV 通道、adapter 接口 |
| 前端负责人 | 数据准入工作台、result/metric 管理页 |
| QA / 验收 | CI Gate 扩展、UAT 用例、验收标准表核对 |
| 数据 Owner（业务域代表） | A2/A3 人工抽检与确认、首链路对象口径确认 |
| M01 Kernel 对接人 | Goal/KPI Owner 边界确认、下发快照口径 |
| EBMS 对接人 | EBMS 接口联调、official_only 语义确认 |

---

# 三、任务总表（按阶段直列，不分周）

## 阶段一：契约冻结 + 治理模型冻结 + 现状映射

| 编号 | 任务 | 产出物 | 验收标准 | 依赖 | 责任 |
| --- | --- | --- | --- | --- | --- |
| T01 | 冻结 System Boundary / Data Ownership / Goal-KPI Owner 边界 | 边界条款并入方案基线 | M01 对接人书面确认；`management.*` 表处置策略定稿 | 无 | PM + M01 |
| T02 | Contract Pack：object / event / result / evidence / governance schema | `contracts/object|event|result|evidence|governance/*.schema.json` | schema 通过 CI 校验；与 V1.2 第七/九节字段一致 | T01 | 平台 + 治理 |
| T03 | Data Source Inventory | mock 基线清单 + 真实 ERP/MES 字段清单获取计划 | 真实系统对接人/接口文档时间表落定（不依赖实际连通） | 无 | 连接器 |
| T04 | 四层模型 ↔ 现有 49 张表映射表 | 映射表文档（V1.2 第十六节格式） | 每张表现状 → 归属层 → 改造动作全覆盖 | T01 | 治理 |
| T05 | A1–A4 状态机 + 审核记录模型设计 | admission 模块 schema 设计稿 + 迁移草案 | 状态/事件/审计点完整；与 V1.2 第十五节命名一致 | T04 | 治理 |
| T06 | 清洗规则注册表 / 标准化字典 / 分类维度模型设计（首链路对象） | 规则字段、字典样例、Customer/Product/Material/Order 维度树 | 覆盖 V1.2 第三十四～三十六节最小集 | T04 | 治理 |
| T07 | CI 扩展：JSON Schema 校验门禁 | `.github/workflows` 增加 schema 校验 job | schema 变更未过 CI 阻断合入 | T02 | QA |

**门禁 G0/G1：** 边界冻结无异议；契约 schema 全部入库且 CI 通过。

## 阶段二：治理最小闭环（RAW → ARCHIVED，首链路关键对象）

| 编号 | 任务 | 产出物 | 验收标准 | 依赖 | 责任 |
| --- | --- | --- | --- | --- | --- |
| T08 | ingest RAW 改造 | `raw_records` 表迁移 + ingest 落 RAW（raw_payload / batch_id / checksum） | 适配器输出先留存后处理；RAW 不可覆盖；对账计数含 RAW | T04 | 治理 + 平台 |
| T09 | CLEAN / STANDARD 层实现 | 清洗规则执行引擎 + 标准层表 | 单域规则可版本化执行；auto_fix 留 before/after + rule 引用 | T06 | 治理 |
| T10 | 清洗规则注册表 API | `modules/governance/cleaning_rules` | 规则 CRUD + 版本 + 生效区间 | T06 | 治理 |
| T11 | 实体解析（别名映射） | `entity_resolution` 别名表 + 匹配服务 | "宁波恒剑光电"类样例归一到 Canonical Entity，别名保留 | T09 | 治理 |
| T12 | 分类 / 标签基础 | dimensions / taxonomy / tags 表 + API | 四个维度最小树可挂接对象 | T06 | 治理 |
| T13 | A2 本系统机器审（全量）+ 人工抽检 | 审核规则集 + 抽检工作台 | 机器审 PASS/WARNING/FAIL + quality_score；人工抽检留痕 | T09 | 治理 + 前端 |
| T14 | A3 管理机器复审 + 人工确认（关键对象） | 复审规则集 + 确认入口 | 跨系统一致性/证据完整性检查；仅 MANAGEMENT_APPROVED 转 OFFICIAL | T13 | 治理 + 前端 |
| T15 | A4 归档 + 状态机落地 | `modules/admission`（A1–A4 状态机、归档记录） | 状态变化产生 Event + Audit；归档含审核追溯字段 | T05 | 治理 |
| T16 | 质量门禁接入管道 | 清洗/准入环节 DQ 检查 | 低于门禁产生 `DataQuality.Exception` 并阻断 | T09 | 治理 |

**阶段验收：** mock 订单数据集 100% 走完 `RECEIVED → ARCHIVED`；血缘可回放（Source → Raw → Rule → Review → Official）。

## 阶段三：企业事实与结果层 + official_only 改造

| 编号 | 任务 | 产出物 | 验收标准 | 依赖 | 责任 |
| --- | --- | --- | --- | --- | --- |
| T17 | result 独立模块 | `modules/result`（models/router/service + 迁移） | 字段覆盖 V1.1 第七节 Result Contract；result 可挂 evidence_refs | T02 | 平台 |
| T18 | decisions/actions/traces/evidence 增 result_refs | 四个模块迁移 + 兼容改造 | 既有数据无损；Decision → Action → Result → Evidence 全链可查询 | T17 | 平台 |
| T19 | business_object 挂 official_version / lineage_id | registry 迁移 + ingest 写入 | OFFICIAL 对象可定位官方版本与血缘 | T15 | 平台 |
| T20 | lineage 模块 | `modules/lineage` + `contracts/governance/lineage.schema.json` | OFFICIAL 数据血缘 100% 可回放 | T15 | 治理 |
| T21 | ebms / tools 接入 official_only | 两模块查询层加过滤 | 默认仅读 OFFICIAL/ARCHIVED；越权读非 OFFICIAL = 0 | T15 | 平台 |
| T22 | 冻结 decision / action / trace schema | `contracts/decision|action|trace/*.schema.json` | 与已实现代码对账导出，不反向改代码语义 | T02 | 平台 |

**门禁 G2（数据门禁首段）：** Result → Evidence 100% 可追溯；mock 数据集全链追踪演示通过。

## 阶段四：Metric + Value + Period

| 编号 | 任务 | 产出物 | 验收标准 | 依赖 | 责任 |
| --- | --- | --- | --- | --- | --- |
| T23 | Metric Registry | `modules/metric`（复用 `management.kpi_*` 迁移映射） | definition_owner / definition_source / target_owner 齐全；口径版本化 | T01 | 平台 |
| T24 | Period Service | `modules/period` | AEOS 窗口（上月16日～当月15日）计算正确 + 6 类周期 | 无 | 平台 |
| T25 | Value Ledger 基础版 | `modules/value` + value-ledger schema | before/after/delta/evidence_refs 可追溯 | T17 | 平台 |
| T26 | EBMS 指标全量走 Registry | ebms 指标查询改造 | EBMS 前端零公式；指标均引用 metric_id | T23 | 平台 + EBMS |
| T27 | 冻结 metric / value schema | `contracts/metric|value/*.schema.json` | CI 通过 | T23 | 平台 |

**门禁 G3（闭环门禁首段）：** mock 全链 Result/Metric/Value 演示通过。

## 阶段五：真实连接器 + 准入规模验证 + 多维查询

| 编号 | 任务 | 产出物 | 验收标准 | 依赖 | 责任 |
| --- | --- | --- | --- | --- | --- |
| T28 | ERP 真实 Connector | `edp_adapters` 真实 ERP 实现 | connect/healthcheck/pull/checkpoint/retry/replay 全实现；数据落 RAW | T03 | 连接器 |
| T29 | MES 真实 Connector | 同上 | 同上 | T03 | 连接器 |
| T30 | Excel/CSV 导入通道 | 导入接口 + 模板校验 | 历史数据可批量入 RAW 并触发管道 | 无 | 连接器 |
| T31 | 真实数据跑通准入管道 | 抽样数据集（首链路对象） | A1–A4 全链路跑通，抽样双审留痕 | T28/T29/T30 | 治理 |
| T32 | worker 调度任务 | worker 增 profiling/清洗/机器审编排 | 沿用 ops.tasks + Redis 互斥；失败可重试重放 | T16 | 平台 |
| T33 | search_objects 多维查询 | tools 模块增 dimensions/classifications/tags 查询 | `official_only=true` 默认；无自由 SQL | T12 | 平台 |
| T34 | Agent Tool API OFFICIAL 校验 | tools 全端点回归 | Agent 读不到非 OFFICIAL 数据 | T21 | 平台 |

## 阶段六：经营闭环 UAT + 验收

| 编号 | 任务 | 产出物 | 验收标准 | 依赖 | 责任 |
| --- | --- | --- | --- | --- | --- |
| T35 | 全链 UAT 用例 | 用例集 + 执行记录 | 销售→订单→交付→应收全链，每环节 Result 均引用 OFFICIAL | T17/T23/T31 | QA |
| T36 | 六类异常跑通 | 异常场景演练记录（复用 drills） | 缺料/产能/交期/品质/出货/应收逾期全可形成 Decision→Action→Evidence | T35 | QA |
| T37 | G0–G4 门禁复检 | 门禁检查表 | 全部通过 | 全量 | PM |
| T38 | 验收标准表 21 项核对 | 指标实测数据 | 全部达标（P95 用压测数据） | 全量 | PM + QA |
| T39 | Owner Verify + Evidence 验收 | Owner 签字记录 | 每条正式事实有 Owner 确认 + Evidence | T35 | 数据 Owner |
| T40 | 文档与 runbook 更新 | ops-runbook / faq / 讲解文档更新 | 与实际系统一致 | 全量 | PM |

---

# 四、门禁清单

| 门禁 | 内容 | 通过条件 |
| --- | --- | --- |
| G0 | 架构门禁 | 边界/Owner/数据所有权冻结无异议，禁止跨域写表 |
| G1 | Contract 门禁 | 契约 schema 全部入库，CI 双门禁通过 |
| G2 | Data 门禁 | Result → Evidence 100% 可追溯，数据完整性/时效/一致性达标 |
| G3 | Closed Loop 门禁 | Decision → Action → Result → Verify → Evidence 全链可追踪 |
| G4 | Agent/EBMS 门禁 | EBMS/Agent 可用，Guard 有效，Trace 完整，official_only 生效 |

数据准入门禁 A1–A4 为管道内状态门（原始留存/本系统共审/管理复审/归档），由 admission 模块承载，与上述架构门禁区分。

---

# 五、风险与应对

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 真实 ERP/MES 对接资源不到位 | T28/T29 阻塞 | T03 即锁定对接人与文档时间表；允许先以接口模拟器完成联调框架 |
| A2/A3 人工审核人力不足 | 管道滞留 | 人工抽检制（非全量双审）；抽检比例与阈值随 T13 定稿 |
| 治理范围膨胀回"全量双审" | 计划崩盘 | 门禁检查是否新增首链路外对象，超出即否决 |
| `management.*` 迁移引发 EBMS 口径争议 | T23 返工 | T01 与 M01/EBMS 书面确认口径归属，争议升级至 Kernel 裁决 |
| schema 对账导出与既有代码不一致 | T22 返工 | T02 先导出一轮 decision/action/trace 现状 schema 预演 |
| mock 数据与真实数据差异大 | T31 返工 | T03 字段清单获取计划提前暴露差异 |

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
| T01 | 完成 | - | 边界条款 9 条 + Owner 基线 + management.* 处置（待 M01/EBMS 签署） |
| T02 | 完成 | - | 8 份域契约 schema（object/event/result/evidence/governance×4） |
| T03 | 完成 | - | mock 基线 4 适配器 + 真实系统字段清单获取计划（ERP/MES 对接待外部资源） |
| T04 | 完成 | - | 51 张表逐 schema 映射 + ingest RAW 改造清单 |
| T05 | 完成 | - | 15 态状态机 + admission_records 迁移草案 + 审核记录模型 |
| T06 | 完成 | - | 首批 10 规则 + 标准化字典 + 四维度最小树 |
| T07 | 完成 | - | schema-gate CI job + Makefile 目标，8/8 通过 |
| T08 | 完成 | - | 0014 迁移 + ingest RAW 留存（先留存后处理，checksum 幂等） |
| T09 | 完成 | - | 清洗引擎 10 rule_type + clean_records 留痕，接入管道 |
| T10 | 完成 | - | cleaning_rules 注册 API（版本化生效区间） |
| T11 | 完成 | - | entity_aliases API + ENTITY_RESOLUTION 归一 |
| T12 | 完成 | - | dimensions/taxonomies/tags + object_classifications API |
| T13 | 完成 | - | A2 机器预审 + 人工抽检（Human-Only，六结果） |
| T14 | 完成 | - | A3 机器复审 + 人工确认（APPROVED→OFFICIAL） |
| T15 | 完成 | - | admission 15 态状态机 + A4 归档（全链实测） |
| T16 | 完成 | - | FAIL→DataQuality.Exception 事件阻断（独立会话） |
| T17 | 完成 | - | result 独立模块（evidence_refs 必填 + RESULT links + verify） |
| T18 | 完成 | - | decisions/actions/traces 增 result_refs 列（evidence 走 links） |
| T19 | 完成 | - | business_objects 三列（layer_status/official_version/lineage_id）+ OFFICIAL/ARCHIVED 回写 |
| T20 | 完成 | - | lineage 模块（写入口=OFFICIAL 转换 + 读 API） |
| T21 | 完成 | - | tools 7 端点 official_only（默认 true，CURATED/ARCHIVED） |
| T22 | 完成 | - | contracts/decision|action|trace 三份 schema，schema-gate 11/11 |
| T23 | 完成 | - | Metric Registry（版本化生效区间 + 边界字段 + 计量值 upsert） |
| T24 | 完成 | - | Period Service（AEOS 窗口 16/15 边界 + 6 类周期） |
| T25 | 完成 | - | Value Ledger 基础版（delta 派生 + Human-Only 核验） |
| T26 | 完成 | - | EBMS 指标全量走 Registry（demo seed 双写 + _latest_kpis 切换） |
| T27 | 完成 | - | contracts/metric + value 契约，schema-gate 13/13 |
| T28 | 待外部资源 | - | 真实 ERP Connector——依赖 T03 字段清单/接口文档（未实施） |
| T29 | 待外部资源 | - | 真实 MES Connector——同上（未实施） |
| T30 | 完成 | - | Excel/CSV 导入通道（raw body + 模板校验 + 幂等重导） |
| T31 | 部分 | - | 真实数据准入以 CSV 通道先行验证；真实系统抽样待 T28/T29 |
| T32 | 完成 | - | worker admission 预审调度（60s 循环 + 独立事务隔离） |
| T33 | 完成 | - | search_objects 多维查询（object_tags 挂接 + 四维过滤） |
| T34 | 完成 | - | tools 全端点 official_only 回归 + search-objects 门禁测试 |
| T35 | 完成 | - | 全链 UAT 用例（test_v12_closed_loop：准入→Result→Decision→Action→归档） |
| T36 | 完成 | - | 六类异常跑通（缺料/产能/交期 + 品质/出货/应收构造，均入 exceptions） |
| T37 | 完成 | - | G0–G4 门禁复检（全绿，G5 冻结） |
| T38 | 完成 | - | 验收标准 21 项核对（20 通过 + 1 项主链通过/全量待真实数据） |
| T39 | 完成 | - | Owner Verify 系统核验落库 + 线下签字表 |
| T40 | 完成 | - | faq/ops-runbook 增补 V1.2 运维面 |

**本行动计划与 V1.2 方案同库维护，任何变更必须同步修订两处。**
