# EDP 数据平台系统设计文档（AEOS 第一阶段）· V2.0

## 文档信息

| 项目 | 内容 |
|---|---|
| 项目名称 | AEOS 自治企业操作系统 —— 第一阶段（Phase 1） |
| 文档主题 | EDP 数据与证据平台系统设计（含 EDP 控制台前端设计） |
| 文档编号 | EDP-DESIGN-P1-001 |
| 文档版本 | V2.0（重构定稿） |
| 编写人 | Fullstack A（EDP/Platform 负责人） |
| 评审对象 | PM / Tech Lead、Fullstack B（第 13 章评审） |
| 编写日期 | 2026-09-14 |
| 上游文档 | 《AEOS 一阶段执行计划》（PDF，唯一需求上游）、《运营总览 等 26 个设计》（高保真原型，`原型设计/pages/`） |
| 配套文档 | 《EDP 数据平台开发计划_一阶段》（任务分解、里程碑与风险） |

### 修订记录

| 版本 | 日期 | 修订人 | 修订说明 |
|---|---|---|---|
| V1.0 | 2026-09-09 | Fullstack A | 创建：总体架构、数据流、数据模型、API 设计、关键机制、安全、可靠性设计；附录含完整 DDL 与全量 API 契约 |
| V1.1~V3.0（内部稿） | 2026-09-09 ~ 09-13 | Fullstack A | 内部评审迭代：多租户全量落地（行级 RLS）、Patroni HA、前端设计草案并入；历史全文见旧版归档（`EDP数据平台系统设计文档_V1.0.md`） |
| V2.0 | 2026-09-14 | Fullstack A | **重构定稿**：以《AEOS 一阶段执行计划》为唯一上游重新推导全文——新增 1.4 需求溯源（PDF 条款 → 设计决策映射）；结构重组、措辞重写；技术决策沿用已评审结论（多租户全表 tenant_id + RLS、Patroni HA + PITR、15 Schema/48 表、Outbox/checksum/状态机）；第 13 章承载 EDP 控制台前端设计（26 个高保真原型为视觉与交互基线）；EBMS 明确为范围外（EDP 仅提供 B.9 查询契约）；配套开发计划另行发布 |

---

## 1. 概述

### 1.1 AEOS 第一阶段使命与 EDP 的角色

《AEOS 一阶段执行计划》确定第一阶段（6 周）的使命：**以「交付风险闭环」验证整个自治架构**——Agent 中枢统一驱动交付、销售、研发等多个专业自治能力，在真实企业数据上发现问题、给出决策建议、生成行动任务并验证结果；第 4 周形成端到端示范闭环（系统识别订单交付风险 → 生成决策案例 → 人工审批 → 执行并验证），第 5~6 周强化可观测性与安全机制并在真实数据上试运行，满足 Go/No-Go 验收指标。

AEOS 第一阶段由四个协同件构成：

| 协同件 | 职责（AEOS 计划 §2） | 承建方 |
|---|---|---|
| Agent 中枢 | 能力注册、Agent 运行时、工具执行、Trace/HITL、权限 Guard | Agent 中枢负责人 |
| 专业自治能力 | Delivery.OrderRisk、Sales.OrderQuality、R&D.ProductReadiness | Agent 中枢 + 算法 |
| **EDP（本文档）** | **统一的事件/证据存储：对象注册、事件入库、证据入库、审计、数据供给** | Fullstack A |
| EBMS | 管理层界面：REPORT / EXCEPTION / DECISION / TODO / DIALOGUE | Fullstack B |

EDP（Evidence & Data Platform，数据与证据平台）在其中是**统一数据底座**：

- 为三大自治能力提供标准化、受控的数据供给（Read-Only 工具 API）；
- 为能力结果回流、决策案例、行动任务提供事件与证据存储；
- 为 EBMS 提供报表、异常、待决、待办、证据钻取的全部查询数据；
- 落实 AEOS 三大架构原则：**事件驱动、证据留痕、权限受控**；
- 承接闭环验收的硬性要求：链路 `Result → Exception → Decision → Evidence → 源数据` 100% 可逆向追溯。

EDP **不复制源业务库**，只存储：统一对象注册、事件历史、证据快照、决策/行动记录、学习记忆与 Agent 执行日志（Trace）。

### 1.2 建设目标（第一阶段，6 周）

1. 建成 PostgreSQL 16 多租户数据库（15 个 Schema、行级 RLS 隔离）与版本化迁移体系；
2. 交付核心存储服务：对象注册、事件入库、证据存储（checksum 防篡改）、审计日志；
3. 交付 ERP/MES/PLM 适配器（Mock 可切换真实接口）与数据转换管道；
4. 交付 Agent 数据工具 API（全 Read-Only，支撑三大能力）与 EBMS 查询 API；
5. 交付多租户运营平面：租户生命周期、成员、配额与限流（支撑后续对外 SaaS 化）；
6. 交付高可用基座（Patroni 主从 HA + PITR）、数据质量监控、备份恢复，支撑验收门控；
7. **交付 EDP 控制台前端**（第 13 章）：21 个主页面 / 约 30 条路由，以 26 个高保真原型为视觉与交互基线，覆盖数据工作台、运维监控、平台配置三域，支撑 M2 链路演示与 M4 闭环演示。

### 1.3 范围边界

| 范围内 | 范围外（归属方） |
|---|---|
| 数据库架构与核心存储服务（对象/事件/证据/审计/决策/行动/记忆/Trace） | Agent Runtime、LLM 调用、HITL 审批流（Agent 中枢） |
| ERP/MES/PLM 数据接入与转换（适配器 + 管道） | EBMS 管理界面 REPORT/EXCEPTION/DECISION/TODO/DIALOGUE（Fullstack B；EDP 仅提供附录 B.9 查询契约） |
| 数据供给与查询 API（Agent 工具 / EBMS 查询 / 控制台） | 业务风险算法（Agent 中枢/算法工程师） |
| **EDP 控制台前端（运维/运营平面，第 13 章）** | 异地容灾（第二阶段） |
| 数据质量、审计、备份恢复 | — |

> **前端范围声明**：本文档第 13 章仅覆盖 **EDP 控制台**（EDP 自带的运维/运营 Web 前端）。EBMS 是面向经营者的独立前端，由 Fullstack B 承建，其与 EDP 的全部交互经附录 B.9 契约完成，页面设计不在本文档范围。

### 1.4 需求溯源（AEOS 计划 → EDP 设计）

本设计的每一条主线均可回溯至《AEOS 一阶段执行计划》的具体条款：

| AEOS 计划条款 | 要求摘要 | EDP 设计承接 |
|---|---|---|
| §1 域与对象契约（BusinessObject/Event/Evidence/Result/DecisionCase/DecisionRecord/Action/Capability/Skill/Trace） | W1 冻结核心对象定义 | 第 5 章数据模型 + 附录 A DDL（对象即表、契约即列） |
| §2 Agent 中枢与 EDP 总览 | EDP 是统一事件/证据存储；经 BusinessObject ID 关联，不复制原始业务库 | 1.1 定位、4.1 数据流、5.2 对象注册锚点 |
| §3 第一阶段交付物 | EDP 基础表、事件入库、证据入库、审计、适配器；闭环可逆向追溯 | 1.2 建设目标、7.6 证据链逆向追溯、附录 C.2/C.3 时序 |
| §4 团队与职责（全栈 A） | 数据库架构、System/Capability Registry、对象注册、事件/证据入库、审计、ERP/MES/PLM 适配器 | 第 2/4/6 章模块划分、B.2/B.3/B.4/B.7 |
| §5 周任务总览 W1~W6 | Schema 建设 → 适配器 → 能力数据可用 → 闭环 → 质量/备份 → 试运行 | 第 13 章配套开发计划的里程碑 M1~M6 |
| §6 Agent 中枢接口与运行规范 | Capability Registry API、工具接口（如 `GET /api/orders/{id}`）只读、Trace Schema、HITL 审批意见入证据 | B.7 注册中心、B.8 Agent 数据工具（Read-Only）、A.9 trace、7.5 审批意见落证据链 |
| §7 EDP 数据模型 | PostgreSQL 多 Schema（platform/master/management/六业务域/event/evidence/decision/action/memory）、全表多租户标识与审计字段 | 第 5 章 15 Schema（在计划 13 Schema 基础上将 action、trace 独立成域）、3.4 全表 RLS |
| §8 EBMS 关键页面与 API | REPORT/EXCEPTION/TOP DECISION/TODO/DIALOGUE/EVIDENCE 及 `GET /reports/summary` 等接口 | 附录 B.9 EBMS 查询契约（EDP 侧实现） |
| §9 验收标准（Go/No-Go） | 覆盖度 ≥95%、追溯 100%、召回 ≥80%、Action 闭环 ≥90%、越权 =0、审计 100%、响应 <2s | 第 11 章指标映射 |
| §10 核心评估测试用例（30+） | 缺料/供应商延迟/新品未验证/数据不一致等场景数据 | EDP-016 演示数据 seed（10 类场景可重放，第 13 章演示支撑） |
| §11 风险与缓解 | 数据质量、模型漂移、耦合过紧（坚持 Modular Monolith）、AI 越权、评估不充分 | 2.2 架构策略、8.3 Agent 只读三层纵深、9.3 质量监控、10.1 Mock 降级 |
| §12/§13 首周任务与最小交付物 | Agent 中枢 W1 接口骨架；EDP 侧 Schema/ER 图/契约文档 | M1 契约冻结门控（开发计划第 2 章） |

### 1.5 术语表

| 术语 | 定义 |
|---|---|
| BusinessObject | 统一业务对象注册元表，跨系统记录以 `object_id`（UUID）关联 |
| Event | 业务事件流水，由源系统操作或能力结果回流触发 |
| Evidence | 决策或 Agent 输出所依赖的原始数据快照，带 checksum 防篡改指纹 |
| 证据链 | Result → Exception/Decision → Evidence → 源记录 的完整可逆向追溯路径 |
| Outbox | 事务性发件箱：事件与业务数据同事务写入，异步分发，保证不丢不错序 |
| 三元组 | 一次同步落库的 (BusinessObject, Event, Evidence) 组合 |
| 能力（Capability） | 专业自治系统暴露的结构化服务单元，如 `Delivery.OrderRisk` |
| HITL | Human-In-The-Loop，关键操作前人工审批 |
| Guard | 权限与策略检查点，含 Human-Only / Read-Only / AutoAllowed 分级 |
| Mock 适配器 | 与真实适配器同接口的模拟数据源，用于外部接口不可得时降级开发 |
| EDP 控制台 | EDP 自带的运维/运营 Web 前端（第 13 章），面向平台运营与租户管理员 |
| EBMS | 管理层经营界面（REPORT/EXCEPTION/DECISION/TODO/DIALOGUE），Fullstack B 承建，非本文档范围 |
| 设计令牌 | 前端设计系统中的命名视觉变量（`--edp-*` CSS 自定义属性），承载颜色/圆角/阴影等主题值 |

### 1.6 约定

- 时间统一使用 UTC 存储（`TIMESTAMPTZ`），展示层转换时区；
- 标识符：主键用 UUID（v4 由服务端生成，v5 确定性生成用于幂等场景）；
- 枚举值用 `TEXT + CHECK` 约束而非原生 ENUM，便于迁移演进；
- **多租户**：除 `platform.tenants` 外，所有表均含 `tenant_id UUID NOT NULL`（对齐 AEOS 计划"所有表均支持多租户标识"声明），并启用 RLS；
- 所有业务表均带审计字段 `created_by/created_at/updated_by/updated_at`（对齐 AEOS 计划 §7 审计字段要求）；
- API 路径统一前缀 `/api/v1`，分页统一游标式（`limit` + `cursor`）。

---

## 2. 总体架构

### 2.1 架构图

```
┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌──────────────┐
│ 租户A ERP    │   │ 租户A MES    │   │ 租户B ERP    │   │ …按租户配置   │
└──────┬──────┘   └──────┬──────┘   └──────┬──────┘   └──────────────┘
       │  REST/文件(Mock可切换)·租户级连接配置        │
       ▼                ▼                        ▼
┌─────────────────────────────────────────────────────────┐
│                 EDP 数据与证据平台（多租户）                 │
│  ┌─────────────────────────────────────────────────┐    │
│  │ 网关（nginx）：TLS 终结 / 租户限流 / 负载均衡         │    │
│  └───────────────────────┬─────────────────────────┘    │
│  ┌───────────────────────▼─────────────────────────┐    │
│  │ 接入层：适配器框架（端口-适配器，注册表驱动）           │    │
│  │   ErpAdapter / MesAdapter / PlmAdapter（租户级配置）│    │
│  │   MockXxxAdapter（同接口，配置切换）                  │    │
│  └───────────────────────┬─────────────────────────┘    │
│  ┌───────────────────────▼─────────────────────────┐    │
│  │ 转换管道：源记录 → 对象注册 → 事件+证据落库            │    │
│  │ （单事务三元组 + Outbox，携带租户上下文）              │    │
│  └───────────────────────┬─────────────────────────┘    │
│  ┌───────────────────────▼─────────────────────────┐    │
│  │ 存储层：PostgreSQL 16（15 Schema · 全表 tenant_id    │    │
│  │ + RLS 行级隔离；Patroni 主从 HA，WAL 归档 PITR）      │    │
│  └───────────────────────┬─────────────────────────┘    │
│  ┌───────────────────────▼─────────────────────────┐    │
│  │ 服务层（FastAPI 模块化单体 ×2 副本，无状态）            │    │
│  │  租户管理│对象注册│事件│证据│审计│注册中心│决策/行动      │    │
│  │  Agent 数据工具(Read-Only)│EBMS 查询│适配器运维        │    │
│  │  数据质量│健康检查                                    │    │
│  └─────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────┐    │
│  │ 后台 Worker ×2：Outbox 分发│数据质量任务│备份调度        │    │
│  │ （按租户循环执行，租户级配额约束）                      │    │
│  └─────────────────────────────────────────────────┘    │
└──────┬──────────────┬──────────────┬─────────────────────┐
       │ Read-Only     │ JWT 查询/审批  │ API Key 写入          │ JWT 运维/运营
       ▼              ▼              ▼                     ▼
┌─────────────┐  ┌─────────────┐  ┌─────────────┐   ┌──────────────┐
│  Agent 中枢   │  │  EBMS 管理界面 │  │  EDP 控制台   │   │ 运维 CLI/脚本  │
│ 三大能力+工具  │  │ 报表/异常/决策 │  │ 前端(第13章)   │   │ health/备份    │
└─────────────┘  └─────────────┘  └─────────────┘   └──────────────┘
```

> 交付形态：`DEPLOY_MODE=shared`（默认，≤50 租户共享一套部署）/ `dedicated`（大客户/合规严客户独立部署）——同一镜像、同一代码，仅部署编排不同（见 3.1/9.5）。

### 2.2 架构策略

| 项 | 方案 | 说明 |
|---|---|---|
| 架构风格 | 模块化单体（Modular Monolith） | 对齐 AEOS 计划 §11 风险缓解"第一阶段坚持单体应用 + Schema 分区"；模块间仅经内部服务接口调用，禁止跨模块直连对方表；应用无状态、可水平扩副本 |
| 语言/框架 | Python 3.12 + FastAPI | 与 Agent 工程生态亲和；FastAPI 自带 OpenAPI，契约即代码 |
| ORM/迁移 | SQLAlchemy 2.0 + Alembic | 每 Schema 独立迁移脚本目录，版本化可回滚；DDL 变更必须携带 RLS 同步策略 |
| 数据库 | PostgreSQL 16 多 Schema + 行级 RLS | 按域隔离（对齐 AEOS 计划 §7 多 Schema 模式）；JSONB 支撑半结构化事件/证据；RLS 强制租户隔离（第 3 章） |
| 多租户 | 全表 `tenant_id` + RLS；共享部署为主，同代码支持独立库交付 | 见第 3 章 |
| 事件机制 | 事务性 Outbox + 进程内分发 | 对齐"所有触发均通过事件总线"，Phase 1 不引入消息队列；Outbox 表保留升级为 MQ 的接缝 |
| 安全机制 | JWT + API Key 双轨认证（均绑定租户），RBAC + Guard 分级 + 审计 | Agent 仅可持 Read-Only scope 密钥取数（对齐 §6 工具接口规范、§11 AI 越权缓解） |
| 高可用 | Patroni 主从流复制 + 自动故障转移；WAL 归档 PITR | RPO≈0（同步确认可配）/分钟级，RTO < 5min，见 9.1 |
| 前端（EDP 控制台） | React 18 + Ant Design 5（Token 主题）+ TanStack Query + Vite；pnpm monorepo（web / api-sdk / shared） | 与 26 个高保真原型对齐（第 13 章）；api-sdk 由 OpenAPI 自动生成，契约 SHA256 进 CI；Storybook 视觉回归 + Playwright E2E + MSW mock |
| 部署 | Docker Compose 容器化；`DEPLOY_MODE=shared\|dedicated` | 服务：`gateway`、`api×2`（backend/apps/api）、`worker×2`（backend/apps/worker）、`db-ha`（Patroni 集群）、`web`（Nginx 托管控制台静态资源，frontend/apps/web 产物）；一键环境，支持快速联调与回滚 |

### 2.3 仓库布局与模块划分（双工作区根）

单仓库、**双工作区根**布局：仓库根只保留跨端中立目录（contracts/deploy/docs），`backend/` 与 `frontend/` 各为独立工作区根。目录边界同时承载四种边界——**语言**（Python/TS）、**工具链**（uv/pnpm）、**团队**（Fullstack A / B）、**CI 过滤器**（`backend/**` / `frontend/**`）。各工作区内 `apps/` = 可部署进程，`packages/` = 库。

> 分包只是**工程与进程边界**，不改变模块化单体语义：业务模块唯一实现在 `backend/apps/api/.../modules`；`adapters` 是实现 `api` 端口的库；`worker` 是后台进程入口。

#### 2.3.1 仓库根

```
（仓库根）
├── backend/                     # uv workspace 根（见 2.3.2）
├── frontend/                    # pnpm workspace 根（见 2.3.3）
├── contracts/                   # 前后端契约中立场（见 2.3.4）
├── deploy/                      # docker-compose（shared/dedicated 两套编排）、备份与 HA 脚本、发布/回滚
└── docs/                        # 本文档、运维手册、演练手册
```

#### 2.3.2 backend/（uv workspace）

```
backend/
├── pyproject.toml               # uv workspace：members = ["apps/*", "packages/*"]
├── apps/
│   ├── api/                     # FastAPI 应用（唯一 API 进程，×2 副本）
│   │   └── edp_api/
│   │       ├── main.py          # 入口：路由装配、中间件链（租户上下文/审计/限流）、适配器注册（组合根）
│   │       ├── core/            # 共享内核——模块间唯一公共依赖，禁止反向依赖任何 module
│   │       │   ├── config.py    #   Pydantic Settings（环境变量注入）
│   │       │   ├── db.py        #   AsyncSession 工厂、SET LOCAL app.tenant_id、连接池
│   │       │   ├── security/    #   JWT/API Key 双轨校验、RBAC 权限矩阵、Guard 分级（8.2）
│   │       │   ├── pagination.py#   游标分页编解码（limit + cursor）
│   │       │   ├── errors.py    #   统一错误结构 + 13 种错误码（B.0）
│   │       │   ├── audit.py     #   审计切面：中间件 + 服务层装饰器（8.4）
│   │       │   ├── events.py    #   进程内事件总线（Outbox 订阅者注册，7.2）
│   │       │   └── ports.py     #   端口（Protocol）：SourceAdapter、AdapterRegistry ...
│   │       └── modules/         # 13 个业务模块（一一对应 Schema，见下）
│   │           ├── tenantmgmt/  #   租户生命周期、成员、配额、使用量、限流策略（横切基础）
│   │           ├── platform/    #   用户/组织/角色/权限/API Key/系统与能力注册/审计
│   │           ├── registry/    #   master：对象注册与主数据
│   │           ├── events/      #   event：事件入库、查询、Outbox 写入
│   │           ├── evidence/    #   evidence：证据写入、checksum、verify、链查询
│   │           ├── decision/    #   decision：案例与记录（Human-Only Guard）
│   │           ├── action/      #   action：9 态状态机（7.5）
│   │           ├── memory/      #   memory：候选记忆
│   │           ├── management/  #   management：目标/KPI/硬性约束（EBMS 预聚合来源）
│   │           ├── tracestore/  #   trace：Trace + tool_calls 存储（三层留痕）
│   │           ├── domains/     #   六业务域快照：sales/ delivery/ rd/ support/ quality/ finance/ 各一子包
│   │           ├── toolapi/     #   Agent 数据工具（Read-Only 强约束，仅 GET，8.3）
│   │           └── ebms/        #   EBMS 查询聚合（只读，B.9）
│   └── worker/                  # 后台进程（×2 副本，SKIP LOCKED 天然安全）
│       └── edp_worker/
│           ├── main.py          # 进程入口
│           ├── scheduler.py     # 按租户循环：单租户超时让出 + 异常隔离（3.3）
│           ├── outbox_dispatch.py   # Outbox 分发：SKIP LOCKED + 指数退避（7.2）
│           ├── quality_tasks.py     # 对账/覆盖率/孤儿/checksum 抽检（9.3）
│           └── backup.py        # 备份调度与可恢复性验证（9.2/9.6）
├── packages/
│   └── adapters/                # 库：端口实现（依赖方向 adapters → api）
│       └── edp_adapters/
│           ├── base.py          # SourceRecord 标准结构 + AdapterRegistry 接入
│           ├── pipeline.py      # 转换管道：三元组单事务落库（4.3）
│           ├── erp/             # ErpMockAdapter / ErpRestAdapter（租户级 adapter_mode 切换）
│           ├── mes/             # MesMockAdapter / MesRestAdapter
│           └── plm/             # PlmMockAdapter / PlmRestAdapter
├── migrations/                  # Alembic（按 schema 分版本链，RLS 策略随 DDL；edp_migrator 执行）
└── tests/                       # 集成测试（testcontainers 起 PG；跨租户隔离用例集为 CI 门禁）
```

**模块内统一结构**（13 个 modules 逐一遵循，消除自由发挥空间）：

```
modules/<name>/
├── router.py        # 路由层：参数校验、权限声明、调 service（薄，无业务逻辑）
├── service.py       # 业务逻辑：模块对外唯一接口，其他模块只允许 import 这里
├── models.py        # SQLAlchemy ORM：本模块表的唯一持有者
├── schemas.py       # Pydantic 请求/响应 DTO
└── dependencies.py  # 模块级 FastAPI 依赖（权限、分页、租户上下文）
```

**依赖规则**（CI 以 import-linter 强制）：

1. `core` 是共享内核：modules → core 单向依赖；`core` 不 import 任何 module；
2. 模块间只许调用对方 `service.py` 公开方法，禁止触碰对方 `models.py`/`router.py`（对齐"禁止跨模块直连对方表"）；
3. `toolapi`/`ebms` 只读调用各域模块查询接口；`tenantmgmt` 为横切基础（其余模块经 `core` 获取租户上下文）；
4. 端口反转：`adapters`（packages）依赖 `api` 实现 `core.ports`；业务代码只经 `AdapterRegistry` 触达适配器，直接 import `edp_adapters` 的唯一例外是组合根（`apps/*/main.py` 的启动注册）；
5. `worker` → `api` + `adapters`，且只经各模块 service 访问数据。

#### 2.3.3 frontend/（pnpm workspace）

```
frontend/
├── pnpm-workspace.yaml           # packages: ["apps/*", "packages/*"]
├── apps/
│   └── web/                      # EDP 控制台（构建产物即部署单元，第 13 章）
│       └── src/
│           ├── app/              # 入口、路由装配、Provider（Query/Theme/Tenant）、全局错误页
│           ├── shell/            # 壳层：Sidebar/Topbar/CommandPalette/租户切换（13.5）
│           ├── features/         # 特性域（与 13.3 路由一一对应）
│           │   ├── overview/     #   运营总览
│           │   ├── registry/     #   业务对象
│           │   ├── events/       #   事件流（含回放向导）
│           │   ├── evidence/     #   证据库（含链图/重索引向导）
│           │   ├── quality/      #   数据质量
│           │   ├── audit/        #   审计日志
│           │   ├── adapters/     #   适配器管理
│           │   ├── systems/      #   系统健康
│           │   ├── tenants/      #   租户管理（列表/详情/成员/配额）
│           │   ├── cases/        #   闭环案例（M4 关键）
│           │   ├── decisions/    #   决策
│           │   ├── actions/      #   行动（9 态状态机）
│           │   ├── tools/ traces/ memory/ drills/   # Agent 工具/Trace/候选记忆/演练回放
│           │   ├── auth/         #   登录/会话
│           │   └── search/       #   全局搜索
│           ├── components/       # 17 条通用模式封装（13.7）
│           └── lib/              # Query client、错误码映射（13.9.2）、格式化工具
└── packages/
    ├── api-sdk/                  # 库：契约消费端
    │   └── src/
    │       ├── generated/        #   openapi-typescript 生成产物（禁止手改）
    │       ├── client.ts         #   fetch 封装（Cookie/CSRF）
    │       └── interceptors.ts   #   401 刷新单飞/429 退避/TENANT_SUSPENDED 横幅
    └── shared/                   # 库：跨页面复用（不依赖 web）
        └── src/
            ├── tokens/           #   设计令牌 TS 常量 → Antd ConfigProvider（13.4）
            ├── enums/            #   枚举/展示名映射/短 ID 规则（13.4.4）
            ├── permissions/      #   权限矩阵与导航可见性定义（13.8）
            └── components/       #   与框架无关的纯展示组件（Storybook 承载）
```

**feature 内统一结构**：`pages/`（路由页）+ `components/`（页面级组件）+ `hooks/`（useXxx 查询，TanStack Query）+ `api.ts`（本域接口封装，仅 import `api-sdk` 类型）。

#### 2.3.4 contracts/（契约中立场）

```
contracts/
├── openapi.json                  # M1 冻结快照（后端 /openapi.json 导出，评审签署物）
├── openapi.sha256                # 契约指纹——CI 双门禁比对基准（13.9.1）
└── README.md                     # 契约变更流程（冻结后变更走 PR + Tech Lead 评审 + SDK 重生成三联动）
```

前后端各自的 CI 门禁都以 `contracts/` 为准：后端导出契约与快照不符 → 后端 PR 失败；`api-sdk` 与快照指纹不符 → 前端 PR 失败。两端发布节奏解耦，契约演进留痕。

---

## 3. 多租户架构设计

### 3.1 隔离模型与交付形态

| 层面 | 决策 | 说明 |
|---|---|---|
| 数据隔离 | **共享库 + 全表 `tenant_id` + PostgreSQL RLS**（行级强制） | 单套部署支撑 ≤50 租户；RLS 作为最后防线，应用层缺陷不致跨租户泄露 |
| 交付形态 | `DEPLOY_MODE=shared\|dedicated`，**同一镜像、同一代码** | 默认共享部署；大客户/合规严客户用独立库（独立 Patroni 集群），仅部署编排与配置不同，不维护代码分支 |
| 租户内组织 | 租户内保留 `organizations` 层级 | 满足集团多组织场景，不再作为隔离边界 |
| 演进路线 | ≤50 租户单集群 → 超出后大客户迁 dedicated、长尾分片（`tenant_shard` 预留字段） | 避免过早分片复杂度 |

**为什么不是 Schema-per-tenant / DB-per-tenant**：迁移成本随租户数线性增长（Alembic ×N）、跨租户运营统计复杂、连接池膨胀；行级 RLS + 独立库兜底在 ≤50 租户规模下隔离强度与成本最优。

### 3.2 租户模型与生命周期

```
platform.tenants（租户主表，平台根实体，自身无 tenant_id）
   ├─ tenant_members   租户成员（用户↔租户绑定，含租户内角色）
   ├─ tenant_quotas    配额（API 速率/存储/事件量/连接数）
   └─ tenant_usage_daily  使用量统计（计量基础，Phase 2 计费可直接消费）

生命周期：PROVISIONING → ACTIVE ⇄ SUSPENDED → CANCELLED（数据保留 30 天后归档清理）
```

- **PROVISIONING**：建租户记录 + 初始管理员 + 默认配额 + 种子数据（角色/权限/KPI 定义），原子开通；
- **SUSPENDED**：欠费/违规暂停——API 层即时拒绝（403 `TENANT_SUSPENDED`），数据保留，Worker 停止该租户同步任务；可恢复；
- **CANCELLED**：注销——先导出租户全量数据（逻辑备份），30 天保留期后清理；删除动作仅限平台 ADMIN，双人复核；
- 内部自用租户：初始化时创建默认租户（如 `default`），Phase 1 以单租户运行但全链路带租户上下文。

### 3.3 租户上下文传播（请求全链路）

```
请求进入
  │ ① 网关：按 Host/路由解析（仅 dedicated 形态需要）
  ▼
② 认证中间件：JWT claims.tenant_id / API Key 绑定的 tenant_id
  │   - 校验租户状态（SUSPENDED→403 TENANT_SUSPENDED）
  │   - 校验 principal 与租户匹配（不匹配→403 TENANT_FORBIDDEN + 审计）
  ▼
③ FastAPI 依赖注入 TenantContext（request.state.tenant）
  ▼
④ DB 会话：每个事务开始时执行
  │   SET LOCAL app.tenant_id = '<uuid>'
  │   （连接池复用安全：SET LOCAL 事务级生效，事务结束自动失效）
  ▼
⑤ RLS 策略自动过滤：所有带 tenant_id 的表，读写均限于本租户行
  ▼
⑥ 审计/日志/Trace：全部携带 tenant_id 与 request_id
```

- **后台 Worker**：按租户循环（租户列表 → 逐租户开事务并 `SET LOCAL`），任一租户任务异常不影响其他租户（try/except 隔离 + 继续下一租户）；
- **特权旁路**：仅迁移账号（`edp_migrator`，非应用账号）持 `BYPASSRLS`，用于 DDL 与跨租户运维（对账/覆盖率统计）；运维操作全程审计；
- **配置缓存**：租户配额/状态缓存 60s（失效途径：管理操作主动失效），避免每请求查库。

### 3.4 RLS 策略（数据库层兜底）

每张含 `tenant_id` 的表（附录 A 全部业务表）：

```sql
ALTER TABLE <schema>.<table> ENABLE ROW LEVEL SECURITY;
ALTER TABLE <schema>.<table> FORCE ROW LEVEL SECURITY;   -- 对表 OWNER 也强制
CREATE POLICY tenant_isolation ON <schema>.<table>
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
```

- `USING` 管读、`WITH CHECK` 管写：未携带或携带他租户 `tenant_id` 的写入直接被拒；
- 应用连接使用非超级用户、非 BYPASSRLS 角色；`FORCE` 保证即使表 OWNER（迁移误用同账号）也受策略约束；
- **测试门禁**：集成测试必含跨租户用例集（A 租户读写 B 租户数据 → 断言 0 行/403），纳入 CI 强制通过。

### 3.5 租户级防护（noisy neighbor）

| 防护点 | 机制 | 配置项（tenant_quotas） |
|---|---|---|
| API 限流 | 网关 + 应用双层令牌桶，按租户维度 | `api_rate_limit`（默认 100 req/min，可调） |
| 批量写限额 | 事件批量入库单次上限 | `batch_max_events`（默认 1000） |
| 查询资源 | 每查询 `statement_timeout`（租户级可调），游标分页强制 | `query_timeout_ms`（默认 5000） |
| 连接占用 | 连接池按租户软配额（超发告警） | `pool_share`（百分比） |
| 存储与事件量 | 周期统计 vs 配额，超限告警→自动降级为只读 | `storage_gb` / `events_per_month` |
| Worker 公平 | 数据质量/同步任务按租户轮转，单租户任务超时让出 | 调度器内置 |

超配额行为：先告警（80%），达 100% 限流/降级，管理端可临时提额；所有动作写审计。

### 3.6 容量假设与演进路线

| 项 | 假设（Phase 1-2） | 演进触发与动作 |
|---|---|---|
| 租户数 | ≤50，单集群 | >50：大客户迁 dedicated；长尾按 `tenant_shard` 哈希分库 |
| 单租户数据量 | GB 级（事件/证据为主） | 事件/审计大表按时间分区已内建；超量租户可独立归档策略 |
| QPS | 总 500 req/s 峰值 | app 无状态横向扩副本；读多场景引入读副本（Phase 2） |
| RLS 开销 | 索引前缀含 tenant_id，性能影响 <5% | 压测验证（W6），超标则按租户组拆库 |

---

## 4. 数据流设计

### 4.1 数据流总览

```
[源系统 ERP/MES/PLM]（按租户配置连接）
   │ ① 适配器拉取（增量/全量，Mock 可切换；Worker 按租户循环）
   ▼
[转换管道 Transform Pipeline]
   │ ② 源记录解析 → 标准化 DTO
   │ ③ 对象注册 upsert（revision 乐观锁）
   │ ④ 事件写入（确定性 UUID 幂等）
   │ ⑤ 证据快照写入（自动 checksum）
   │ ⑥ Outbox 写入（与 ③④⑤ 同一事务；全程租户上下文）
   ▼
[PostgreSQL 15 Schema · RLS]
   │ ⑦ Worker 轮询 Outbox → 分发（进程内订阅 / Webhook 升级接缝）
   ▼
[服务层 API]
   ├─⑧ Agent 数据工具（Read-Only）──→ 三大能力查询
   ├─⑨ 能力结果回流（结果事件+风险等级）──→ Event/Evidence
   ├─⑩ Agent 中枢写入 Trace/Memory/Capability 注册
   └─⑪ EBMS 查询/审批（JWT）──→ 报表/异常/决策/待办/证据钻取
```

该数据流即 AEOS 计划"事件驱动 + 闭环反馈"原则的落地形态：上游变更与能力结果皆成事件（⑨ 的行动完成同样以 `action.verified` 事件回流，见附录 C.2），任何决策可经证据链回溯至源记录（7.6）。

### 4.2 接入层：适配器框架

**端口（接口）定义**——所有源系统适配器实现统一端口：

```python
class SourceAdapter(Protocol):
    name: str                      # 适配器标识，如 "erp"
    def fetch_incremental(self, since: datetime) -> list[SourceRecord]: ...
    def fetch_full(self, object_types: list[str]) -> list[SourceRecord]: ...
    def health_check(self) -> AdapterHealth: ...
```

- **注册表驱动**：适配器在启动时注册到 `AdapterRegistry`，运维 API 按名称触发同步；
- **租户级连接配置**：每个租户的源系统连接参数（endpoint、密钥引用、Mock/真实模式）存于 `platform.systems`（按 `tenant_id` 隔离），Worker 按租户实例化适配器；
- **Mock 可切换**：`ErpMockAdapter` 与 `ErpRestAdapter` 实现同一端口，租户级配置 `adapter_mode=mock|real` 切换，真实接口到位即切换，不影响上层管道（对齐 AEOS 计划 §1 假设与 §11 数据风险缓解）；
- **SourceRecord 标准结构**：`{source_system, object_type, source_id, occurred_at, payload, prev_hash?}`，后续所有处理只依赖该结构。

### 4.3 转换管道：三元组落库

每条 `SourceRecord` 在**单事务**内完成（事务首句 `SET LOCAL app.tenant_id`，RLS 全程生效）：

1. **对象注册**：按 `(source_system, object_type, source_id)` 组合键 upsert `master.business_objects`，存在则 `revision + 1`（乐观锁），不存在则创建并生成新 `object_id`；
2. **事件写入**：`event.events` 插入，`event_id` 由 `(source_system, source_id, occurred_at, event_type)` 经 UUID v5 确定性生成——重放安全，天然幂等；
3. **证据快照**：`evidence.records` 插入原始 payload 快照，服务端计算 `checksum = SHA-256(canonical_json(payload))`；
4. **Outbox**：同事务写入 `event.outbox`，供 Worker 异步分发。

抽样对账任务校验管道正确性（源记录数 vs 三元组落库数）。

### 4.4 存储层

15 个 Schema 职责见第 5 章；完整 DDL（含 tenant_id 与 RLS 策略）见附录 A。

### 4.5 服务层与消费方

| 消费方 | 接入方式 | 权限 |
|---|---|---|
| Agent 中枢·三大能力 | Agent 数据工具 API（API Key，scope=`readonly`，绑定租户） | 仅 GET；DB 连接角色只读；RLS 限定本租户 |
| Agent 中枢·结果回流 | 事件批量入库 API（API Key，scope=`write:event`） | 仅事件/证据写入（本租户） |
| Agent 中枢·注册与日志 | 注册中心 API、Trace/Memory API（API Key） | 各自受限 scope（本租户） |
| EBMS 前端 | EBMS 查询/审批 API（JWT，RBAC，claims 携带租户） | 管理者角色；审批仅 human principal |
| **EDP 控制台前端**（第 13 章） | 全部 `/api/v1` 分组：EBMS 查询/审计/适配器运维/质量/租户管理/健康检查（JWT Cookie + CSRF） | 按角色 RBAC：平台运营（PLATFORM_ADMIN 跨租户）、租户 ADMIN/MANAGER 本租户运维 |
| 平台运营 | 租户管理 API（JWT，平台 ADMIN） | 租户生命周期/成员/配额/使用量 |
| 运维 | 适配器运维/数据质量 API（JWT，ADMIN） | 手动同步、质量报告 |

---

## 5. 数据模型设计

### 5.1 Schema 总览（15 个）

> 说明：AEOS 计划 W1 列出 13 个 Schema（`decision` 域内含 action 表、`memory` 独立）。本设计将 **`action`、`trace` 独立成域**，展开为 **15 个独立 Schema**，以获得最清晰的域边界与独立的备份/清理策略（trace 高频写入、action 状态机审计敏感）。此调整随本文档一并提交 W1 评审冻结。
>
> 多租户：除 `platform.tenants` 外全部表含 `tenant_id` 并启用 RLS（见第 3 章）；`platform` 中的租户四表（tenants/tenant_members/tenant_quotas/tenant_usage_daily）为平台根实体，`tenants` 自身无 `tenant_id`。

| # | Schema | 职责 | 核心表 |
|---|---|---|---|
| 1 | platform | 平台基础：租户、成员、配额、使用量、用户、组织、角色、权限、API 密钥、系统/能力/技能注册、审计日志 | tenants, tenant_members, tenant_quotas, tenant_usage_daily, organizations, users, roles, permissions, api_keys, systems, capabilities, skills, audit_logs |
| 2 | master | 统一对象注册与主数据 | business_objects, customers, products, materials, boms, bom_items, suppliers |
| 3 | event | 事件流水与结果、Outbox | events, outbox |
| 4 | evidence | 证据快照与证据链关联 | records, links |
| 5 | decision | 决策案例与决策记录 | cases, records |
| 6 | action | 行动任务（状态机） | actions |
| 7 | memory | 学习记忆（候选→评审→Approved） | memories |
| 8 | management | 经营目标、KPI 定义与数值、硬性约束 | objectives, kpi_definitions, kpi_values, constraints |
| 9 | trace | Agent 执行日志 | traces, tool_calls |
| 10 | sales | 销售域同步快照 | orders, order_lines |
| 11 | delivery | 交付域同步快照 | inventory, purchase_orders, supplier_lead_times, capacity |
| 12 | rd | 研发域同步快照 | projects, milestones |
| 13 | support | 支持域同步快照 | tickets |
| 14 | quality | 品控域同步快照 | inspections, exceptions |
| 15 | finance | 财务域同步快照 | receivables, revenue_snapshots |

共 **48 张表**。业务域（sales~finance）快照表统一模式：`object_id` 关联注册对象 + `snapshot_at` 快照时点 + `attributes JSONB` 承载域差异字段，W2 起随适配器接入范围逐步启用。

### 5.2 核心实体关系

```
platform.tenants（平台根）
   │ 1:N（tenant_id 贯穿全部表）
   ▼
master.business_objects (object_id) ──1:N── event.events
      │                                        │
      │1:N                                     │1:N（可选关联）
      ▼                                        ▼
evidence.records ──N:M── evidence.links ──→ decision.cases
      │                                    （ref_type: CASE/DECISION/ACTION/RESULT/EVENT/TRACE）
      │                                         │1:N
      │                                         ▼
      └── checksum 可独立校验            decision.records / action.actions
```

- **租户**是数据归属根：所有实体（含对象注册）先归属租户，再参与域内关系；
- **对象注册**是租户内所有数据的锚点：事件、证据、域快照均通过 `object_id` 关联（对齐 AEOS 计划 §2"通过 BusinessObject ID 关联不同系统数据"）；
- **证据链**通过 `evidence.links(ref_type, ref_id)` 通用关联实现逆向追溯（Result→Decision→Evidence→源记录）；
- **能力结果**回流为事件（`event_type = capability.result.*`），结构化风险字段存于 `events.risk_level/result_type/score` 列，EBMS 异常列表据此高效过滤。

### 5.3 关键表说明

**master.business_objects（对象注册元表）**

- 租户内组合唯一键 `(tenant_id, source_system, object_type, source_id)` 防重复注册；
- `revision` 乐观锁版本号，并发 upsert 冲突返回 409；
- `status`：`ACTIVE/SUSPENDED/MERGED`，支持主数据合并治理（如客户 ID 重复场景，AEOS 计划评估用例 8）。

**event.events（事件流水）**

- `event_id` 确定性 UUID v5 幂等；`idempotency_key` 适配器批次去重；
- `risk_level/result_type/score` 为能力结果事件专用可空列，建部分索引；
- `data JSONB` 存事件明细，GIN 索引支撑按属性查询。

**evidence.records（证据快照）**

- `checksum = SHA-256(canonical_json(snapshot))`，服务端写入时计算，`verify` 接口可随时重算比对，防篡改；
- `source_system + source_record_id` 指回源系统原始记录，是追溯链终点。

**action.actions（行动状态机）**

状态机：`PROPOSED → ASSIGNED → ACCEPTED → APPROVED → EXECUTING → COMPLETED → VERIFIED`，旁路 `CANCELLED / REJECTED`（与 AEOS 计划 §1 Action 状态机"提议→分配→接受→审批→执行→完成→验证"一致）。合法转移由应用层守卫表约束并落审计。

**trace.traces（Agent 执行日志）**

高频写入，独立 Schema 便于独立保留期与归档策略；`tool_calls` 子表记录每次工具调用的入参/出参/耗时/错误，满足三层留痕（输入证据、执行轨迹、结果与版本，对齐 AEOS 计划 §6 Trace Schema）。

完整 DDL（含全部索引与约束）见**附录 A**。

---

## 6. API 设计

### 6.1 API 分组概览

| 分组 | 前缀 | 主要消费方 | 鉴权 |
|---|---|---|---|
| 认证与密钥 | `/api/v1/auth` | EBMS 前端、运维 | 公开（登录）/ JWT |
| 租户管理 | `/api/v1/tenants` | 平台运营 | JWT（平台 ADMIN；租户内 ADMIN 限本租户成员/配额查询） |
| 对象注册 | `/api/v1/objects` | 适配器管道、EBMS 钻取 | API Key（write:registry）/ JWT |
| 事件 | `/api/v1/events` | Agent 中枢回流、EBMS | API Key（write:event）/ JWT |
| 证据 | `/api/v1/evidence` | Agent 中枢、EBMS 钻取 | API Key（write:evidence）/ JWT |
| 决策与行动 | `/api/v1/decisions` `/api/v1/actions` | Agent 中枢建 Case、EBMS 审批 | JWT + API Key |
| 审计 | `/api/v1/audit-logs` | 合规查询 | JWT（ADMIN） |
| 注册中心 | `/api/v1/systems` `/api/v1/capabilities` `/api/v1/skills` | Agent 中枢 | API Key（write:registry） |
| Agent 数据工具 | `/api/v1/tools/*` | 三大能力 | API Key（readonly） |
| EBMS 查询 | `/api/v1/ebms/*` | EBMS 前端 | JWT（MANAGER+） |
| Trace / Memory | `/api/v1/traces` `/api/v1/memories` | Agent 中枢 | API Key |
| 适配器运维 | `/api/v1/admin/adapters` | 运维 | JWT（ADMIN） |
| 数据质量与运行状况 | `/api/v1/admin/quality` `/api/v1/health` | 运维、Go/No-Go 度量 | JWT（ADMIN）/ 公开（health 浅层） |

> 所有分组（租户管理除外）的访问范围均被租户上下文限定（3.3）：JWT 携带 `tenant_id` claim，API Key 绑定租户；跨租户访问统一 `403 TENANT_FORBIDDEN`。

### 6.2 通用约定

- **鉴权**：用户侧 `Authorization: Bearer <JWT>`（access 2h + refresh 7d；claims 含 `tenant_id`、`roles`、`principal_type`）；服务侧 `X-API-Key: <key>`（仅存 SHA-256 哈希，按 scope 授权，**密钥绑定租户**）；
- **租户校验**：认证中间件校验租户状态与 principal 归属（3.3），SUSPENDED 租户返回 `403 TENANT_SUSPENDED`；
- **错误结构**：`{"error": {"code": "STRING_CODE", "message": "...", "request_id": "uuid"}}`，统一错误码见附录 B.0；
- **分页**：`?limit=50&cursor=<opaque>`，响应带 `next_cursor`，禁止 OFFSET 深翻页；
- **限流**：按租户令牌桶（3.5 配额），超限 `429 RATE_LIMITED` 响应头带 `Retry-After`；
- **幂等**：批量写接口携带客户端生成的 UUID，重复提交返回原结果（HTTP 200 + `deduplicated: true`）；
- **契约治理**：FastAPI 自动生成 OpenAPI 3.1（`/openapi.json`），W1 冻结后变更须走契约评审（开发计划 M1 门控流程）。

全量接口契约（方法/路径/鉴权/请求/响应/错误码）见**附录 B**。

---

## 7. 关键机制设计

### 7.1 幂等与去重（三层）

| 层 | 机制 | 说明 |
|---|---|---|
| 适配器层 | 确定性 `event_id = UUIDv5(tenant_ns, source_system+source_id+occurred_at+event_type)` | 同一源记录重放产生相同 UUID，`ON CONFLICT DO NOTHING`；UUID v5 命名空间含 tenant_id，天然租户隔离 |
| 接口层 | 批量请求幂等键 | `Idempotency-Key` 头，Redis/内存缓存请求结果（可降级为 DB 表） |
| 数据层 | 组合唯一约束 | `UNIQUE(tenant_id, source_system, object_type, source_id)`（注册）、`UNIQUE(event_id)`（事件，全局唯一）、`UNIQUE(tenant_id, evidence_id)`（证据） |

### 7.2 事务性 Outbox 事件分发

```
写事务：SET LOCAL app.tenant_id → 业务表 + event.outbox(PENDING)  同事务提交
Worker：按租户循环：SELECT ... WHERE tenant_id=:t AND status='PENDING'
        AND available_at<=now() FOR UPDATE SKIP LOCKED
        → 分发给订阅者（W1-W4：进程内事件总线 → EBMS 通知/缓存失效）
        → 成功置 PUBLISHED；失败 retry_count+1，指数退避 available_at，超阈值置 FAILED+报警
        → 单租户异常隔离，不影响其他租户继续分发
```

- Phase 1 不引入 MQ；Outbox 表即事件溯源底账，保留升级 Kafka/Webhook 的分发接缝（订阅者接口 `on_event(event) -> ack/nack`）；
- 分发至少一次 + 消费端按 `event_id` 幂等，语义等效恰好一次。

### 7.3 证据防篡改 checksum

- 写入：`checksum = SHA-256(canonical_json(snapshot))`，canonical 规则：键排序、无空白、UTF-8、数字规范化（对齐 RFC 8785 简化子集）；
- 校验：`GET /evidence/{id}/verify` 服务端重算比对，返回 `{"valid": true/false}`；校验失败自动写审计 `EVIDENCE_CHECKSUM_MISMATCH` 并报警；
- 抽检：数据质量任务每日抽样重算 P0/P1 关联证据。

### 7.4 乐观锁并发控制

- `business_objects.revision`：upsert 携带期望版本，`WHERE revision = :expected`，失配返回 `409 CONFLICT` 与当前版本，调用方重读后重试（最多 3 次）；
- `action.actions` 状态机转移同理：`WHERE status = :expected_status`，防并发双写审批。

### 7.5 Action 状态机

```
PROPOSED ──分配──▶ ASSIGNED ──接受──▶ ACCEPTED ──审批──▶ APPROVED
   │                                                  │执行
   │拒绝                                              ▼
   ▼                                    EXECUTING ──完成──▶ COMPLETED ──验证──▶ VERIFIED
REJECTED                                              任意非终态 ──取消──▶ CANCELLED
```

- 转移合法性表在应用层集中定义，非法转移返回 `422 INVALID_TRANSITION`；
- `APPROVED → EXECUTING` 仅允许 human principal 触发（Guard，见 8.4）；审批意见作为输入证据落 `evidence.links`（对齐 AEOS 计划 §6 HITL"必须记录审批意见作为输入 Evidence 的一部分"）。

### 7.6 证据链逆向追溯

闭环验收要求链路 `Result → Exception → Decision → Evidence → 源数据` 可逆向追溯：

1. EBMS 从异常/决策条目取得 `ref_type + ref_id`；
2. `GET /evidence?ref_type=CASE&ref_id=...` 经 `evidence.links` 命中证据集合（RLS 自动限定本租户）；
3. 每条证据可 `verify` 校验 + 经 `source_system/source_record_id` 指回源系统原始记录；
4. 中间任何 DecisionCase/DecisionRecord/Action 均可通过自身 `evidence_refs` 正向补全链路。

---

## 8. 安全设计

### 8.1 认证

| 轨道 | 适用 | 机制 |
|---|---|---|
| JWT | 用户（EBMS 前端、运维） | 登录签发 access(2h)+refresh(7d)；密码 Argon2id 哈希；claims 含 `tenant_id/roles/principal_type` |
| API Key | 服务（Agent 中枢、适配器 Worker） | 生成时仅展示一次，库存 SHA-256；**绑定租户**与 principal、scope 列表，支持吊销与过期 |

### 8.2 授权（RBAC + Guard 分级）

- **角色**：`PLATFORM_ADMIN`（平台运营，跨租户管理）、`ADMIN`（租户管理）、`MANAGER`（管理者，EBMS 全功能）、`ANALYST`（只读分析）、`SERVICE`（服务主体，按 scope）；
- **权限矩阵**：permission = `resource × action`（如 `evidence:read`、`decision:decide`），另加租户维度归属校验（用户↔租户经 `tenant_members`）；
- **风险分级**（对齐 AEOS 计划 §6 Guard 规则）：
  - `Human-Only`：决策审批、行动执行确认、记忆评审、密钥管理——API 层拒绝 AI principal，仅 human JWT；
  - `Read-Only`：Agent 数据工具全部接口；
  - `AutoAllowed`：内部提醒、草拟任务类写入。

### 8.3 访问边界：租户隔离 + Agent 只读（双纵深）

**租户隔离（跨租户防护，双保险）**

1. **应用层**：认证中间件校验 principal↔租户归属，不匹配即 `403 TENANT_FORBIDDEN` + 审计；
2. **数据库层**：全表 RLS（3.4）兜底——即使应用层缺陷，SQL 也只能触达 `app.tenant_id` 限定行。

**Agent Read-Only 强约束**

1. **应用层**：`/api/v1/tools/*` 路由仅注册 GET 方法，中间件强制校验 API Key `scope=readonly`，非 GET 一律 `405`（对齐 AEOS 计划 §6"禁止 LLM 直接调用业务表，只能通过经授权的工具接口"）；
2. **数据库层**：Agent 专用 PG 角色仅授予六业务域 Schema 的 `SELECT`；
3. **审计层**：所有被拒越权尝试写 `audit_logs(ACTION=GUARD_DENIED)`，报警联动 Go/No-Go 度量"AI 越权 0 次"。

### 8.4 审计与 Guard 检查点

- **审计切面**：FastAPI 中间件 + 服务层装饰器，覆盖全部写操作：记录 `tenant_id/actor/principal_type/action/resource/before/after/request_id`；
- **Guard 检查点**：决策审批接口校验 principal 为 human；策略规则与 `management.constraints` 联动，触发警告即转 HITL（对齐 AEOS 计划 §6"策略触发警告时系统必然触发 HITL"）；
- 审计日志仅追加（无 UPDATE/DELETE 权限），按月分区，含 `tenant_id` 索引支撑租户级合规查询。

### 8.5 密钥与敏感数据

- 配置经环境变量注入（Docker Compose `.env`，不入库不入仓）；租户级源系统密钥经密钥引用（`secret_ref`）间接持有，明文仅在运行时解析；
- 证据快照可能含客户敏感信息：字段级脱敏钩子在适配器管道提供（W3 按需启用），快照本体不脱敏以保 checksum 可验证性——脱敏在读取层投影执行。

---

## 9. 可靠性与运维

> 本章承接 AEOS 计划 W5"数据备份与故障恢复流程"要求并按"一定要可靠"的标准强化：数据库主从 HA + 自动故障转移 + WAL 归档 PITR + 租户级恢复，全部纳入 W5 演练。

### 9.1 数据库高可用（Patroni HA）

| 项 | 方案 |
|---|---|
| 拓扑 | Patroni 集群：主库 ×1 + 从库 ×1（流复制）+ etcd ×3（Leader 选举/元数据）；dedicated 形态同构缩小 |
| 复制 | 流复制；`synchronous_commit=remote_apply` 可按租户敏感级配置（默认异步，P0 租户可开同步确认） |
| 故障转移 | Patroni 自动探测（pg 的健康 + etcd 仲裁），主故障 <30s 自动提升从库；应用侧连接串带 `target_session_attrs=read-write` + 失败重试，无需人工介入 |
| 目标 | **RPO ≈ 0（同步）/ 秒级（异步）；RTO < 5min** |
| 防脑裂 | etcd 多节点仲裁；任一时刻仅一个可写主（Patroni 保证） |
| 演练 | W5 真实演练：kill 主库 → 观察自动切换 → 业务恢复 → 数据校验（对账任务 + checksum 抽检） |

### 9.2 备份与恢复（含租户级恢复）

| 项 | 方案 |
|---|---|
| 全量备份 | 每日 02:00 `pg_dump -Fc`（Patroni 从库执行，不影响主库），保留 14 天 |
| WAL 归档 | `archive_mode=on` 归档至备份存储（与数据卷分开），支持 PITR 任意时点恢复 |
| 整库恢复 | PITR：基础备份 + WAL 重放至目标时点；RTO ≤ 2h |
| **租户级恢复** | 误删/污染场景：`pg_dump --table` 逻辑导出目标租户数据（按 `tenant_id` 过滤）→ 恢复至隔离库 → 校验 → 按表回放（经 BYPASSRLS 运维账号 + 全程审计） |
| 恢复目标 | RPO ≤ 5min（WAL 归档粒度）、RTO：整库 ≤ 2h / 单租户 ≤ 4h |
| 演练（W5，三项） | ① 主从自动切换演练；② PITR 整库恢复演练；③ 租户级恢复演练（模拟某租户数据误删后找回），均产出手册与度量记录 |
| 备份存储 | 独立于数据库卷的持久卷/对象存储；空间预估随租户数动态（单租户阶段 50GB 基线，对外后按配额扩容） |

### 9.3 数据质量监控（W5 上线，按租户执行）

| 任务 | 逻辑 | 产出 |
|---|---|---|
| 对账 | 源系统记录数 vs EDP 三元组落库数，偏差 > 阈值报警 | 租户级对账报告 |
| 覆盖率统计 | 按 `object_type` 统计注册覆盖率，支撑 Go/No-Go ≥95% | 租户级/平台级周度报表 |
| 孤儿检测 | `event.object_id` 无对应注册对象 / `evidence.object_id` 悬挂 | 孤儿清单 |
| 缺失与异常检测 | 关键字段（订单交期、库存数）缺失/越界报警 | 异常事件（写 event + 通知） |
| checksum 抽检 | 每日抽样重算 P0/P1 证据 | 校验报告 |

质量任务结果统一写 `event.events(event_type=quality.*)` 并出报表 API：`GET /admin/quality/reports`（平台视角可跨租户聚合，走 BYPASSRLS 运维账号 + 审计）。

### 9.4 性能与租户防护（目标：主要接口 < 2s）

- 索引先行：DDL 按查询模式建索引且**前缀含 `tenant_id`**（附录 A），W6 压测前完成 `pg_stat_statements` 慢查询治理；
- 分页一律游标式，禁止深分页 OFFSET；每查询 `statement_timeout` 按租户配额生效（3.5），防慢查询拖垮共享集群；
- 限流：网关 + 应用双层按租户令牌桶（3.5），超配额先告警（80%）后限流（100%）；
- EBMS 报表摘要接口读物化视图/预聚合表（`management.kpi_values`），避免实时聚合大表；
- 缓存：W6 视压测结果引入 Redis 缓存热点查询（TTL 60s 级，**缓存键必须含 tenant_id**，防止跨租户串数据），作为优化预留而非首期依赖。

### 9.5 部署拓扑（Docker Compose，shared / dedicated 双形态）

```yaml
# deploy/docker-compose.shared.yml（默认；dedicated 形态同结构，db 单实例 + 每日备份，HA 可选）
services:
  gateway:    # nginx：TLS、路由、租户级限流（per-tenant rate limit zone）
  api:        # FastAPI（uvicorn，backend/apps/api）×2 副本，无状态水平扩展
  web:        # frontend/apps/web 构建产物（Nginx 静态托管 + /api 反代）
  worker:     # Outbox 分发 + 数据质量任务 + 备份调度 ×2 副本（SKIP LOCKED 天然安全）
  etcd:       # ×3，Patroni 仲裁
  patroni:    # postgres:16 主从 ×2（含 healthcheck、自动故障转移）
  pgbackrest: # WAL 归档 + 基础备份 sidecar（挂独立备份卷）
```

- 迁移独立执行：`alembic upgrade head` 于发布前（deploy 脚本控制，使用 `edp_migrator` BYPASSRLS 账号），失败即阻断发布；RLS 策略随 DDL 同版本链迁移；
- 环境三套：`dev`（本地 Compose 单库）、`staging`（联调 + W4 闭环演示，HA 拓扑与 prod 同构）、`prod`（试运行 W5 起，HA 全量）；
- `DEPLOY_MODE=shared|dedicated` 仅影响编排文件与配置，代码零分支。

### 9.6 可观测性

- 结构化 JSON 日志（含 `tenant_id` + `request_id`，贯穿审计与 Trace）；
- `/api/v1/health`：浅层（存活）+ 深层（DB 连接、复制延迟、Outbox 积压、最近同步状态）；
- 核心告警指标（按租户维度 + 平台汇总双视角）：Outbox 积压、适配器失败率、checksum 失配数、**复制延迟、HA 切换事件、租户配额水位（80% 告警）**；
- 备份可恢复性每日自动验证（备份文件完整性 + 抽样恢复到临时库）。

---

## 10. 外部系统边界

### 10.1 ERP / MES / PLM（上游源系统）

| 项 | 约定 |
|---|---|
| 接入方式 | REST（优先）或文件落盘；统一经 `SourceAdapter` 端口封装 |
| 租户级配置 | 每租户独立的源系统连接与 Mock/真实模式配置（`platform.systems` 按 `tenant_id` 隔离，见 4.2） |
| 数据范围（W2 起） | ERP：订单、BOM、库存、供应商交期；MES/PLM：W3 按能力需要扩展 |
| 降级策略 | `ErpMockAdapter` 提供与真实接口同构的确定性测试数据集；租户级 `adapter_mode=mock\|real` 配置切换，上层管道零改动 |
| 增量语义 | 优先增量（`since` 水位，按租户维护），支持全量对账修正 |
| 责任边界 | 源数据口径由业务方主数据 Owner 负责（AEOS 计划 §11 数据质量风险缓解）；对外租户的主数据责任人在租户开通时指定 |

### 10.2 Agent 中枢（下游服务主体）

| 交互 | EDP 提供 |
|---|---|
| 取数 | Agent 数据工具 API（Read-Only：订单/库存/采购/BOM/供应商交期/客户，对齐三大能力工具 `get_order/get_inventory/get_purchase` 的数据面） |
| 结果回流 | `POST /events/batch`（`capability.result.*` 事件）+ 证据写入 |
| 注册 | 能力/技能注册 API（platform.capabilities/skills 的存储与查询，对齐 AEOS 计划 Capability Registry API） |
| 日志 | Trace 写入与查询 API（对齐 AEOS 计划 Trace Schema 存储） |
| 记忆 | Memory 候选创建/查询；评审流转 API W6 由中枢接管 |

边界：Agent 中枢不直连 EDP 数据库；一切访问经 API + 密钥 + 审计。

### 10.3 EBMS 与 EDP 控制台（下游用户界面）

**EBMS（Fullstack B 承建，范围外——见 1.3 前端范围声明）**

- 只消费 EBMS 查询 API（JWT，租户上下文）；审批等写操作走决策/行动 API，Guard 强制 human principal；
- 页面（REPORT/EXCEPTION/DECISION/TODO/DIALOGUE/EVIDENCE）对 EDP 的接口映射见附录 B.9（DIALOGUE 由 Agent 中枢对话接口实现，EDP 仅提供其取数工具）。

**EDP 控制台（本文档第 13 章，运维/运营平面）**

- 面向平台运营与租户管理员，消费租户管理、审计、适配器运维、数据质量、EBMS 查询、健康检查等全部 `/api/v1` 分组；
- 与 EBMS 的职责边界：EBMS 面向**经营者**看「结果-异常-决策-证据」；EDP 控制台面向**平台运维/运营**管「数据链路-质量-审计-租户」——两者共用同一套 API 与租户上下文，不复用页面；
- 前端契约治理：api-sdk 由 `/openapi.json` 自动生成，SHA256 校验进 CI（13.9）。

---

## 11. 验收指标映射（Go/No-Go）

> 指标来源：AEOS 计划 §9 验收标准与 §13 关键验收门控；后三项为多租户/可靠性基线补充指标。

| 指标 | 目标 | 设计支撑 |
|---|---|---|
| 业务对象覆盖度 | ≥95% | 对象注册组合唯一键（5.3）+ 覆盖率统计任务（9.3）+ `GET /admin/quality/coverage` |
| 证据可追溯 | P0/P1 结论 100% 可追溯 | 证据链 links + checksum（7.3/7.6）+ 逆向追溯 API（附录 B.4） |
| 风险识别召回率 | 重大风险召回 ≥80%、误报 ≤20% | 工具 API 数据完备性（B.8）+ 演示数据 seed 覆盖 10 类评估场景（13.10） |
| Action 执行/闭环率 | ≥90% 生成行动被执行并关闭验证 | Action 状态机 + HITL（7.5）+ 闭环事件回流统计（附录 C.2） |
| AI 越权执行 | 0 次 | Read-Only 三层纵深（8.3）+ Guard 检查点（8.4）+ 越权审计报警 |
| 审计合规 | 每次决策与关键动作审计完整率 100%；高风险动作全过 HITL | 审计切面覆盖全部写操作（8.4）+ 仅追加分区表 |
| 接口响应 | <2s | 索引设计（附录 A，tenant 前缀）+ 游标分页 + 预聚合（9.4） |
| 租户隔离 | 跨租户访问 100% 拒绝 | 应用层校验 + RLS 双保险（8.3）+ CI 跨租户测试门禁（3.4） |
| 高可用 | 主库故障 RTO<5min、RPO≈0/秒级 | Patroni 自动故障转移（9.1）+ W5 切换演练 |
| 备份可恢复 | 三项演练通过 | 整库 PITR + 租户级恢复 + 每日备份验证（9.2/9.6） |

---

## 12. 对开发计划的影响

> 技术范围（多租户 P1 全量落地 + HA 强化 + EDP 控制台前端）相对 AEOS 计划基线的工作量增量约 15%~20%（后端）；前端线按第 13 章落地。任务分解、周排布、里程碑与风险详见配套文档**《EDP 数据平台开发计划_一阶段》**，本章仅保留结论性要点。

### 12.1 任务增量（任务编号与开发计划一致）

| 任务ID | 周 | 内容 | 验收标准 |
|---|---|---|---|
| EDP-022 | W1 | 租户数据模型与 RLS 基线：tenants 四表、全表 tenant_id、RLS 策略迁移 | 跨租户集成测试用例进 CI 并通过 |
| EDP-023 | W1 | 租户上下文中间件：JWT claims / API Key 绑定、SET LOCAL、租户状态校验 | 无租户上下文的请求被拒绝；SUSPENDED 拒绝生效 |
| EDP-024 | W2 | 租户管理 API：生命周期/成员/配额（B.14） | 开通→暂停→恢复→注销全流程可演示 |
| EDP-025 | W2 | 租户限流与配额执行：双层令牌桶、statement_timeout、使用量统计 | 超配额请求 429；使用量日报可查 |
| EDP-026 | W4 | 跨租户安全测试：越权矩阵用例（API 层 + RLS 层） | 全部拒绝路径覆盖，0 泄露 |
| EDP-027 | W5 | HA 部署与演练：Patroni 拓扑上线、主从切换/PITR/租户级恢复三项演练 | 演练记录与手册归档 |

### 12.2 前端任务（EDP-101~604，详见开发计划第 4 章）

| 任务ID | 周 | 内容 | 验收标准 |
|---|---|---|---|
| EDP-101~105 | W1 | monorepo 脚手架、Antd Token 主题映射（13.4）、壳层骨架（13.5）、9 个核心组件（13.7）、api-sdk 自动生成 + 契约 SHA256 CI（13.9） | Storybook 视觉对齐原型基线；契约变化 PR 自动失败 |
| EDP-201~203 | W2 | Query 客户端拦截器（13.9.2）、运营总览页、业务对象页 | KPI 卡 + 链路状态实时展示；chip 过滤 + 游标分页 |
| EDP-301~304 | W3 | 事件流（含回放向导）、证据库（含重索引向导 + verify）、数据质量（含重校验弹窗）、系统健康页 | 对应设计稿交互全覆盖 |
| EDP-401~404 | W4 | 审计日志、适配器管理、闭环案例页（M4 关键）、决策/行动页 | 一屏讲完闭环叙事；422 按 allowed_to 重渲染 |
| EDP-501~503 | W5 | 租户 6 页 + 切换、演练回放、Agent 工具/Trace/记忆页 | 租户全生命周期可演示 |
| EDP-601~604 | W6 | 错误页收口、Playwright E2E、Storybook 视觉回归基线、文档归档 | 错误码 13 种全覆盖；CI 强制通过 |

### 12.3 里程碑影响与关键风险

| 里程碑 | 影响 | 应对 |
|---|---|---|
| M1 契约冻结 | W1 范围扩大（+EDP-022/023） | 租户模型随契约一并冻结；评审重点增加 RLS 策略 |
| M2 数据链路 | 适配器按租户配置改造，量小 | Mock 适配器直接按多租户实现，避免返工 |
| M4 闭环演示 | **关键路径风险**：租户平面若挤压联调资源 | 租户运营功能（配额报表/计量）可裁剪至 W3-W4 交付，M4 前冻结租户功能范围 |
| M5 可靠性 | 演练从 1 项扩为 3 项（切换/PITR/租户恢复） | staging 提前于 W4 搭 HA 同构环境 |
| M6 验收 | 指标新增租户隔离与 HA 两项 | W4 安全测试前移，W5 完成演练留缓冲 |

**关键人风险提示**：单人承担后端前提下，多租户+HA 同期落地压力上升；建议将 EDP-024/025（租户管理平面）列为可协商裁剪项，数据层 RLS 与 HA 演练（EDP-022/023/026/027）为不可裁剪项。前端线由 Fullstack B 主责、A 承担 SDK/联调/评审，双线冲突时 M4 前 EDP 控制台优先（开发计划第 8 章风险 6）。

---

## 13. EDP 控制台前端设计

> 本章为 EDP 唯一的前端范围（见 1.3 前端范围声明），以《运营总览 等 26 个设计》高保真原型（`原型设计/pages/*.html`）为视觉与交互基线。评审对象：PM / Tech Lead、Fullstack B。

### 13.1 定位与设计原则

**定位**：EDP 控制台是 EDP 自带的运维/运营 Web 前端，服务三类用户——平台运营（PLATFORM_ADMIN，跨租户管理）、租户管理员（ADMIN，本租户成员/配额/适配器运维）、运营分析（MANAGER/ANALYST，数据链路观察）。它与 EBMS（经营者看结果-异常-决策）共用同一套 `/api/v1` 与租户上下文，但页面完全不重叠。

**设计原则**（从 26 个原型提炼，全程强制）：

1. **证据优先**：任何风险/异常/决策条目必须可一键下钻到证据（checksum 展示 + verify 入口），页面结构围绕"指标 → 列表 → 详情 → 证据"四级钻取组织；
2. **状态即语义色**：success/warning/error/info/primary 五色全局统一映射（13.4.3），同一状态在任何页面颜色一致；
3. **ID 可追溯**：所有业务 ID（对象/事件/证据/决策/任务）以 mono 字体展示短 ID（UUID 前 8 位）+ tooltip 全量，可复制；
4. **空态有出口**：任何列表/搜索结果为空时提供"清除筛选 + 新建"双动作，不留死胡同；
5. **危险操作分级**：一般删除用红色按钮轻量确认；租户注销等不可逆操作升级为"输入 slug 强确认"（13.7 模式 10）；
6. **任务异步化可视化**：长任务（重索引/重校验/回放）一律向导发起 + 抽屉看日志时间线，不阻塞页面。

### 13.2 技术选型与工程架构

| 层 | 选型 | 说明 |
|---|---|---|
| 框架 | React 18 + TypeScript 5 + Vite | 组件生态成熟；Vite 秒级 HMR |
| UI 库 | Ant Design 5，Token 主题映射原型令牌（13.4） | 不引 second UI lib；原型视觉经 `ConfigProvider theme.token` 全量映射 |
| 数据层 | TanStack Query v5 | 缓存/重试/游标分页 `useInfiniteQuery`；写操作 Mutation + 失效 |
| 路由 | React Router v6（扁平路由 + 布局路由） | 路由表见 13.3 |
| 状态 | 服务端状态全走 Query；客户端仅主题/租户上下文（Zustand） | 不引入 Redux |
| Mock | MSW（Mock Service Worker） | 契约冻结前/后端未就绪页面（如系统健康、演练回放）用 MSW 先行 |
| 构建/仓库 | frontend/ pnpm workspace：`apps/web` + `packages/api-sdk`、`packages/shared`（双根布局见 2.3） | 与后端 `backend/` 同仓（仓库级双工作区根，2.3）；契约中立场 `contracts/` |
| SDK | `api-sdk` 由 `/openapi.json` 经 openapi-typescript 自动生成 | 契约 SHA256 校验进 CI（13.9.1），后端契约变更未重新生成 SDK 则 PR 失败 |
| 测试 | Storybook（组件文档 + 视觉回归）+ Playwright（E2E）+ Vitest（单元） | E2E 选择器统一用原型 `data-dom-id` 锚点 |
| 部署 | `web` 构建产物由 Nginx 容器托管，经 gateway 反代 `/api` | Docker Compose 一键起全套 |

```
frontend/apps/web/src/
├── app/            # 入口、路由装配、Provider（Query/Theme/Tenant）
├── shell/          # 壳层：Sidebar/Topbar/CommandPalette/租户切换
├── features/       # 特性域（19 个，与 13.3 路由对应，清单见 2.3.3）
├── components/     # 通用组件（13.7 的 17 条模式封装）
└── lib/            # Query client、拦截器、错误映射、枚举字典
frontend/packages/shared/src/    # 设计令牌 TS 常量、枚举/展示名映射、权限矩阵定义
frontend/packages/api-sdk/src/   # 生成产物 + 拦截器（Cookie/CSRF/401 刷新/429 退避）
```

### 13.3 信息架构与路由（21 主页面 / 约 30 路由）

侧边导航四组（与原型一致）：

```
运营总览     /admin/overview
数据工作台
  ├─ 业务对象  /admin/registry        （卡片/表格双视图 + 详情 Tab）
  ├─ 事件流    /admin/events          （+ 回放向导弹窗）
  └─ 证据库    /admin/evidence        （+ 重索引向导弹窗 + 链图面板）
运维监控
  ├─ 数据质量  /admin/quality         （+ 重校验弹窗 + 任务日志抽屉）
  ├─ 审计日志  /admin/audit           （+ 导出/新建策略弹窗）
  ├─ 适配器管理 /admin/adapters        （+ 新增/测试/连接弹窗 + 日志抽屉）
  └─ 系统健康  /admin/systems         （HA 状态 + 备份 + 告警渠道）
平台配置
  └─ 租户管理  /tenants               （列表/详情/成员/配额 + 4 弹窗）
智能闭环（无高保真稿，按 13.6.5 规范）
  ├─ 闭环案例  /cases  /cases/:id     （M4 演示关键页）
  ├─ 决策      /decisions
  ├─ 行动      /actions
  ├─ Agent 工具 /admin/tools
  ├─ Trace    /admin/traces
  ├─ 候选记忆  /admin/memory
  └─ 演练回放  /admin/drills          （W5 三项演练记录）
全局：/login、403/404/500 错误页、全局搜索空态
```

| # | 主页面 | 路由 | 设计稿 | 一级入口 |
|---|---|---|---|---|
| 1 | 登录 | `/login` | —（按壳层规范） | 公开 |
| 2 | 运营总览 | `/admin/overview` | 运营总览 | 侧边栏 |
| 3 | 业务对象 | `/admin/registry` | 业务对象（+空态+新建弹窗） | 侧边栏 |
| 4 | 事件流 | `/admin/events` | 事件流（+回放向导） | 侧边栏 |
| 5 | 证据库 | `/admin/evidence` | 证据库（+重索引向导） | 侧边栏 |
| 6 | 数据质量 | `/admin/quality` | 数据质量（+重校验弹窗） | 侧边栏 |
| 7 | 审计日志 | `/admin/audit` | 审计日志（+导出/策略弹窗） | 侧边栏 |
| 8 | 适配器管理 | `/admin/adapters` | 适配器管理（+4 弹窗/抽屉） | 侧边栏 |
| 9 | 系统健康 | `/admin/systems` | —（MSW 先行） | 侧边栏 |
| 10 | 租户管理 | `/tenants` | 租户管理 | 侧边栏 |
| 11 | 租户详情 | `/tenants/:tenant_id` | —（复用租户管理三联卡） | 表格行 |
| 12 | 闭环案例 | `/cases` | —（13.6.5） | 总览时间线 |
| 13 | 案例详情 | `/cases/:case_id` | 风险详情-抽屉（升级为整页） | 案例表/风险卡 |
| 14 | 决策 | `/decisions` | —（13.6.5） | 案例详情 |
| 15 | 行动 | `/actions` | —（13.6.5） | 决策页 |
| 16 | Agent 工具 | `/admin/tools` | —（13.6.5） | 侧边栏（运维监控组） |
| 17 | Trace 检索 | `/admin/traces` | —（13.6.5） | Agent 工具页 |
| 18 | 候选记忆 | `/admin/memory` | —（13.6.5） | Trace 页 |
| 19 | 演练回放 | `/admin/drills` | —（只读展示） | 系统健康页 |
| 20 | 错误页 | `/403 /404 /500` | —（复用空态模式） | 全局 |
| 21 | 全局搜索结果/空态 | `/search?q=` | 搜索无结果-空态 | 顶栏搜索 |

> 26 个设计稿 → 页面/组件/API 的逐条映射见**附录 D**。

### 13.4 设计系统（Design Tokens）

#### 13.4.1 令牌体系

原型以 `--edp-*` CSS 自定义属性定义主题，前端将其作为单一事实来源，同步映射到 Antd 5 `theme.token`：

| 令牌 | 亮色值 | 暗色值 | Antd Token 映射 |
|---|---|---|---|
| `--edp-background` | `#f7f8fc` | `#0b0c14` | `colorBgLayout` |
| `--edp-card` | `#ffffff` | `#131520` | `colorBgContainer` |
| `--edp-foreground` | `#172033` | `#e8ebf2` | `colorText` |
| `--edp-primary` | `#5b5ce2` | `#7b7cf0` | `colorPrimary` |
| `--edp-primary-50/100/200` | `#ececff / #dcdcff / #c6c7ed` | `#1e1f3a / #2a2b4d / #3d3e6a` | 计算色板（`#5b5ce2` 生成） |
| `--edp-muted-foreground` | `#788298` | `#9aa1af` | `colorTextSecondary` |
| `--edp-border` | `#e8ebf2` | `#2a2d3d` | `colorBorder` |
| `--edp-radius-small/medium/large` | `4 / 8 / 12px` | 同 | `borderRadiusSM / borderRadius / borderRadiusLG` |
| `--edp-shadow-1/2/3` | 卡片/悬浮/弹窗三级阴影 | 同 | Antd 阴影 |

状态色（独立于主色，全局语义令牌）：

| 令牌 | 亮色 前景/背景 | 用途 |
|---|---|---|
| `--edp-state-success` / `-bg` | `#12a47d` / `#e9fbf4` | 成功、健康、运行中、VALID、L1 低风险 |
| `--edp-state-warning` / `-bg` | `#d97706` / `#fff7e8` | L2 中风险、降级、重试、待审批、WARN |
| `--edp-state-error` / `-bg` | `#df4f5f` / `#fff0f2` | P0/P1 高风险、失败、拒绝、ERROR、危险按钮 |
| `--edp-state-info` / `-bg` | `#3b82f6` / `#edf5ff` | Derived 证据、info 事件、INFO 日志 |

字体：`Inter + Noto Sans SC`（正文）/ `ui-monospace + Consolas`（ID、哈希、日志）；字号阶 `10/11/12/14/18/20/24px`，列表主文本 12px、页面标题 20px、KPI 数值 20~24px。

主题切换：`html.dark` class 切换 + `prefers-color-scheme` 初始化 + localStorage 记忆；所有颜色仅经令牌引用，禁止硬编码。

#### 13.4.2 图标与品牌

- 图标库 Lucide（原型同源）；侧边栏 Logo：`E` 字 36px 圆角块（primary 底）+ "AEOS EDP / Evidence Data Platform" 双行字；
- 租户/用户头像：两字母缩写圆块（primary-50 底 + primary 字）。

#### 13.4.3 状态语义色全局映射（强制字典）

| 状态域 | 枚举 → 语义色 |
|---|---|
| 风险等级 | P0 灾难(error) / P1 高(error) / P2 中(warning) / P3 低(success) |
| 对象派生状态 | Healthy(success) / Watch(info) / At Risk(warning) / Blocking(error) / DQ Exception(error) / Delayed(warning) |
| 适配器 | 运行中(success) / 降级(warning) / 停用(muted) |
| 任务 | 运行中(warning) / 成功(success) / 失败(error) |
| 日志级别 | INFO(info) / WARN(warning) / ERROR(error) |
| 证据 | VALID(success) / INVALID(error) / EXPIRED(muted) |
| 审计结果 | 成功/允许(success/info) / 拒绝(error) |
| 租户 | ACTIVE 运行中(success) / PROVISIONING 开通中(info) / SUSPENDED 已暂停(warning) / CANCELLED 已注销(muted) |

#### 13.4.4 枚举统一（原型 ↔ 后端契约对齐决策）

原型为视觉稿存在命名不一致，以下映射为**冻结决策**，前端经 `shared/enums.ts` 单点转换：

| 域 | 后端契约（存储/API） | 前端展示 |
|---|---|---|
| 风险等级 | `P0/P1/P2/P3`（event/decision） | 展示 P 系 pill；原型 L 系作废（L3→P1、L2→P2、L1→P3 归档映射仅用于原型对照） |
| 能力风险等级 | `L0~L3`（capabilities 表，能力操作风险） | 仅在 Agent 工具页展示，与业务风险 P 系严格区分 |
| 套餐 plan | `TRIAL / STANDARD / PREMIUM / DEDICATED` | 体验版 / 基础版 / 专业版 / 企业版（原型 professional/basic/enterprise 命名作废；DEDICATED=企业版·独立部署） |
| 角色 | `PLATFORM_ADMIN / ADMIN / MANAGER / ANALYST / SERVICE` | 平台运营 / 工作空间管理员 / 数据管理员·业务负责人 / 审计员·操作员 / 服务主体（原型 Workspace Admin/Data Steward/Data Owner/Business Owner/Operator/Auditor 六名归并为五角色 + 数据范围区分） |
| 事件类型 | dotted 风格：`order.created / inventory.changed / purchase.delayed / capability.result.* / decision.approved / action.completed / quality.* / adapter.failed` | 展示名中文映射（如"订单创建"）；类型筛选器用此字典 |
| 来源系统 | `erp / mes / plm / mdm / wms / agent-hub / human / adapter` | 展示名映射：ERP-S4 / MES / PLM / MDM / WMS / DQ Engine / Human / Adapter（展示名可配置） |
| 业务 ID | UUID 主键 | 短 ID = 类型前缀 + UUID 前 4~8 位（`evt-8f32` / `ev-73c2`），mono + 可复制 + tooltip 全量；业务编号（`case_no=DC-20260928-007`、`source_id=ORD-202609-001`）优先展示 |

### 13.5 应用壳层（Shell）

布局：固定左侧栏 250px + 顶栏 66px，内容区 `padding 24px`、`max-width 1440px` 居中；≤1200px 时 KPI 网格 4→2 列，≤900px 双栏折叠单列。

| 区块 | 规格（对齐原型） |
|---|---|
| 侧边栏·Logo 区 | 高 70px，Logo + 产品名 |
| 侧边栏·租户切换器 | 常驻卡片按钮：租户头像 + 名称 + 套餐·环境副标题 + 下拉箭头；点击弹出租户切换弹窗（13.6.4）；当前租户高亮 + "当前"徽标 |
| 侧边栏·导航 | 分四组（13.3），项 = 图标 + 文字（12px），激活态 primary 底色圆角块；`智能闭环` 组仅 PLATFORM_ADMIN/ADMIN 可见 |
| 侧边栏·用户区 | 头像 + 姓名 + 角色名 + 设置按钮（设置含主题切换） |
| 顶栏·面包屑 | `EDP / {当前页名}`（`data-slot="crumb"`） |
| 顶栏·全局搜索 | 330px 输入框，placeholder"搜索对象、事件、证据…"；回车跳 `/search?q=`，跨 objects/events/evidence 三索引查询 |
| 顶栏·通知 | 铃铛 + 未读徽标数；下拉为消息中心（质量任务完成/校验失败/Guard 告警） |
| 顶栏·命令面板 | `⌘K`（浏览器快捷键 + 按钮），命令：导航到各页、切换租户、触发同步、切主题 |
| 顶栏·用户菜单 | 头像 + 姓名 + 下拉：个人设置 / 退出登录 |

可访问性：所有弹窗 `role="dialog" aria-modal="true"`；抽屉 `aria-modal`；关闭按钮 `aria-label="关闭"`；可交互元素均带 `data-dom-id` 锚点（E2E 选择器，命名沿用原型）。

### 13.6 页面规格

> 每页给出：布局区块 → 关键字段（对齐 API 响应）→ 数据来源。通用交互（分页/筛选/空态）不重复，见 13.7。

#### 13.6.1 运营总览 `/admin/overview`（设计稿：运营总览）

| 区块 | 内容 | 数据来源 |
|---|---|---|
| Hero 状态卡 | 运行状态 pill（运行中·多租户工作空间）+ 动态标题（"今天的 EDP 状态：证据链健康，N 个 P1 风险需要处理"）+ 主/次按钮（查看风险详情→风险抽屉 / 导出日报）+ 内嵌三指标（对象覆盖率、P95 接入延迟、适配器成功率） | `GET /admin/quality/coverage` + `GET /health?deep=true` + `GET /admin/adapters` |
| KPI 网格（8 卡） | 业务对象数(+日环比) / 24H 事件(峰值) / 证据存储(+今日) / 适配器成功率 / DLQ 队列(warning 色) / P95 延迟 / 审计日志量(近 7 天) / 策略命中(+今日) | 聚合自 health/quality/audit-logs/events |
| 重点风险列表 | 风险卡 ×3：等级 pill + 对象短 ID + 时间 + 标题 + 描述（如"供应商 S-118 预计交期延迟 14 天，物料 X 缺口 1000"）；点击开风险抽屉 | `GET /ebms/exceptions?severity=P1&limit=3` |
| 事件时间线 | 垂直时间线 5 节点（时间/事件文本/关联 ID·来源，语义色圆点），右上"进入事件流" | `GET /events?limit=5` |
| 三栏图表区 | 数据健康（24H mini 柱图 + 4 子指标）/ 证据链健康（环形进度 100% + Primary/Derived 计数 + 校验和有效率）/ 审计动态（4 条记录） | quality reports + evidence 统计 + audit-logs |

风险抽屉（设计稿：风险详情-抽屉）：右侧 420px，避让侧边栏；分区：头部（风险事件 RSK-短ID + 等级 pill + 状态·类别·时间）→ 受影响对象卡（对象名 + 2 迷你指标格如"物料缺口 1,000 件 / 预计延迟 14 天"）→ 事件时间线（4 节点）→ 关联证据（可点击行：图标 + ID·名称 + 格式·时间·附注 + 外链箭头）→ 底部操作（创建任务 / 标记处理）。

#### 13.6.2 数据工作台

**业务对象 `/admin/registry`**（设计稿：业务对象 + 空态 + 新建弹窗）

- 工具栏：搜索（对象 ID/名称/来源）+ 域下拉（全部域/Delivery/Sales/R&D/Procurement/Master）+ 状态下拉（Healthy/Watch/At Risk/Blocking/DQ Exception/Delayed，派生规则见下）+ 卡片/表格分段切换 + 筛选；
- 对象卡片：等级 pill + 类型标签（Order/Product/Customer/PurchaseOrder）+ `source_id`（ORD-202609-001，mono）+ 名称 + 域·来源 + 风险评分进度条（0-100 按等级着色）+ 标签 chips（VIP客户/交期紧/物料X）+ `Rev 18 · 时间` + 查看详情；
- 对象派生状态 = f(最新能力结果 risk_level, DQ 异常, 同步时延)：P0/P1→At Risk/Blocking、quality 异常→DQ Exception、同步延迟超阈→Delayed、无→Healthy/Watch（前端纯展示派生，不落库）；
- 新建弹窗字段：对象名称* / 对象编码*（示例 CUST-MASTER-001）/ 所属域* select（订单/客户/供应商/物料）/ 数据来源* 多选 chip（ERP/MDM/CRM）/ 责任人 / 描述 textarea；必填校验行内错误（"对象名称不能为空，且不能与已有对象重复"）→ `POST /objects`；
- 空态：search-x 圆形图标 + "未找到业务对象" + "新建对象 / 清空筛选"双按钮；
- API：`GET /objects`（游标分页）、`GET /objects/{id}`、`POST /objects`、`GET /objects/{id}/history`。

**事件流 `/admin/events`**（设计稿：事件流 + 事件回放向导）

- KPI 带：24H 事件 / P95 接入延迟 / 幂等命中率 / 死信队列（warning）；
- 工具栏：搜索 + 事件类型下拉（dotted 字典）+ 时间范围（24H/7D/30D）+ 筛选；
- 表格 9 列：`事件(短ID mono) | 类型(彩色 pill) | 对象(短ID) | 描述(truncate 240px) | 发生时间 | 接入耗时 | 来源(展示名) | 状态(DELIVERED) | 操作(详情)`；
- 分页：左"显示 1–8 条，共 18,421 条" + 右页码（游标式，后端 `next_cursor` 驱动）；
- 回放向导（三步 stepper 弹窗，720px）：① 选择事件（列表选中回显）→ ② 配置参数（目标适配器 select / 回放模式 radio 卡片：按原序·并发 / 开始时间 datetime-local；底部只读事件摘要卡）→ ③ 确认执行；用于演示环境事件重放；
- API：`GET /events`、`GET /events/{id}`；回放由 `POST /admin/adapters/{name}/sync`（重放模式）承载。

**证据库 `/admin/evidence`**（设计稿：证据库 + 证据重新索引向导 + 搜索无结果空态）

- KPI 带：证据数量 / 对象覆盖率 / 校验和有效(success) / 原文访问 24H；
- 双栏 1.2fr | 0.8fr：
  - 左·证据列表（卡内搜索）：证据卡 = 类型 pill（Primary=primary-50 / Derived=info）+ 标题 + 状态 pill（VALID）+ `短ID · 来源/集合/业务键` + 描述 + 底栏（时间 · 哈希缩写 `a4c1…9f3d` mono · 归属部门）；
  - 右·证据链图：垂直链式节点（圆形图标 + 名称 + 短 ID + 类型 + 业务键 + 时间，Derived 节点 info 色），底部"链上校验"区（"N 份证据校验和均有效，依赖关系完整"）；
- 页头操作：完整性抽检（→ 触发 checksum 抽检任务）/ 重建索引（→ 三步向导：① 选择范围=对象集合多选卡+日期范围 → ② 校验规则 radio 卡片=完整性/血缘/完整性与血缘 → ③ 执行确认=预估条数 41.5K + 预计耗时约 6 分钟）；
- 已生效筛选以 removable chip 呈现（`关键词：order_2026` `来源：ERP-S4` `状态：VALID`）；空态三件套 + 建议替代关键词；
- API：`GET /evidence`、`GET /evidence/{id}`、`GET /evidence/{id}/verify`（校验按钮联动结果 pill）、`GET /evidence?ref_type=&ref_id=`（链图按对象聚合）。

#### 13.6.3 运维监控

**数据质量 `/admin/quality`**（设计稿：数据质量 + 重新校验弹窗）

- KPI：综合质量 97.8% / 时效性 SLA / 完整性 / 待处理异常（含"N 项高优先级"error 角标）；
- 左栏·维度评分：按数据域（ERP·订单 / WMS·库存 / PLM·产品就绪度 / MDM·客户 / PROCURE·采购）进度条，<95 warning 色；
- 右栏·异常卡：优先级 pill（高/中）+ 对象短 ID + 详情 + "处理"按钮；尾部合并提示（"剩余 6 项异常已合并为低优先级队列"）；
- 重新校验弹窗：校验维度 2×2 复选卡（完整性/一致性/时效性/唯一性，默认全选）+ 范围 radio（全部对象/仅异常对象）+ info 提示条（"校验完成后经消息中心通知，并自动更新评分与异常列表"）；
- 任务日志抽屉：头部（任务 TASK-YYYYMMDD-#### mono + 运行中 pill）+ 元信息（开始时间/已耗时）+ 日志时间线（时间 mono + 级别 pill INFO/WARN/ERROR + 正文）+ 底部"下载日志"；
- API：`GET /admin/quality/reports`、`GET /admin/quality/coverage`；重校验/任务日志 W5 由质量任务 API 承载（进度经 Outbox 通知刷新）。

**审计日志 `/admin/audit`**（设计稿：审计日志 + 导出弹窗 + 新建策略弹窗）

- KPI：策略检查（24H）/ 通过（98.5% 自动放行）/ 需审批（39 等待人工复核）/ 拒绝（6 违反策略已阻断）；
- 左栏·策略列表：策略编号（P-0042）+ 效果 pill（允许 success/拒绝 error）+ 规则（资源→动作）+ 控制方式（角色控制/自动允许/仅人工）；
- 右栏·审计表格 7 列：`时间 | 操作者 | 动作 | 目标(资源标识 mono) | 对象 ID(mono) | 租户 | 结果(pill)`；
- 导出弹窗：时间范围（起止 date）/ 操作人 multi-select / 操作类型复选（READ/WRITE/DELETE/LOGIN）/ 导出格式 radio（csv/excel/json）/ 文件名（默认 audit-log-export）；
- 新建策略弹窗：策略名称 / 适用对象 select（角色）/ 审计动作 checkbox（读取/写入/删除）/ 风险等级 pill toggle（P1/P2/P3）/ 告警方式 select（站内+邮件/仅站内/仅邮件/站内+短信/全部）/ 启用 toggle；
- GUARD_DENIED 记录在表格中红色高亮标注（越权可视化，支撑"AI 越权 0 次"举证）；
- API：`GET /audit-logs`（筛选参数对齐导出弹窗字段）。

**适配器管理 `/admin/adapters`**（设计稿：适配器管理 + 新增/测试/连接弹窗 + 任务日志抽屉）

- KPI：已连接系统（租户级/共享拆分）/ 数据产品 / 适配器可用率（30 天 SLA）/ 死信队列；
- 表格 7 列：`系统 | 接入方式(REST 拉取/REST 推送) | 责任团队 | 最近同步 | 健康度(99.9%) | 状态(运行中/降级) | 隔离范围(租户级/共享→租户)`；
- 底部双卡：数据接入流水线（适配器→事件→证据→审计 四节点横向流程 + 当前租户队列状态 + 待处理事件数）/ Tenant Isolation（命名空间隔离·凭证分离 100%、共享资源池配额 72%、共享→租户路由 MasterHub）；
- 新增适配器弹窗：名称 / 系统类型 select（ERP-S4/MDM/CRM/custom）/ 接入方式 select（REST/Kafka/DB）/ Endpoint / 认证信息**可折叠面板**（App Key + App Secret password）/ 默认租户隔离 switch / "测试连接"按钮（成功行内提示"连接成功"）；
- 测试适配器弹窗：目标摘要卡 + 测试目标复选（Ping/Metadata/Sample Event）+ 进度日志时间线（✓ 标题 + mono 详情 + 时间戳）+ 结果横幅（"全部测试通过"）+ 重新测试；
- 数据源连接弹窗（三步 stepper）：① 连接信息（主机/端口 5432/数据库/用户名/密码/SSL 模式 select：prefer/require/disable/verify-ca/verify-full）→ ② Schema 选择（复选：public/sales/inventory）→ ③ 测试连接（success 横幅）；
- API：`GET /admin/adapters`、`POST /admin/adapters/{name}/sync`、`GET /admin/adapters/{name}/status`。

**系统健康 `/admin/systems`**（无设计稿，MSW 先行）

- HA 状态卡（Patroni 主从角色/复制延迟/副本数，来自 `GET /health?deep=true` 的 `db_ha`）+ 备份卡（最近全量/WAL 归档时点/恢复验证状态）+ Outbox 积压卡 + 告警渠道配置卡；M5 三项演练记录入口 → `/admin/drills`。

#### 13.6.4 平台配置（租户）

**租户管理 `/tenants`**（设计稿：租户管理 + 4 弹窗）

- 三联卡：租户信息（头像 + 名称 + 套餐·环境 + 租户 slug/区域 mono + 状态 pill）/ 成员列表（姓名 + 角色中文名，计数角标）/ 配额用量（4 进度条：每日事件 18.4K/100K、证据存储 684GB/2TB、API 调用 2.8M/10M、成员数 42/100，按水位着色，"实时"角标）；
- 角色权限矩阵（只读展示）：行=角色、列=模块（业务对象/事件/证据/审计日志/质量/策略），值 R/RW/Governed/Policy + 图例；编辑入口走权限分配弹窗；
- 新建租户弹窗：租户名称* / 租户编码*（slug，"全局唯一标识，创建后不可修改"helper）/ 套餐版本* radio 卡片（基础版/专业版/企业版，按 13.4.4 映射 plan 枚举）/ 数据范围* 复选（华东/华南/华北）/ 管理员邮箱* / 备注 + **配额预览三卡**（对象数/日事件/存储，随套餐联动：STANDARD 5K/5K/100GB · PREMIUM 30K/30K/500GB · DEDICATED 100K/100K/2TB）→ `POST /tenants`；
- 邀请成员弹窗：邮箱 / 角色 select（按 13.4.4 五角色）/ 租户访问范围复选 chip（数据工作台/运维监控/平台配置，映射侧边栏分组可见性）/ 备注 → `POST /tenants/{id}/members`；
- 权限分配弹窗：角色信息横幅（角色名 + "已分配 N 位用户" + 职责描述）+ 权限矩阵（行=7 模块、列=查看/编辑/删除 checkbox，`perm-{module}-{action}` 锚点）→ `PATCH /tenants/{id}/members/{mid}`（角色变更）+ 权限矩阵提交；
- 租户切换弹窗（顶栏常驻入口）：租户列表项（头像 + 名称 + "当前"徽标 + 套餐·环境 + 选中 check）+ 整宽"确认切换"→ `POST /tenants/{id}/context`（仅 PLATFORM_ADMIN）；
- **租户注销为强确认**（13.7 模式 10）：输入租户 slug 解锁确认按钮 + 原因必填 + 双人复核提示 → `POST /tenants/{id}/cancel {confirm:true, reason}`；
- 生命周期操作：暂停/恢复（`POST /tenants/{id}/suspend|resume`，SUSPENDED 租户徽标即时变 warning）。

#### 13.6.5 智能闭环页（无高保真稿，按本规范实现，复用 13.7 模式）

| 页面 | 规格 | API |
|---|---|---|
| 闭环案例 `/cases` | 筛选（状态 OPEN/DECIDED/CANCELLED + 风险等级）+ 表格（案例编号 case_no / 问题 / 风险 pill / 状态 / 创建时间 / 操作） | `GET /decisions/cases` |
| 案例详情 `/cases/:id`（**M4 关键**） | 一屏闭环叙事：① 问题卡（question + context 影响说明 + 风险 pill + 选项列表）② 证据链横向图（Result→Decision→Evidence→源记录，节点可点开证据详情/verify）③ Steps 时间线（事件→案例→审批记录→Action 状态推进，Human-Only 节点带人形图标）④ 关联风险抽屉（复用风险详情抽屉） | `GET /decisions/cases/{id}`、`GET /evidence?ref_type=CASE`、`GET /actions?case_id=` |
| 决策 `/decisions` | 待决列表 + 决策表单（选项 radio = case.options + 意见 textarea）；提交为 Human-Only，AI principal 不可见按钮 | `POST /decisions/cases/{id}/records` |
| 行动 `/actions` | 9 态状态机可视化（状态矩阵/时间线双视图）+ 状态流转操作（allowed_to 驱动按钮渲染，422 后按服务端返回重渲染）+ Human-Only 转移（APPROVED→EXECUTING、COMPLETED→VERIFIED）人形图标标注 | `GET /actions`、`PATCH /actions/{id}/status` |
| Agent 工具 `/admin/tools` | 已注册能力卡（name/domain/risk_level L 系/permission/endpoint）+ 工具清单（`/tools/*` 只读接口在线试查表单：选工具 + 参数 → JSON 响应 + evidence_hint 展示） | `GET /capabilities`、`GET /tools/*` |
| Trace `/admin/traces` | 筛选（agent_id/task_id/capability）+ Trace 列表 + 详情（执行 DAG：输入→工具调用链（seq/latency/status）→LLM 输出 + token_usage + evidence_refs 链接） | `GET /traces`、`GET /traces/{id}` |
| 候选记忆 `/admin/memory` | CANDIDATE 列表 + 评审操作（批准/拒绝 + 意见，Human-Only）+ APPROVED 知识库视图 | `GET /memories`、`PATCH /memories/{id}/review` |
| 演练回放 `/admin/drills` | W5 三项演练只读记录卡（HA 切换/PITR/租户恢复：时间线 + RTO/RPO 实测值 + 手册链接） | 演练记录数据集（W5 产出） |

### 13.7 通用组件与交互模式（17 条，`components/` 封装）

| # | 模式 | 规格 | 使用页面 |
|---|---|---|---|
| 1 | 状态 Pill | 语义色字典（13.4.3）驱动；小号 10~11px + 圆点可选 | 全站 |
| 2 | Chip 过滤器 | 已生效筛选 removable chip（`关键词：x`/`来源：y`）+ 工具栏筛选按钮 | 列表页通用 |
| 3 | KPI 指标卡 | 标签(10px 大写) / 大数值 / 辅助说明 / 右上图标（语义色底）；4 列网格响应式 2 列 | 总览/事件/证据/质量/审计/适配器 |
| 4 | 垂直时间线 | 语义色圆点 + 时间/文本/关联 ID·来源三行结构 | 总览/风险抽屉/案例详情 |
| 5 | 卡片↔表格视图切换 | 分段控件；卡片网格 3 列响应式 | 业务对象 |
| 6 | 模态表单 | 图标徽标 + 标题 + 关闭 X；`取消`+主行动按钮（带图标）；底栏 border-top；宽 480/520/640 三档 | 全部弹窗 |
| 7 | 三步向导 Stepper | 圆形序号 + 标题/副标 + 连接线（完成=primary）；底栏 `上一步(disabled@首步)/下一步(末步=完成)`；事件摘要/预估条只读卡 | 事件回放/证据重索引/数据源连接 |
| 8 | 右侧抽屉 | 420px，`left-[250px]` 避让侧边栏；头部(标题+元信息) → 滚动主体分区 → 底部操作栏 | 风险详情/任务日志 |
| 9 | 空态三件套 | 圆形 muted/primary-50 底大图标(search-x 等) + 标题 + 引导文案 + 双动作（清除筛选 primary 辅助 / 新建） | 全站列表/搜索 |
| 10 | 危险确认 | 分级：一般删除=红色图标块 + 后果文案（`<code>` 高亮对象 + "无法恢复" + 级联影响声明）+ 红底确认按钮；**强确认**=额外"输入 {slug/名称}"输入框解锁按钮（租户注销等不可逆操作） | 删除业务对象/租户注销 |
| 11 | 权限矩阵 | 行=模块/角色、列=操作/角色 的 checkbox 或只读值（R/RW/Governed）+ 图例 | 租户管理/权限分配 |
| 12 | 配额进度条 | 当前值/配额 + 百分比；<70% primary、70~90% warning、>90% error；"实时"角标 | 租户配额/资源池 |
| 13 | Mono 短 ID | 类型前缀 + UUID 前 4~8 位（`evt-8f32`）；可复制 + tooltip 全量；哈希缩写 `a4c1…9f3d` 格式 | 全站 ID/哈希 |
| 14 | 游标分页条 | 左"显示 X–Y 条，共 N 条" + 右页码（后端 next_cursor 驱动，禁用越界） | 全站表格 |
| 15 | 可折叠面板 | chevron 旋转 + aria-expanded；用于密钥/高级选项收纳 | 新增适配器认证信息 |
| 16 | 进度日志时间线 | 任务日志：时间(mono) + 级别 pill(INFO/WARN/ERROR) + 正文；完成项 check 图标 + mono 详情行 + 时间戳 | 任务日志/测试适配器/演练回放 |
| 17 | 徽标计数 | 铃铛未读数 / 成员计数 / "实时"角标 / KPI 卡 warning 角标 | 壳层/租户/质量 |

### 13.8 多租户与权限的前端呈现

- **租户上下文**：登录响应的 `tenant` 写入上下文；非平台运营用户租户固定（切换器只读展示）；PLATFORM_ADMIN 经租户切换弹窗调 `POST /tenants/{id}/context`，切换后全站 Query 缓存清空重拉（`queryClient.clear()`），页面数据即时切至目标租户，面包屑旁显示当前租户徽标；
- **SUSPENDED 呈现**：任何接口返回 `403 TENANT_SUSPENDED` → 顶栏横幅"当前租户已暂停，请联系平台管理员"，写操作全部禁用；
- **导航权限**：侧边栏分组按角色渲染——`平台配置`（租户管理）仅 PLATFORM_ADMIN；`智能闭环` 组 ADMIN+；`数据工作台/运维监控` 全角色（ANALYST 只读：所有写按钮隐藏，依赖后端 RBAC 兜底）；
- **Human-Only 呈现**：决策审批、Action 执行/验证、记忆评审等 Human-Only 操作按钮带"人形"图标 + tooltip"仅人工可执行"；服务 principal（AI）请求被拒的记录在审计页 GUARD_DENIED 高亮。

### 13.9 前后端契约与状态处理

#### 13.9.1 契约治理

`api-sdk` 由后端 `/openapi.json` 自动生成（openapi-typescript）；契约快照与指纹存于 `contracts/`（2.3.4），CI 双门禁：后端导出契约与 `contracts/openapi.json` 不符 → 后端 PR 失败；`api-sdk` 与 `contracts/openapi.sha256` 不符（改契约未重生成 SDK）→ 前端 PR 失败。契约冻结（W1 末）后变更走 PR + Tech Lead 评审 + SDK 重生成三联动。

#### 13.9.2 请求与会话

- 认证：HttpOnly Cookie（access 2h / refresh 7d）+ CSRF Token 头；API Key 仅后端服务用，前端不持有；
- 拦截器链（`api-sdk`）：401 → refresh 单飞重放 → 失败跳 `/login`；429 → `Retry-After` 指数退避自动重试（上限 3）；`TENANT_SUSPENDED` → 全局横幅；网络错误 → toast + 重试按钮；
- 错误码 13 种全覆盖（对齐附录 B.0）：`VALIDATION_ERROR`（表单行内映射字段）/ `UNAUTHENTICATED`（跳登录）/ `FORBIDDEN`（403 页）/ `TENANT_FORBIDDEN`（403 页 + "无权访问该租户"文案）/ `TENANT_SUSPENDED`（横幅）/ `GUARD_POLICY_DENIED`（"该操作仅限人工执行"提示）/ `NOT_FOUND`（404 页）/ `METHOD_NOT_ALLOWED`（提示上报，正常不可达）/ `CONFLICT`（"数据已被他人修改，已刷新"自动重拉）/ `INVALID_TRANSITION`（按响应 `allowed_to` 重渲染状态机按钮）/ `RATE_LIMITED`（退避 toast）/ `UPSTREAM_UNAVAILABLE`（"源系统暂不可达，稍后重试"）/ `INTERNAL`（500 页 + request_id 可复制）。

#### 13.9.3 性能

首屏路由级代码分割；列表页游标分页 + `keepPreviousData`；KPI/报表摘要读预聚合（`management.kpi_values`）保证 <2s 感知；图表随窗口 resize 防抖；轮询仅总览页（30s）与健康页（10s deep）。

### 13.10 质量保障与演示支撑

| 项 | 策略 |
|---|---|
| Storybook | 17 条模式 + 9 个核心组件（状态 pill/chip/详情 Tab/删除确认/空态/搜索空态等）成文档；26 设计稿关键状态建视觉回归基线（chromatic 或 playwright-screenshot） |
| MSW | 契约冻结前 + 后端未就绪页面（系统健康/演练回放/W4 前的 cases）用 MSW handler 按 B 组响应示例造数，切换仅改环境变量 |
| Playwright E2E | ① M4 闭环脚本：登录 → 总览风险卡 → 风险抽屉 → 案例详情证据链 → 审批 → Action 执行 → Verified；② 多租户隔离：A 租户数据在 B 租户上下文不可见（403/空列表断言）；选择器全用 `data-dom-id` |
| 视觉对齐 | EDP-102（W1）以原型截图为基线建 Storybook 对照；偏差走 PR 评审 |
| 演示支撑 | M4 演示 7 分钟叙事脚本：① 总览开场（1min KPI+风险）→ ② 风险抽屉下钻（1.5min 时间线+证据）→ ③ 案例详情一屏讲证据链（2min Result→Decision→Evidence→源记录 + verify）→ ④ HITL 审批 + Action 闭环（1.5min）→ ⑤ 回到总览看闭环事件回流（1min）；演示数据由 EDP-016 一键 seed（覆盖 AEOS 计划 §10 十类评估场景）+ 重放 |

---

## 附录 A：完整 DDL（PostgreSQL 16）

> 通用约定：
> 1. **多租户**：除下列**控制平面表**外，所有业务表均含 `tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id)`，DDL 中以注释 `-- + tenant_id` 表示该列。控制平面表（不启用 RLS，仅平台运营/审计路径可访问）：`platform.tenants`、`platform.tenant_members`、`platform.tenant_quotas`、`platform.tenant_usage_daily`、`platform.audit_logs`（横切审计，含可空 `tenant_id`，NULL=平台级事件）。
> 2. **RLS 模板**（适用于全部含 `tenant_id` 的表，见 3.4；Alembic 迁移随建表同版本执行）：
> ```sql
> ALTER TABLE <schema>.<table> ENABLE ROW LEVEL SECURITY;
> ALTER TABLE <schema>.<table> FORCE ROW LEVEL SECURITY;
> CREATE POLICY tenant_isolation ON <schema>.<table>
>     USING (tenant_id = current_setting('app.tenant_id')::uuid)
>     WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
> ```
> 3. 所有业务表均含审计字段 `created_by TEXT NOT NULL DEFAULT 'system'`、`created_at TIMESTAMPTZ NOT NULL DEFAULT now()`、`updated_by TEXT`、`updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`；DDL 中以 `-- + 审计字段` 表示。
> 4. 枚举一律 `TEXT + CHECK`，不用原生 ENUM。
> 5. 迁移由 Alembic 管理（`edp_migrator` BYPASSRLS 账号执行），按 Schema 分版本链；本文为逻辑全集。
> 6. 唯一约束默认含 `tenant_id` 前缀（跨租户唯一仅限全局标识：UUID 主键、`api_keys.key_hash`、`event.events.event_id`——UUIDv5 命名空间含 tenant，全局唯一即租户内唯一）。

### A.1 platform —— 平台基础与租户控制平面

```sql
CREATE SCHEMA platform;

-- ========== 控制平面（不启用 RLS；仅平台运营 API/审计路径访问） ==========

-- 租户主表（平台根实体）
CREATE TABLE platform.tenants (
    tenant_id    UUID PRIMARY KEY,
    slug         TEXT NOT NULL UNIQUE,           -- 子域名/路由标识
    name         TEXT NOT NULL,
    plan         TEXT NOT NULL DEFAULT 'STANDARD' CHECK (plan IN ('TRIAL','STANDARD','PREMIUM','DEDICATED')),
    status       TEXT NOT NULL DEFAULT 'PROVISIONING' CHECK (status IN ('PROVISIONING','ACTIVE','SUSPENDED','CANCELLED')),
    tenant_shard INT NOT NULL DEFAULT 0,         -- 预留：水平分片接缝
    cancel_scheduled_at TIMESTAMPTZ,             -- CANCELLED 后数据清理时点（保留 30 天）
    attributes   JSONB NOT NULL DEFAULT '{}'
    -- + 审计字段
);
CREATE INDEX idx_tenants_status ON platform.tenants(status);

-- 租户成员（用户↔租户绑定 + 租户内角色；替代独立 user_roles 表）
CREATE TABLE platform.tenant_members (
    member_id    UUID PRIMARY KEY,
    tenant_id    UUID NOT NULL REFERENCES platform.tenants(tenant_id),
    user_id      UUID NOT NULL REFERENCES platform.users(user_id),
    member_roles TEXT[] NOT NULL DEFAULT '{}',   -- ADMIN / MANAGER / ANALYST
    status       TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('INVITED','ACTIVE','DISABLED')),
    invited_by   TEXT
    -- + 审计字段
);
CREATE UNIQUE INDEX uq_tenant_member ON platform.tenant_members(tenant_id, user_id);

-- 租户配额（3.5 防护配置）
CREATE TABLE platform.tenant_quotas (
    tenant_id         UUID PRIMARY KEY REFERENCES platform.tenants(tenant_id),
    api_rate_limit    INT NOT NULL DEFAULT 100,          -- req/min
    batch_max_events  INT NOT NULL DEFAULT 1000,
    query_timeout_ms  INT NOT NULL DEFAULT 5000,
    pool_share        NUMERIC(5,2) NOT NULL DEFAULT 2.0, -- 连接池占比 %
    storage_gb        INT NOT NULL DEFAULT 50,
    events_per_month  INT NOT NULL DEFAULT 1000000
    -- + 审计字段
);

-- 使用量统计（日粒度；Phase 2 计费输入）
CREATE TABLE platform.tenant_usage_daily (
    id           UUID PRIMARY KEY,
    tenant_id    UUID NOT NULL REFERENCES platform.tenants(tenant_id),
    usage_date   DATE NOT NULL,
    api_calls    BIGINT NOT NULL DEFAULT 0,
    events_in    BIGINT NOT NULL DEFAULT 0,
    storage_gb   NUMERIC(12,2) NOT NULL DEFAULT 0,
    throttled_429 BIGINT NOT NULL DEFAULT 0
    -- + 审计字段
);
CREATE UNIQUE INDEX uq_usage_daily ON platform.tenant_usage_daily(tenant_id, usage_date);

-- ========== 业务表（含 tenant_id + RLS） ==========

-- 组织（租户内层级，非隔离边界）
CREATE TABLE platform.organizations (
    org_id      UUID PRIMARY KEY,
    tenant_id   UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    name        TEXT NOT NULL,
    parent_org_id UUID REFERENCES platform.organizations(org_id),
    status      TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','DISABLED'))
    -- + 审计字段
);
CREATE INDEX idx_orgs_tenant ON platform.organizations(tenant_id);

-- 用户（全局身份；租户归属经 tenant_members）
CREATE TABLE platform.users (
    user_id       UUID PRIMARY KEY,
    tenant_id     UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS；归属租户（成员关系另见 tenant_members）
    username      TEXT NOT NULL,
    email         TEXT NOT NULL,
    password_hash TEXT NOT NULL,                -- Argon2id
    display_name  TEXT NOT NULL,
    org_id        UUID REFERENCES platform.organizations(org_id),
    principal_type TEXT NOT NULL DEFAULT 'HUMAN' CHECK (principal_type IN ('HUMAN','AI')),
    is_platform_admin BOOLEAN NOT NULL DEFAULT FALSE,   -- 平台运营账号（跨租户，登录后可切换租户上下文）
    status        TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','DISABLED'))
    -- + 审计字段
);
CREATE UNIQUE INDEX uq_users_username ON platform.users(tenant_id, username);
CREATE UNIQUE INDEX uq_users_email    ON platform.users(tenant_id, email);

-- 角色 / 权限 / 授权（全局模板）
CREATE TABLE platform.roles (
    role_id UUID PRIMARY KEY,
    code    TEXT NOT NULL UNIQUE,               -- PLATFORM_ADMIN / ADMIN / MANAGER / ANALYST / SERVICE
    name    TEXT NOT NULL
    -- + 审计字段
);

CREATE TABLE platform.permissions (
    permission_id UUID PRIMARY KEY,
    code          TEXT NOT NULL UNIQUE,         -- 如 evidence:read
    resource      TEXT NOT NULL,
    action        TEXT NOT NULL
);

CREATE TABLE platform.role_permissions (
    role_id       UUID REFERENCES platform.roles(role_id),
    permission_id UUID REFERENCES platform.permissions(permission_id),
    PRIMARY KEY (role_id, permission_id)
);

-- API 密钥（服务主体；绑定租户）
CREATE TABLE platform.api_keys (
    key_id         UUID PRIMARY KEY,
    key_hash       TEXT NOT NULL UNIQUE,        -- SHA-256(key)，明文仅签发时展示一次
    tenant_id      UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    principal_type TEXT NOT NULL DEFAULT 'SERVICE' CHECK (principal_type IN ('SERVICE','AI')),
    principal_id   TEXT NOT NULL,               -- 如 agent-hub
    scopes         TEXT[] NOT NULL DEFAULT '{}',-- readonly / write:event / write:evidence / write:registry / write:trace / admin
    expires_at     TIMESTAMPTZ,
    status         TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','REVOKED'))
    -- + 审计字段
);
CREATE INDEX idx_api_keys_tenant ON platform.api_keys(tenant_id, principal_type, principal_id);

-- 系统注册（按租户的源系统/消费方连接配置）
CREATE TABLE platform.systems (
    system_id   UUID PRIMARY KEY,
    tenant_id   UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    name        TEXT NOT NULL,                  -- erp / mes / plm / agent-hub / ebms
    type        TEXT NOT NULL,                  -- SOURCE / CONSUMER / BOTH
    endpoint    TEXT,
    adapter_mode TEXT NOT NULL DEFAULT 'mock' CHECK (adapter_mode IN ('mock','real')),
    auth_config JSONB NOT NULL DEFAULT '{}',    -- 含 secret_ref（密钥引用，不含明文）
    status      TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','DISABLED'))
    -- + 审计字段
);
CREATE UNIQUE INDEX uq_systems_name ON platform.systems(tenant_id, name);

-- 能力注册（Agent 中枢能力的存储，按租户）
CREATE TABLE platform.capabilities (
    capability_id UUID PRIMARY KEY,
    tenant_id     UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    name          TEXT NOT NULL,                -- Delivery.OrderRisk / Sales.OrderQuality / RD.ProductReadiness
    domain        TEXT NOT NULL,                -- delivery / sales / rd ...
    input_schema  JSONB NOT NULL,
    output_schema JSONB NOT NULL,
    risk_level    TEXT NOT NULL CHECK (risk_level IN ('L0','L1','L2','L3')),
    permission    TEXT NOT NULL CHECK (permission IN ('HUMAN_ONLY','READ_ONLY','AUTO_ALLOWED')),
    endpoint      TEXT,
    owner         TEXT,
    status        TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('DRAFT','ACTIVE','RETIRED'))
    -- + 审计字段
);
CREATE UNIQUE INDEX uq_capability_name ON platform.capabilities(tenant_id, name);

-- 技能（Prompt/模型版本）
CREATE TABLE platform.skills (
    skill_id      UUID PRIMARY KEY,
    tenant_id     UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    capability_id UUID NOT NULL REFERENCES platform.capabilities(capability_id),
    prompt        TEXT NOT NULL,
    model_version TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','ACTIVE','RETIRED'))
    -- + 审计字段
);
CREATE INDEX idx_skills_capability ON platform.skills(tenant_id, capability_id, status);

-- 审计日志（仅追加，按月分区；控制平面表，不启用 RLS，API 层按 tenant_id 过滤；
-- tenant_id 可空：NULL = 平台级事件，如租户生命周期操作）
CREATE TABLE platform.audit_logs (
    audit_id     BIGINT GENERATED ALWAYS AS IDENTITY,
    occurred_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    tenant_id    UUID,
    actor_type   TEXT NOT NULL CHECK (actor_type IN ('HUMAN','SERVICE','AI')),
    actor_id     TEXT NOT NULL,
    request_id   UUID,
    action       TEXT NOT NULL,                 -- OBJECT_UPSERT / EVENT_BATCH_IN / EVIDENCE_WRITE / GUARD_DENIED / TENANT_CREATED / ...
    resource_type TEXT NOT NULL,
    resource_id  TEXT,
    detail       JSONB NOT NULL DEFAULT '{}',   -- 含 before/after
    PRIMARY KEY (audit_id, occurred_at)
) PARTITION BY RANGE (occurred_at);
CREATE INDEX idx_audit_tenant   ON platform.audit_logs(tenant_id, occurred_at);
CREATE INDEX idx_audit_actor    ON platform.audit_logs(actor_type, actor_id, occurred_at);
CREATE INDEX idx_audit_resource ON platform.audit_logs(resource_type, resource_id, occurred_at);
CREATE INDEX idx_audit_action   ON platform.audit_logs(action, occurred_at);
```

### A.2 master —— 统一对象注册与主数据

```sql
CREATE SCHEMA master;

-- 业务对象注册元表（全局锚点）
CREATE TABLE master.business_objects (
    object_id     UUID PRIMARY KEY,
    tenant_id     UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    object_type   TEXT NOT NULL,                -- ORDER / CUSTOMER / PRODUCT / MATERIAL / BOM / SUPPLIER / PO / PROJECT ...
    owner_domain  TEXT NOT NULL,                -- sales / delivery / rd ...
    source_system TEXT NOT NULL,                -- erp / mes / plm
    source_id     TEXT NOT NULL,
    revision      BIGINT NOT NULL DEFAULT 1,    -- 乐观锁版本
    status        TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','SUSPENDED','MERGED')),
    merged_into   UUID REFERENCES master.business_objects(object_id),
    attributes    JSONB NOT NULL DEFAULT '{}'
    -- + 审计字段
);
CREATE UNIQUE INDEX uq_bo_natural_key ON master.business_objects(tenant_id, source_system, object_type, source_id);
CREATE INDEX idx_bo_type    ON master.business_objects(tenant_id, object_type, status);
CREATE INDEX idx_bo_domain  ON master.business_objects(tenant_id, owner_domain);
CREATE INDEX idx_bo_attrs   ON master.business_objects USING GIN (attributes);

-- 客户
CREATE TABLE master.customers (
    customer_id UUID PRIMARY KEY REFERENCES master.business_objects(object_id),
    tenant_id   UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    code        TEXT NOT NULL,
    name        TEXT NOT NULL,
    level       TEXT,                           -- VIP / NORMAL ...
    attributes  JSONB NOT NULL DEFAULT '{}'
    -- + 审计字段
);
CREATE UNIQUE INDEX uq_customer_code ON master.customers(tenant_id, code);

-- 产品 / 物料 / 供应商
CREATE TABLE master.products (
    product_id UUID PRIMARY KEY REFERENCES master.business_objects(object_id),
    tenant_id  UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    code       TEXT NOT NULL,
    name       TEXT NOT NULL,
    category   TEXT,
    status     TEXT NOT NULL DEFAULT 'ACTIVE'
    -- + 审计字段
);
CREATE UNIQUE INDEX uq_product_code ON master.products(tenant_id, code);

CREATE TABLE master.materials (
    material_id UUID PRIMARY KEY REFERENCES master.business_objects(object_id),
    tenant_id   UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    code        TEXT NOT NULL,
    name        TEXT NOT NULL,
    unit        TEXT,
    attributes  JSONB NOT NULL DEFAULT '{}'
    -- + 审计字段
);
CREATE UNIQUE INDEX uq_material_code ON master.materials(tenant_id, code);

CREATE TABLE master.suppliers (
    supplier_id UUID PRIMARY KEY REFERENCES master.business_objects(object_id),
    tenant_id   UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    code        TEXT NOT NULL,
    name        TEXT NOT NULL,
    attributes  JSONB NOT NULL DEFAULT '{}'
    -- + 审计字段
);
CREATE UNIQUE INDEX uq_supplier_code ON master.suppliers(tenant_id, code);

-- BOM 及明细
CREATE TABLE master.boms (
    bom_id    UUID PRIMARY KEY REFERENCES master.business_objects(object_id),
    tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    product_id UUID NOT NULL REFERENCES master.products(product_id),
    version   TEXT NOT NULL,
    status    TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('DRAFT','ACTIVE','RETIRED'))
    -- + 审计字段
);
CREATE UNIQUE INDEX uq_bom_product_version ON master.boms(tenant_id, product_id, version, status);

CREATE TABLE master.bom_items (
    item_id     UUID PRIMARY KEY,
    tenant_id   UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    bom_id      UUID NOT NULL REFERENCES master.boms(bom_id),
    material_id UUID NOT NULL REFERENCES master.materials(material_id),
    quantity    NUMERIC(18,4) NOT NULL CHECK (quantity > 0),
    position    INT
    -- + 审计字段
);
CREATE INDEX idx_bom_items_bom ON master.bom_items(tenant_id, bom_id);
```

### A.3 event —— 事件流水与 Outbox

```sql
CREATE SCHEMA event;

-- 事件表
CREATE TABLE event.events (
    event_id        UUID PRIMARY KEY,           -- 适配器回流：UUIDv5(tenant_ns, ...) 确定性生成（幂等），全局唯一
    tenant_id       UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    event_type      TEXT NOT NULL,              -- order.created / inventory.changed / purchase.delayed / capability.result.* / quality.*
    object_id       UUID NOT NULL REFERENCES master.business_objects(object_id),
    source_system   TEXT NOT NULL,
    occurred_at     TIMESTAMPTZ NOT NULL,
    actor_type      TEXT CHECK (actor_type IN ('HUMAN','SERVICE','AI')),
    actor_id        TEXT,
    result_type     TEXT,                       -- 能力结果事件专用：ORDER_RISK / ORDER_QUALITY / PRODUCT_READINESS
    risk_level      TEXT CHECK (risk_level IN ('P0','P1','P2','P3') OR risk_level IS NULL),
    score           NUMERIC(10,4),
    data            JSONB NOT NULL DEFAULT '{}',
    idempotency_key TEXT                        -- 批次/接口幂等键
    -- + 审计字段
);
CREATE INDEX idx_events_object   ON event.events(tenant_id, object_id, occurred_at DESC);
CREATE INDEX idx_events_type     ON event.events(tenant_id, event_type, occurred_at DESC);
CREATE INDEX idx_events_risk     ON event.events(tenant_id, risk_level, occurred_at DESC) WHERE risk_level IS NOT NULL;
CREATE INDEX idx_events_data     ON event.events USING GIN (data);
CREATE UNIQUE INDEX uq_events_idem ON event.events(tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL;

-- 事务性发件箱
CREATE TABLE event.outbox (
    outbox_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id     UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    aggregate_type TEXT NOT NULL,               -- EVENT / EVIDENCE / OBJECT ...
    aggregate_id  UUID NOT NULL,
    event_type    TEXT NOT NULL,
    payload       JSONB NOT NULL,
    status        TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','PUBLISHED','FAILED')),
    retry_count   INT NOT NULL DEFAULT 0,
    available_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at  TIMESTAMPTZ
    -- + 审计字段
);
CREATE INDEX idx_outbox_dispatch ON event.outbox(tenant_id, status, available_at) WHERE status = 'PENDING';
```

### A.4 evidence —— 证据快照与证据链

```sql
CREATE SCHEMA evidence;

-- 证据记录
CREATE TABLE evidence.records (
    evidence_id     UUID PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    source_system   TEXT NOT NULL,
    source_record_id TEXT NOT NULL,             -- 指回源系统原始记录（追溯链终点）
    object_id       UUID NOT NULL REFERENCES master.business_objects(object_id),
    event_id        UUID REFERENCES event.events(event_id),
    content_type    TEXT NOT NULL DEFAULT 'application/json',
    checksum        TEXT NOT NULL,              -- SHA-256(canonical_json(snapshot))
    checksum_algo   TEXT NOT NULL DEFAULT 'SHA256',
    snapshot        JSONB NOT NULL,
    captured_at     TIMESTAMPTZ NOT NULL
    -- + 审计字段
);
CREATE INDEX idx_evidence_object ON evidence.records(tenant_id, object_id, captured_at DESC);
CREATE INDEX idx_evidence_event  ON evidence.records(tenant_id, event_id);
CREATE INDEX idx_evidence_source ON evidence.records(tenant_id, source_system, source_record_id);

-- 证据链关联（通用逆向追溯：ref_type+ref_id → evidence）
CREATE TABLE evidence.links (
    link_id     UUID PRIMARY KEY,
    tenant_id   UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    evidence_id UUID NOT NULL REFERENCES evidence.records(evidence_id),
    ref_type    TEXT NOT NULL CHECK (ref_type IN ('CASE','DECISION','ACTION','RESULT','EVENT','TRACE')),
    ref_id      UUID NOT NULL
    -- + 审计字段
);
CREATE INDEX idx_links_ref      ON evidence.links(tenant_id, ref_type, ref_id);
CREATE INDEX idx_links_evidence ON evidence.links(tenant_id, evidence_id);
```

### A.5 decision —— 决策案例与记录

```sql
CREATE SCHEMA decision;

-- 决策案例
CREATE TABLE decision.cases (
    case_id     UUID PRIMARY KEY,
    tenant_id   UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    case_no     TEXT,                           -- 展示编号，可空（租户内自动生成）
    question    TEXT NOT NULL,
    context     JSONB NOT NULL DEFAULT '{}',    -- 影响说明、来源事件等
    options     JSONB NOT NULL DEFAULT '[]',    -- 可选操作选项
    risk_level  TEXT CHECK (risk_level IN ('P0','P1','P2','P3')),
    source_type TEXT,                           -- capability.result / human / rule
    source_id   TEXT,
    status      TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','DECIDED','CANCELLED')),
    decided_at  TIMESTAMPTZ
    -- + 审计字段
);
CREATE UNIQUE INDEX uq_case_no ON decision.cases(tenant_id, case_no) WHERE case_no IS NOT NULL;
CREATE INDEX idx_cases_status ON decision.cases(tenant_id, status, risk_level, created_at DESC);

-- 决策记录
CREATE TABLE decision.records (
    decision_id   UUID PRIMARY KEY,
    tenant_id     UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    case_id       UUID NOT NULL REFERENCES decision.cases(case_id),
    chosen_option TEXT NOT NULL,                -- 批准/拒绝/修改/补充证据
    decision_type TEXT NOT NULL CHECK (decision_type IN ('HUMAN','AI_SUGGESTED')),
    decided_by    TEXT NOT NULL,
    decision_time TIMESTAMPTZ NOT NULL DEFAULT now(),
    comment       TEXT
    -- + 审计字段
);
CREATE INDEX idx_decision_records_case ON decision.records(tenant_id, case_id, decision_time);
```

### A.6 action —— 行动任务状态机

```sql
CREATE SCHEMA action;

CREATE TABLE action.actions (
    action_id       UUID PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    case_id         UUID REFERENCES decision.cases(case_id),
    title           TEXT NOT NULL,
    description     TEXT,
    action_type     TEXT NOT NULL,              -- expedite_purchase / notify_customer / adjust_plan ...
    status          TEXT NOT NULL DEFAULT 'PROPOSED' CHECK (status IN
                    ('PROPOSED','ASSIGNED','ACCEPTED','APPROVED','EXECUTING','COMPLETED','VERIFIED','CANCELLED','REJECTED')),
    owner           TEXT,                       -- 责任人
    owner_role      TEXT,
    due_date        TIMESTAMPTZ,
    completion_time TIMESTAMPTZ,
    verified_at     TIMESTAMPTZ,
    verified_by     TEXT
    -- + 审计字段
);
CREATE INDEX idx_actions_status ON action.actions(tenant_id, status, due_date);
CREATE INDEX idx_actions_case   ON action.actions(tenant_id, case_id);
CREATE INDEX idx_actions_owner  ON action.actions(tenant_id, owner, status);
```

### A.7 memory —— 学习记忆

```sql
CREATE SCHEMA memory;

-- 记忆（候选 → 评审 → Approved/Rejected；评审逻辑 W6 由中枢接管）
CREATE TABLE memory.memories (
    memory_id    UUID PRIMARY KEY,
    tenant_id    UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    capability_id UUID REFERENCES platform.capabilities(capability_id),
    source_type  TEXT NOT NULL,                 -- decision / action / trace
    source_id    UUID NOT NULL,
    content      JSONB NOT NULL,                -- 结构化经验/偏好
    status       TEXT NOT NULL DEFAULT 'CANDIDATE' CHECK (status IN ('CANDIDATE','APPROVED','REJECTED')),
    reviewed_by  TEXT,
    reviewed_at  TIMESTAMPTZ,
    review_comment TEXT
    -- + 审计字段
);
CREATE INDEX idx_memories_status ON memory.memories(tenant_id, status, created_at DESC);
CREATE INDEX idx_memories_capability ON memory.memories(tenant_id, capability_id, status);
```

### A.8 management —— 经营目标与 KPI

```sql
CREATE SCHEMA management;

-- 经营目标
CREATE TABLE management.objectives (
    objective_id  UUID PRIMARY KEY,
    tenant_id     UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    title         TEXT NOT NULL,
    metric_type   TEXT NOT NULL,                -- revenue / on_time_delivery ...
    target_value  NUMERIC(18,4) NOT NULL,
    current_value NUMERIC(18,4),
    period        TEXT NOT NULL,                -- 2026-Q4
    owner         TEXT,
    due_date      TIMESTAMPTZ,
    status        TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','ACHIEVED','MISSED','CANCELLED'))
    -- + 审计字段
);
CREATE INDEX idx_objectives_tenant ON management.objectives(tenant_id, period, status);

-- KPI 定义与数值（EBMS 报表预聚合来源）
CREATE TABLE management.kpi_definitions (
    kpi_id  UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    code    TEXT NOT NULL,
    name    TEXT NOT NULL,
    formula TEXT,                               -- 口径说明
    unit    TEXT,
    refresh_cycle TEXT NOT NULL DEFAULT 'DAILY'
    -- + 审计字段
);
CREATE UNIQUE INDEX uq_kpi_code ON management.kpi_definitions(tenant_id, code);

CREATE TABLE management.kpi_values (
    value_id    UUID PRIMARY KEY,
    tenant_id   UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    kpi_id      UUID NOT NULL REFERENCES management.kpi_definitions(kpi_id),
    period      TEXT NOT NULL,
    value       NUMERIC(18,4) NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    source      TEXT
    -- + 审计字段
);
CREATE UNIQUE INDEX uq_kpi_value ON management.kpi_values(tenant_id, kpi_id, period);

-- 硬性约束（与 Guard 策略联动）
CREATE TABLE management.constraints (
    constraint_id UUID PRIMARY KEY,
    tenant_id     UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    name          TEXT NOT NULL,
    rule_type     TEXT NOT NULL,                -- guard_policy / data_quality / business_rule
    config        JSONB NOT NULL,
    severity      TEXT NOT NULL CHECK (severity IN ('BLOCK','WARN','INFO')),
    enabled       BOOLEAN NOT NULL DEFAULT TRUE
    -- + 审计字段
);
```

### A.9 trace —— Agent 执行日志

```sql
CREATE SCHEMA trace;

-- 执行轨迹（高频写入，独立保留期与归档策略）
CREATE TABLE trace.traces (
    trace_id         UUID PRIMARY KEY,
    tenant_id        UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    agent_id         TEXT NOT NULL,
    task_id          TEXT,
    capability_id    UUID REFERENCES platform.capabilities(capability_id),
    started_at       TIMESTAMPTZ NOT NULL,
    finished_at      TIMESTAMPTZ,
    status           TEXT NOT NULL DEFAULT 'RUNNING' CHECK (status IN ('RUNNING','SUCCEEDED','FAILED','TIMEOUT','ABORTED')),
    input_context    JSONB,
    llm_prompt       TEXT,
    llm_response     TEXT,
    output_structured JSONB,
    token_usage      JSONB,                     -- {prompt, completion, total}
    evidence_refs    UUID[] NOT NULL DEFAULT '{}',
    error            JSONB
    -- + 审计字段
);
CREATE INDEX idx_traces_agent ON trace.traces(tenant_id, agent_id, started_at DESC);
CREATE INDEX idx_traces_task  ON trace.traces(tenant_id, task_id);
CREATE INDEX idx_traces_capability ON trace.traces(tenant_id, capability_id, started_at DESC);

-- 工具调用明细（三层留痕之执行轨迹层）
CREATE TABLE trace.tool_calls (
    call_id    UUID PRIMARY KEY,
    tenant_id  UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    trace_id   UUID NOT NULL REFERENCES trace.traces(trace_id),
    seq        INT NOT NULL,
    tool_name  TEXT NOT NULL,
    input      JSONB,
    output     JSONB,
    status_code INT,
    error      JSONB,
    latency_ms INT,
    called_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_tool_calls_trace ON trace.tool_calls(tenant_id, trace_id, seq);
```

### A.10 sales —— 销售域快照

```sql
CREATE SCHEMA sales;

-- 订单快照（源：ERP，W2 起）
CREATE TABLE sales.orders (
    order_id     UUID PRIMARY KEY REFERENCES master.business_objects(object_id),
    tenant_id    UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    order_no     TEXT NOT NULL,
    customer_id  UUID REFERENCES master.customers(customer_id),
    amount       NUMERIC(18,4),
    currency     TEXT NOT NULL DEFAULT 'CNY',
    status       TEXT NOT NULL,                 -- 新建/已确认/已发货/已关闭/取消
    order_date   TIMESTAMPTZ,
    delivery_date TIMESTAMPTZ,
    snapshot_at  TIMESTAMPTZ NOT NULL,
    attributes   JSONB NOT NULL DEFAULT '{}'
    -- + 审计字段
);
CREATE UNIQUE INDEX uq_sales_order_no ON sales.orders(tenant_id, order_no);
CREATE INDEX idx_sales_orders_customer ON sales.orders(tenant_id, customer_id, snapshot_at DESC);
CREATE INDEX idx_sales_orders_status  ON sales.orders(tenant_id, status, delivery_date);

-- 订单行
CREATE TABLE sales.order_lines (
    line_id     UUID PRIMARY KEY,
    tenant_id   UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    order_id    UUID NOT NULL REFERENCES sales.orders(order_id),
    product_id  UUID REFERENCES master.products(product_id),
    material_id UUID REFERENCES master.materials(material_id),
    quantity    NUMERIC(18,4) NOT NULL,
    unit_price  NUMERIC(18,4),
    amount      NUMERIC(18,4)
    -- + 审计字段
);
CREATE INDEX idx_order_lines_order ON sales.order_lines(tenant_id, order_id);
```

### A.11 delivery —— 交付域快照

```sql
CREATE SCHEMA delivery;

-- 库存快照
CREATE TABLE delivery.inventory (
    inv_id            UUID PRIMARY KEY REFERENCES master.business_objects(object_id),
    tenant_id         UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    material_id       UUID NOT NULL REFERENCES master.materials(material_id),
    warehouse         TEXT,
    quantity_available NUMERIC(18,4) NOT NULL DEFAULT 0,
    quantity_reserved  NUMERIC(18,4) NOT NULL DEFAULT 0,
    snapshot_at       TIMESTAMPTZ NOT NULL,
    attributes        JSONB NOT NULL DEFAULT '{}'
    -- + 审计字段
);
CREATE INDEX idx_inventory_material ON delivery.inventory(tenant_id, material_id, snapshot_at DESC);

-- 采购单快照
CREATE TABLE delivery.purchase_orders (
    po_id         UUID PRIMARY KEY REFERENCES master.business_objects(object_id),
    tenant_id     UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    po_no         TEXT NOT NULL,
    supplier_id   UUID REFERENCES master.suppliers(supplier_id),
    material_id   UUID REFERENCES master.materials(material_id),
    quantity      NUMERIC(18,4) NOT NULL,
    expected_date TIMESTAMPTZ,
    status        TEXT NOT NULL,                -- 待确认/已下单/在途/到货/延迟
    snapshot_at   TIMESTAMPTZ NOT NULL,
    attributes    JSONB NOT NULL DEFAULT '{}'
    -- + 审计字段
);
CREATE UNIQUE INDEX uq_delivery_po_no ON delivery.purchase_orders(tenant_id, po_no);
CREATE INDEX idx_po_material_status ON delivery.purchase_orders(tenant_id, material_id, status, expected_date);

-- 供应商交期（OrderRisk 能力关键输入）
CREATE TABLE delivery.supplier_lead_times (
    id           UUID PRIMARY KEY,
    tenant_id    UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    supplier_id  UUID NOT NULL REFERENCES master.suppliers(supplier_id),
    material_id  UUID REFERENCES master.materials(material_id),
    lead_time_days INT NOT NULL CHECK (lead_time_days >= 0),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
    -- + 审计字段
);
CREATE UNIQUE INDEX uq_lead_time ON delivery.supplier_lead_times(tenant_id, supplier_id, material_id);

-- 产能快照（W3 按能力需要启用）
CREATE TABLE delivery.capacity (
    id           UUID PRIMARY KEY,
    tenant_id    UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    product_line TEXT NOT NULL,
    period       TEXT NOT NULL,
    capacity_qty NUMERIC(18,4) NOT NULL,
    snapshot_at  TIMESTAMPTZ NOT NULL
    -- + 审计字段
);
CREATE UNIQUE INDEX uq_capacity ON delivery.capacity(tenant_id, product_line, period, snapshot_at);
```

### A.12 rd —— 研发域快照

```sql
CREATE SCHEMA rd;

-- 研发项目
CREATE TABLE rd.projects (
    project_id      UUID PRIMARY KEY REFERENCES master.business_objects(object_id),
    tenant_id       UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    project_no      TEXT NOT NULL,
    product_id      UUID REFERENCES master.products(product_id),
    status          TEXT NOT NULL,              -- 规划/设计中/验证中/已量产/暂停
    stage           TEXT,
    readiness_level TEXT,                       -- 未达产/达产评估中/已达产
    snapshot_at     TIMESTAMPTZ NOT NULL,
    attributes      JSONB NOT NULL DEFAULT '{}'
    -- + 审计字段
);
CREATE UNIQUE INDEX uq_rd_project_no ON rd.projects(tenant_id, project_no);

-- 项目里程碑
CREATE TABLE rd.milestones (
    milestone_id UUID PRIMARY KEY,
    tenant_id    UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    project_id   UUID NOT NULL REFERENCES rd.projects(project_id),
    name         TEXT NOT NULL,
    due_date     TIMESTAMPTZ,
    actual_date  TIMESTAMPTZ,
    status       TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','IN_PROGRESS','DONE','OVERDUE'))
    -- + 审计字段
);
CREATE INDEX idx_milestones_project ON rd.milestones(tenant_id, project_id, due_date);
```

### A.13 support —— 支持域快照

```sql
CREATE SCHEMA support;

-- 工单
CREATE TABLE support.tickets (
    ticket_id   UUID PRIMARY KEY REFERENCES master.business_objects(object_id),
    tenant_id   UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    ticket_no   TEXT NOT NULL,
    customer_id UUID REFERENCES master.customers(customer_id),
    type        TEXT,
    severity    TEXT CHECK (severity IN ('P0','P1','P2','P3')),
    status      TEXT NOT NULL,
    snapshot_at TIMESTAMPTZ NOT NULL,
    attributes  JSONB NOT NULL DEFAULT '{}'
    -- + 审计字段
);
CREATE UNIQUE INDEX uq_support_ticket_no ON support.tickets(tenant_id, ticket_no);
```

### A.14 quality —— 品控域快照

```sql
CREATE SCHEMA quality;

-- 质检记录
CREATE TABLE quality.inspections (
    inspection_id UUID PRIMARY KEY REFERENCES master.business_objects(object_id),
    tenant_id     UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    inspection_no TEXT NOT NULL,
    target_type   TEXT NOT NULL,                -- MATERIAL / PRODUCT / PO ...
    target_id     UUID NOT NULL,
    result        TEXT NOT NULL CHECK (result IN ('PASS','FAIL','CONDITIONAL')),
    defect_qty    NUMERIC(18,4),
    inspected_at  TIMESTAMPTZ,
    snapshot_at   TIMESTAMPTZ NOT NULL,
    attributes    JSONB NOT NULL DEFAULT '{}'
    -- + 审计字段
);
CREATE UNIQUE INDEX uq_inspection_no ON quality.inspections(tenant_id, inspection_no);

-- 质量异常
CREATE TABLE quality.exceptions (
    exception_id UUID PRIMARY KEY REFERENCES master.business_objects(object_id),
    tenant_id    UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    source       TEXT NOT NULL,
    severity     TEXT CHECK (severity IN ('P0','P1','P2','P3')),
    status       TEXT NOT NULL DEFAULT 'OPEN',
    description  TEXT NOT NULL,
    snapshot_at  TIMESTAMPTZ NOT NULL
    -- + 审计字段
);
CREATE INDEX idx_quality_exceptions ON quality.exceptions(tenant_id, status, severity);
```

### A.15 finance —— 财务域快照

```sql
CREATE SCHEMA finance;

-- 应收
CREATE TABLE finance.receivables (
    ar_id       UUID PRIMARY KEY REFERENCES master.business_objects(object_id),
    tenant_id   UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    customer_id UUID REFERENCES master.customers(customer_id),
    amount      NUMERIC(18,4) NOT NULL,
    due_date    TIMESTAMPTZ,
    overdue_days INT NOT NULL DEFAULT 0,
    status      TEXT NOT NULL,
    snapshot_at TIMESTAMPTZ NOT NULL
    -- + 审计字段
);
CREATE INDEX idx_ar_customer ON finance.receivables(tenant_id, customer_id, due_date);

-- 收入快照（预聚合）
CREATE TABLE finance.revenue_snapshots (
    id           UUID PRIMARY KEY,
    tenant_id    UUID NOT NULL REFERENCES platform.tenants(tenant_id),   -- + RLS
    period       TEXT NOT NULL,
    revenue      NUMERIC(18,4) NOT NULL,
    cost         NUMERIC(18,4),
    gross_margin NUMERIC(10,4),
    snapshot_at  TIMESTAMPTZ NOT NULL
    -- + 审计字段
);
CREATE UNIQUE INDEX uq_revenue_period ON finance.revenue_snapshots(tenant_id, period, snapshot_at);
```

## 附录 B：全量 API 契约

### B.0 通用约定与错误码

**鉴权**

| 方式 | 头 | 适用 |
|---|---|---|
| JWT | `Authorization: Bearer <access_token>` | 用户（EBMS、运维）；claims：`{sub, tenant_id, roles, principal_type, is_platform_admin}` |
| API Key | `X-API-Key: <key>` | 服务主体（Agent 中枢、Worker）；密钥绑定租户 |

**租户上下文**：除租户管理分组（B.14）外，所有接口的范围由认证凭据中的租户决定，请求体不传 tenant_id；平台运营账号经 `POST /tenants/{id}/context` 切换目标租户（平台级接口除外）。

**分页**：请求 `?limit=50&cursor=<opaque>`；响应统一包裹 `{"items": [...], "next_cursor": "..." | null}`。

**幂等**：批量写接口要求 `Idempotency-Key: <uuid>` 头；重复提交返回首次结果并附 `"deduplicated": true`。

**限流**：按租户令牌桶（3.5），超限 `429` 响应头附 `Retry-After`。

**错误响应结构**

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "occurred_at is required",
    "request_id": "0d9c4b1e-8f2a-4c1d-9e77-3a2b1c0d9e11"
  }
}
```

| HTTP | code | 场景 |
|---|---|---|
| 400 | VALIDATION_ERROR | 参数缺失/格式错误 |
| 401 | UNAUTHENTICATED | 未认证 / Token 过期 / Key 无效 |
| 403 | FORBIDDEN | 权限不足 |
| 403 | TENANT_FORBIDDEN | principal 与目标租户不匹配（跨租户访问，落审计） |
| 403 | TENANT_SUSPENDED | 租户已暂停（API 即时拒绝） |
| 403 | GUARD_POLICY_DENIED | 策略拒绝（如 AI 请求 Human-Only 操作） |
| 404 | NOT_FOUND | 资源不存在（含跨租户资源——不泄露存在性） |
| 405 | METHOD_NOT_ALLOWED | Read-Only 路由收到非 GET 请求 |
| 409 | CONFLICT | 乐观锁版本冲突 / 唯一键冲突 |
| 422 | INVALID_TRANSITION | Action 状态机非法转移 |
| 429 | RATE_LIMITED | 租户限流 |
| 503 | UPSTREAM_UNAVAILABLE | 源系统不可达（适配器同步触发时） |
| 500 | INTERNAL | 内部错误 |

### B.1 认证与密钥

**POST /api/v1/auth/login** —— 公开
```json
// 请求
{ "username": "manager1", "password": "...", "tenant_slug": "default" }   // tenant_slug 可选（单租户部署可省；多租户必填或经子域名解析）
// 200 响应
{ "access_token": "...", "refresh_token": "...", "expires_in": 7200,
  "tenant": { "tenant_id": "uuid", "slug": "default", "name": "默认租户", "status": "ACTIVE" },
  "user": { "user_id": "uuid", "username": "manager1", "roles": ["MANAGER"], "is_platform_admin": false } }
// 401：UNAUTHENTICATED；403：TENANT_SUSPENDED
```

**POST /api/v1/auth/refresh** —— 公开
```json
// 请求
{ "refresh_token": "..." }
// 200 响应
{ "access_token": "...", "expires_in": 7200 }
```

**GET /api/v1/auth/me** —— JWT
```json
// 200 响应
{ "user_id": "uuid", "username": "manager1", "org_id": "uuid", "tenant_id": "uuid", "is_platform_admin": false, "roles": ["MANAGER"], "permissions": ["evidence:read", "decision:decide", "..."] }
```

### B.2 对象注册（registry）

**POST /api/v1/objects** —— API Key（write:registry）
```json
// 请求（首次注册创建，重复注册走 upsert 语义）
{
  "object_type": "ORDER",
  "owner_domain": "sales",
  "source_system": "erp",
  "source_id": "SO-2026-00123",
  "idempotency": { "expected_revision": null },
  "attributes": { "amount": 120000.00 }
}
// 201 响应
{ "object_id": "uuid", "revision": 1, "status": "ACTIVE", "created_at": "2026-09-14T02:11:33Z" }
// 409 CONFLICT：expected_revision 与当前不符（响应体附 current_revision）
```

**GET /api/v1/objects/{object_id}** —— JWT / API Key（readonly）
```json
// 200 响应
{ "object_id": "uuid", "object_type": "ORDER", "owner_domain": "sales", "source_system": "erp", "source_id": "SO-2026-00123", "revision": 7, "status": "ACTIVE", "attributes": {}, "created_at": "...", "updated_at": "..." }
```

**GET /api/v1/objects?object_type=ORDER&source_system=erp&source_id=SO-2026-00123** —— JWT / readonly（组合键查询）
```json
// 200 响应
{ "items": [ { "object_id": "uuid", "revision": 7, "...": "..." } ], "next_cursor": null }
```

**GET /api/v1/objects/{object_id}/history** —— JWT（ADMIN/MANAGER）
```json
// 200 响应（revision 变更轨迹，来自审计日志聚合）
{ "object_id": "uuid", "revisions": [ { "revision": 7, "action": "OBJECT_UPSERT", "actor_id": "adapter:erp", "occurred_at": "..." } ] }
```

### B.3 事件

**POST /api/v1/events/batch** —— API Key（write:event）；Header `Idempotency-Key`
```json
// 请求（能力结果回流同此接口，event_type=capability.result.*）
{
  "events": [
    {
      "event_id": "uuid-v5",
      "event_type": "capability.result.order_risk",
      "object_id": "uuid",
      "source_system": "agent-hub",
      "occurred_at": "2026-09-28T08:00:00Z",
      "actor_type": "AI",
      "actor_id": "agent:delivery-order-risk",
      "result_type": "ORDER_RISK",
      "risk_level": "P1",
      "score": 0.86,
      "data": { "reason": "物料X缺口1000", "recommendation": "加急采购/替代料" }
    }
  ]
}
// 200 响应
{ "accepted": 1, "duplicated": 0, "rejected": 0, "deduplicated": false }
```

**GET /api/v1/events?object_id=&event_type=&risk_level=&since=&until=&limit=** —— JWT / readonly
```json
// 200 响应
{ "items": [ { "event_id": "uuid", "event_type": "order.created", "object_id": "uuid", "occurred_at": "...", "risk_level": null, "data": {} } ], "next_cursor": "b64..." }
```

**GET /api/v1/events/{event_id}** —— JWT / readonly
```json
// 200 响应：完整事件对象；404：NOT_FOUND
```

### B.4 证据

**POST /api/v1/evidence** —— API Key（write:evidence）
```json
// 请求（checksum 服务端计算，客户端无需传）
{
  "source_system": "erp",
  "source_record_id": "SO-2026-00123#v7",
  "object_id": "uuid",
  "event_id": "uuid",                         // 可选
  "snapshot": { "order_no": "SO-2026-00123", "amount": 120000, "delivery_date": "2026-10-15" },
  "captured_at": "2026-09-28T08:00:00Z",
  "links": [ { "ref_type": "CASE", "ref_id": "uuid" } ]   // 可选：写入同时建链
}
// 201 响应
{ "evidence_id": "uuid", "checksum": "sha256:9f86d081...", "captured_at": "..." }
```

**GET /api/v1/evidence/{evidence_id}** —— JWT / readonly（EBMS 证据钻取复用此接口）
```json
// 200 响应
{ "evidence_id": "uuid", "source_system": "erp", "source_record_id": "SO-2026-00123#v7", "object_id": "uuid", "checksum": "sha256:...", "snapshot": {}, "captured_at": "..." }
```

**GET /api/v1/evidence/{evidence_id}/verify** —— JWT
```json
// 200 响应（服务端重算 canonical JSON 的 SHA-256 比对；失败写审计并报警）
{ "evidence_id": "uuid", "valid": true, "verified_at": "..." }
```

**GET /api/v1/evidence?ref_type=CASE&ref_id=&object_id=&limit=** —— JWT / readonly（证据链逆向追溯）
```json
// 200 响应
{ "items": [ { "evidence_id": "uuid", "source_system": "erp", "captured_at": "...", "checksum": "sha256:..." } ], "next_cursor": null }
```

### B.5 决策与行动

**POST /api/v1/decisions/cases** —— API Key（Agent 中枢）/ JWT
```json
// 请求
{ "question": "订单 SO-2026-00123 存在缺料风险，是否加急采购物料X？", "context": { "order_amount": 120000, "material_gap": 1000, "source_event_id": "uuid" }, "options": [ { "key": "EXPEDITE", "label": "加急采购" }, { "key": "SUBSTITUTE", "label": "启用替代料" }, { "key": "REJECT", "label": "拒绝建议" } ], "risk_level": "P1", "source_type": "capability.result", "source_id": "uuid", "evidence_ids": ["uuid"] }
// 201 响应
{ "case_id": "uuid", "case_no": "DC-20260928-007", "status": "OPEN", "created_at": "..." }
```

**GET /api/v1/decisions/cases?status=OPEN&risk_level=&limit=** —— JWT
```json
// 200 响应
{ "items": [ { "case_id": "uuid", "case_no": "DC-20260928-007", "question": "...", "risk_level": "P1", "status": "OPEN", "created_at": "..." } ], "next_cursor": null }
```

**GET /api/v1/decisions/cases/{case_id}** —— JWT（含关联证据引用）
```json
// 200 响应
{ "case_id": "uuid", "question": "...", "context": {}, "options": [], "risk_level": "P1", "status": "OPEN", "evidence_refs": [ { "evidence_id": "uuid", "checksum": "sha256:...", "source_system": "erp" } ], "decisions": [] }
```

**POST /api/v1/decisions/cases/{case_id}/records** —— JWT（**Human-Only**：AI principal 一律 403 GUARD_POLICY_DENIED 并落审计）
```json
// 请求
{ "chosen_option": "EXPEDITE", "decision_type": "HUMAN", "comment": "同意，优先保交付" }
// 201 响应
{ "decision_id": "uuid", "case_id": "uuid", "decision_time": "...", "case_status": "DECIDED" }
```

**POST /api/v1/actions** —— API Key / JWT
```json
// 请求
{ "case_id": "uuid", "title": "加急采购物料X 1000 件", "action_type": "expedite_purchase", "owner": "procurement_zhang", "owner_role": "PROCUREMENT", "due_date": "2026-10-01T00:00:00Z" }
// 201 响应
{ "action_id": "uuid", "status": "PROPOSED", "created_at": "..." }
```

**GET /api/v1/actions?status=&owner=&case_id=&limit=** —— JWT
```json
// 200 响应
{ "items": [ { "action_id": "uuid", "title": "...", "status": "APPROVED", "owner": "procurement_zhang", "due_date": "..." } ], "next_cursor": null }
```

**GET /api/v1/actions/{action_id}** —— JWT：完整行动对象（404：NOT_FOUND）。

**PATCH /api/v1/actions/{action_id}/status** —— JWT；`APPROVED→EXECUTING` 与 `COMPLETED→VERIFIED` 转移 **Human-Only**
```json
// 请求
{ "from_status": "APPROVED", "to_status": "EXECUTING", "comment": "已向供应商下单" }
// 200 响应
{ "action_id": "uuid", "status": "EXECUTING", "updated_at": "..." }
// 422 INVALID_TRANSITION：非法转移；409 CONFLICT：from_status 与当前不符
```

### B.6 审计

**GET /api/v1/audit-logs?actor_id=&resource_type=&action=&since=&until=&limit=** —— JWT（ADMIN）
```json
// 200 响应
{ "items": [ { "audit_id": 10231, "occurred_at": "...", "actor_type": "AI", "actor_id": "agent:delivery-order-risk", "action": "GUARD_DENIED", "resource_type": "decision.records", "resource_id": "uuid", "detail": {} } ], "next_cursor": null }
```

**GET /api/v1/audit-logs/{audit_id}** —— JWT（ADMIN）：完整审计条目。（写操作由审计切面自动留痕，无写 API。）

### B.7 注册中心

**POST /api/v1/systems** —— JWT（ADMIN）/ API Key（write:registry）
```json
// 请求
{ "name": "erp", "type": "SOURCE", "endpoint": "https://erp.internal/api", "auth_config": { "kind": "apikey", "secret_ref": "ENV:ERP_API_KEY" } }
// 201 响应
{ "system_id": "uuid", "name": "erp", "status": "ACTIVE", "created_at": "..." }
```

**GET /api/v1/systems?status=** —— JWT（ADMIN）：`{ "items": [ ... ], "next_cursor": null }`。

**POST /api/v1/capabilities** —— API Key（write:registry；仅平台管理角色/服务可注册）
```json
// 请求
{ "name": "Delivery.OrderRisk", "domain": "delivery", "input_schema": { "type": "object", "properties": { "order_id": { "type": "string" } } }, "output_schema": { "type": "object", "properties": { "risk_level": { "type": "string" }, "evidence_refs": { "type": "array" } } }, "risk_level": "L2", "permission": "READ_ONLY", "endpoint": "agent-hub://capabilities/delivery-order-risk", "owner": "wuyangpeng" }
// 201 响应
{ "capability_id": "uuid", "name": "Delivery.OrderRisk", "status": "ACTIVE", "created_at": "..." }
```

**GET /api/v1/capabilities?domain=&status=** —— JWT / API Key：能力列表。
**GET /api/v1/capabilities/{capability_id}** —— JWT / API Key：能力详情（含 input/output_schema）。

**PUT /api/v1/capabilities/{capability_id}** —— API Key（write:registry）：更新端点/schema/状态（RETIRED 下线）。
```json
// 请求（局部更新语义）
{ "endpoint": "agent-hub://capabilities/delivery-order-risk/v2", "status": "ACTIVE" }
// 200 响应：更新后完整能力对象
```

**POST /api/v1/skills** —— API Key（write:registry）
```json
// 请求
{ "capability_id": "uuid", "prompt": "...", "model_version": "glm-4.7", "status": "DRAFT" }
// 201 响应
{ "skill_id": "uuid", "capability_id": "uuid", "status": "DRAFT", "created_at": "..." }
```

**GET /api/v1/skills?capability_id=&status=ACTIVE** —— JWT / API Key：技能列表。

### B.8 Agent 数据工具（全 Read-Only；API Key scope=readonly；仅 GET）

统一行为：`404 NOT_FOUND`（无数据）、`429 RATE_LIMITED`；数据全部读自 EDP 快照，源系统故障不影响本组接口可用性（适配器同步失败由运维状态接口与数据质量报警暴露）；服务端内部异常返回统一错误结构（B.0），调用方（Agent 中枢）负责超时与重试语义。响应均含 `evidence_hint`（关联 object_id/event_id）便于能力结果回溯引用证据。

**GET /api/v1/tools/orders/{order_no}**
```json
// 200 响应
{ "order_no": "SO-2026-00123", "object_id": "uuid", "customer": { "code": "C-008", "name": "某客户", "level": "VIP" }, "amount": 120000.00, "currency": "CNY", "status": "已确认", "order_date": "...", "delivery_date": "...", "lines": [ { "product_code": "P-F", "quantity": 500, "unit_price": 240.0 } ], "evidence_hint": { "object_id": "uuid" } }
```

**GET /api/v1/tools/orders?customer=&status=&limit=**：订单摘要列表（同上结构数组，不含 lines 明细）。

**GET /api/v1/tools/inventory?material_code=X-100**
```json
// 200 响应
{ "material_code": "X-100", "material_id": "uuid", "warehouses": [ { "warehouse": "WH-01", "available": 3200, "reserved": 800 } ], "total_available": 3200, "snapshot_at": "..." }
```

**GET /api/v1/tools/purchase-orders?material_code=X-100&status=在途**
```json
// 200 响应
{ "items": [ { "po_no": "PO-2026-00771", "supplier_code": "S-021", "quantity": 2000, "expected_date": "2026-10-20", "status": "在途" } ], "next_cursor": null }
```

**GET /api/v1/tools/bom?product_code=P-F**
```json
// 200 响应
{ "product_code": "P-F", "bom_version": "V3", "items": [ { "material_code": "X-100", "quantity_per": 2.5 }, { "material_code": "Y-200", "quantity_per": 1.0 } ] }
```

**GET /api/v1/tools/supplier-lead-times?supplier_code=S-021**
```json
// 200 响应
{ "supplier_code": "S-021", "lead_times": [ { "material_code": "X-100", "lead_time_days": 10 } ], "updated_at": "..." }
```

**GET /api/v1/tools/customers/{customer_code}**
```json
// 200 响应
{ "customer_code": "C-008", "name": "某客户", "level": "VIP", "attributes": {} }
```

### B.9 EBMS 查询（JWT，MANAGER+）

**GET /api/v1/ebms/reports/summary**
```json
// 200 响应（读 management 预聚合，<2s 目标的主要接口）
{ "period": "2026-09", "objectives": [ { "objective_id": "uuid", "title": "Q4 准时交付率", "target_value": 95, "current_value": 91.2, "status": "ACTIVE" } ], "kpis": [ { "code": "on_time_delivery", "name": "准时交付率", "value": 91.2, "unit": "%", "period": "2026-W36" } ], "recent_changes_summary": [ "订单 SO-2026-00123 风险升级为 P1" ] }
```

**GET /api/v1/ebms/exceptions?severity=P1&status=OPEN&limit=20**
```json
// 200 响应（读 event.events 能力结果事件的 risk_level 部分索引）
{ "items": [ { "event_id": "uuid", "result_type": "ORDER_RISK", "risk_level": "P1", "object_id": "uuid", "order_no": "SO-2026-00123", "summary": "物料X缺口1000，预计延误5天", "occurred_at": "...", "case_id": "uuid" } ], "next_cursor": null }
```

**GET /api/v1/ebms/decisions/pending**（默认最多返回 5 条，对齐"TOP DECISION"设计）
```json
// 200 响应
{ "items": [ { "case_id": "uuid", "case_no": "DC-20260928-007", "question": "...", "risk_level": "P1", "options": [ { "key": "EXPEDITE", "label": "加急采购" } ], "created_at": "..." } ], "total_pending": 7 }
```

**GET /api/v1/ebms/decisions/{case_id}**：同 B.5 `GET /decisions/cases/{case_id}`（EBMS 网关复用）。

**GET /api/v1/ebms/todos**（待办聚合：待审批决策 + 待执行/待验证行动 + 异常待确认）
```json
// 200 响应
{ "pending_decisions": [ { "case_id": "uuid", "risk_level": "P1", "created_at": "..." } ], "pending_actions": [ { "action_id": "uuid", "title": "...", "status": "EXECUTING", "due_date": "..." } ], "exceptions_to_confirm": [ { "event_id": "uuid", "risk_level": "P2" } ] }
```

**GET /api/v1/ebms/objectives**：经营目标列表（同 reports/summary.objectives 完整版）。

**GET /api/v1/ebms/evidence/{evidence_id}**：复用 B.4 `GET /evidence/{id}`（权限随 JWT 校验）。

### B.10 Trace（API Key：write:trace / readonly；查询 JWT亦可）

**POST /api/v1/traces** —— API Key（write:trace）
```json
// 请求（Agent Runtime 一次执行一条；工具调用随行写入）
{ "trace_id": "uuid", "agent_id": "agent:delivery-order-risk", "task_id": "task-0928-001", "capability_id": "uuid", "started_at": "2026-09-28T08:00:00Z", "finished_at": "2026-09-28T08:00:41Z", "status": "SUCCEEDED", "input_context": { "order_no": "SO-2026-00123" }, "output_structured": { "risk_level": "P1", "score": 0.86 }, "token_usage": { "prompt": 3120, "completion": 480, "total": 3600 }, "evidence_refs": ["uuid"], "tool_calls": [ { "seq": 1, "tool_name": "get_inventory", "input": { "material_code": "X-100" }, "output": { "total_available": 3200 }, "status_code": 200, "latency_ms": 85 } ] }
// 201 响应
{ "trace_id": "uuid", "status": "SUCCEEDED", "created_at": "..." }
```

**GET /api/v1/traces?agent_id=&task_id=&capability_id=&since=&limit=** —— JWT / readonly：轨迹摘要列表。

**GET /api/v1/traces/{trace_id}** —— JWT / readonly：完整轨迹（含 tool_calls 明细）。

### B.11 Memory

**POST /api/v1/memories** —— API Key（Agent 中枢）
```json
// 请求
{ "capability_id": "uuid", "source_type": "decision", "source_id": "uuid", "content": { "lesson": "VIP客户订单优先保交付，建议默认倾向加急" } }
// 201 响应
{ "memory_id": "uuid", "status": "CANDIDATE", "created_at": "..." }
```

**GET /api/v1/memories?status=CANDIDATE&capability_id=** —— JWT / readonly。

**PATCH /api/v1/memories/{memory_id}/review** —— JWT（Human-Only；W6 评审模块由中枢界面触发）
```json
// 请求
{ "status": "APPROVED", "comment": "经验有效，纳入知识库" }
// 200 响应
{ "memory_id": "uuid", "status": "APPROVED", "reviewed_by": "manager1", "reviewed_at": "..." }
```

### B.12 适配器运维（JWT ADMIN / 运维 Key）

**POST /api/v1/admin/adapters/{adapter_name}/sync**（手动触发；`adapter_name` ∈ erp/mes/plm）
```json
// 请求
{ "mode": "incremental", "since": "2026-09-28T00:00:00Z" }   // 或 {"mode": "full", "object_types": ["ORDER","INVENTORY"]}
// 202 响应
{ "sync_id": "uuid", "status": "RUNNING", "started_at": "..." }
```

**GET /api/v1/admin/adapters/{adapter_name}/status**
```json
// 200 响应
{ "adapter": "erp", "mode": "mock", "last_sync": { "sync_id": "uuid", "finished_at": "...", "stats": { "fetched": 1200, "registered": 1180, "duplicated": 20, "failed": 0 } }, "health": "OK" }
```

**GET /api/v1/admin/adapters**：全部适配器清单与运行状态。

### B.13 数据质量与运行状况

**GET /api/v1/admin/quality/reports?date=2026-09-28** —— JWT（ADMIN）
```json
// 200 响应
{ "date": "2026-09-28", "reconciliation": [ { "source_system": "erp", "object_type": "ORDER", "source_count": 1200, "edp_count": 1180, "deviation_pct": 1.67, "ok": true } ], "coverage": { "overall_pct": 96.8, "by_type": [ { "object_type": "ORDER", "coverage_pct": 99.1 } ] }, "orphans": { "event_orphans": 0, "evidence_orphans": 0 }, "checksum_sampling": { "sampled": 120, "failed": 0 } }
```

**GET /api/v1/admin/quality/coverage** —— JWT：覆盖率简报（Go/No-Go 周度跟踪用），结构同上 `coverage` 字段。

**GET /api/v1/health**
```json
// 200 响应（?deep=true 需 ADMIN/运维 Key）
{ "status": "OK", "db": "OK", "db_ha": { "role": "primary", "replication_lag_mb": 0.4, "replicas": 1 }, "outbox_pending": 3, "last_sync": { "erp": "2026-09-28T02:00:00Z" }, "version": "2.0.0" }
```

**GET /api/v1/admin/outbox/status** —— JWT（ADMIN）
```json
// 200 响应
{ "pending": 3, "failed": 0, "oldest_pending_at": "...", "published_last_hour": 1240 }
```

### B.14 租户管理（JWT，平台 ADMIN；租户内 ADMIN 限本租户成员/配额查询）

**POST /api/v1/tenants** —— 平台 ADMIN；开通即原子完成（租户+初始管理员+默认配额+种子数据）
```json
// 请求
{ "slug": "acme", "name": "Acme 制造", "plan": "STANDARD", "admin": { "username": "admin1", "email": "admin@acme.example", "display_name": "租户管理员" }, "quotas": { "storage_gb": 50, "events_per_month": 1000000 } }
// 201 响应
{ "tenant_id": "uuid", "slug": "acme", "name": "Acme 制造", "status": "ACTIVE", "created_at": "...", "initial_admin_user_id": "uuid" }
```

**GET /api/v1/tenants?status=&plan=&limit=** —— 平台 ADMIN
```json
// 200 响应
{ "items": [ { "tenant_id": "uuid", "slug": "acme", "name": "Acme 制造", "plan": "STANDARD", "status": "ACTIVE", "usage": { "storage_gb": 12.4, "events_this_month": 83000 }, "created_at": "..." } ], "next_cursor": null }
```

**GET /api/v1/tenants/{tenant_id}** —— 平台 ADMIN：租户详情（含配额与用量）。

**PATCH /api/v1/tenants/{tenant_id}** —— 平台 ADMIN
```json
// 请求
{ "name": "Acme 制造集团", "plan": "PREMIUM" }
// 200 响应：更新后完整租户对象
```

**POST /api/v1/tenants/{tenant_id}/suspend** / **POST /api/v1/tenants/{tenant_id}/resume** —— 平台 ADMIN
```json
// 202 响应
{ "tenant_id": "uuid", "status": "SUSPENDED", "operation": "suspend", "occurred_at": "..." }
// 暂停后该租户全部 API 即时 403 TENANT_SUSPENDED；恢复后即时生效
```

**POST /api/v1/tenants/{tenant_id}/cancel** —— 平台 ADMIN（**Human-Only + 二次确认**：需携带 `confirm: true` 与原因，双人复核流程见 3.2）
```json
// 请求
{ "confirm": true, "reason": "合同终止", "operator_ticket": "OPS-2026-118" }
// 202 响应
{ "tenant_id": "uuid", "status": "CANCELLED", "data_retention_until": "2026-11-08T00:00:00Z" }
```

**POST /api/v1/tenants/{tenant_id}/context** —— 平台 ADMIN；切换自身会话的目标租户上下文（切换后该 JWT 后续请求作用于目标租户）
```json
// 200 响应
{ "tenant_id": "uuid", "switched_at": "...", "note": "所有后续请求将以该租户执行，操作全程审计" }
```

**GET /api/v1/tenants/{tenant_id}/members?limit=** / **POST /api/v1/tenants/{tenant_id}/members** —— 平台 ADMIN（租户内 ADMIN 可查询本租户）
```json
// POST 请求
{ "user_id": "uuid", "member_roles": ["MANAGER"] }
// 201 响应
{ "member_id": "uuid", "tenant_id": "uuid", "user_id": "uuid", "member_roles": ["MANAGER"], "status": "ACTIVE" }
```

**PATCH /api/v1/tenants/{tenant_id}/members/{member_id}** —— 平台 ADMIN（改角色/禁用）
```json
// 请求
{ "member_roles": ["ADMIN"], "status": "ACTIVE" }
// 200 响应：更新后成员对象
```

**GET /api/v1/tenants/{tenant_id}/quotas** / **PATCH /api/v1/tenants/{tenant_id}/quotas** —— 平台 ADMIN
```json
// PATCH 请求（临时提额示例）
{ "api_rate_limit": 300, "storage_gb": 100, "reason": "月末对账高峰" }
// 200 响应
{ "tenant_id": "uuid", "api_rate_limit": 300, "batch_max_events": 1000, "query_timeout_ms": 5000, "pool_share": 2.0, "storage_gb": 100, "events_per_month": 1000000, "updated_at": "..." }
```

**GET /api/v1/tenants/{tenant_id}/usage?since=&until=** —— 平台 ADMIN（租户内 ADMIN 可查本租户）
```json
// 200 响应
{ "items": [ { "usage_date": "2026-09-28", "api_calls": 51230, "events_in": 4200, "storage_gb": 12.4, "throttled_429": 17 } ], "next_cursor": null }
```

## 附录 C：关键流程时序图

### C.1 适配器同步链路（M2：ERP → EDP → EBMS）

```
运维/定时器          ErpAdapter(Mock/Real)      转换管道                PostgreSQL                Worker/EBMS
    │ POST /admin/adapters/erp/sync │                │                      │                        │
    │────────────▶│  fetch_incremental(since)        │                      │                        │
    │             │─────── 拉取源记录 ────────▶       │                      │                        │
    │             │        SourceRecord[]            │                      │                        │
    │             │─────────────────────────────▶ BEGIN TX                 │                        │
    │             │                                 │ ③ objects upsert     │                        │
    │             │                                 │   (revision 乐观锁)   │                        │
    │             │                                 │ ④ events insert      │                        │
    │             │                                 │   (UUIDv5 幂等)       │                        │
    │             │                                 │ ⑤ evidence insert    │                        │
    │             │                                 │   (自动 checksum)     │                        │
    │             │                                 │ ⑥ outbox insert ── COMMIT                        │
    │             │◀───────── 202 {sync_id} ────────│                      │                        │
    │             │                                 │                      │◀── poll PENDING        │
    │             │                                 │                      │──▶ PUBLISHED ──▶ 通知/缓存失效
    │             │                                 │                      │                        │
    │   EBMS 前端：GET /ebms/exceptions ──▶ 查询事件/快照 ──▶ 展示 ERP 同步数据                        │
```

### C.2 能力结果回流与决策闭环（M3/M4：识别 → 决策 → 审批 → 执行 → 验证）

```
三大能力(Agent)          Agent 中枢              EDP                        EBMS(管理者)
    │ GET /tools/* 取数     │                     │                            │
    │───────────────────────────────────────▶    │（Read-Only，越权被拒+审计）  │
    │◀──────────────── 数据快照 ──────────────    │                            │
    │ 分析：订单缺料风险 P1 │                     │                            │
    │                      │ POST /events/batch（结果事件 risk_level=P1）       │
    │                      │────────────────────▶│ 事件+证据+links 落库        │
    │                      │ POST /decisions/cases（问题+选项+证据引用）        │
    │                      │────────────────────▶│                            │
    │                      │                     │──▶ GET /ebms/exceptions ──▶│
    │                      │                     │    GET /ebms/decisions/pending
    │                      │                     │◀── POST /decisions/{id}/records（Human-Only 审批）
    │                      │                     │    决策意见→证据落链         │
    │                      │                     │◀── POST /actions（PROPOSED）│
    │                      │                     │◀── PATCH /actions/{id}/status
    │                      │                     │    PROPOSED→…→VERIFIED     │
    │                      │ POST /events/batch（action.verified 事件，闭环回流）│
    │                      │────────────────────▶│ 覆盖率/闭环率统计更新        │
```

### C.3 证据链逆向追溯（验收演示：Result → Evidence → 源数据）

```
EBMS 前端                     EDP API                          存储
    │ 点击异常/决策条目           │                                │
    │ GET /evidence?ref_type=CASE&ref_id={case_id}              │
    │──────────────────────────▶│                                │
    │                           │ SELECT ... FROM evidence.links │
    │                           │  JOIN evidence.records          │
    │                           │───────────────────────────────▶│
    │◀──── 证据集合（checksum）──│                                │
    │ GET /evidence/{id}/verify │                                │
    │──────────────────────────▶│ 重算 canonical SHA-256 比对      │
    │◀──── {"valid": true} ─────│ （失败→审计报警）                │
    │ 证据详情展示：source_system=erp, source_record_id=SO-...#v7 │
    │ （→ 可回 ERP 原始单据核对）  │                                │
```

## 附录 D：26 个设计稿 → 页面/API 映射总表

> 设计稿位于 `原型设计/pages/`；「API」列为该设计稿主要数据来源（附录 B 分组）。无对应后端接口的展示项（如 DLQ 队列）由 health/quality 聚合派生。

| # | 设计稿 | 页面/组件（路由） | 主要 API | 前端任务 |
|---|---|---|---|---|
| 1 | 运营总览 | `/admin/overview` | `GET /admin/quality/coverage`、`GET /health?deep`、`GET /ebms/exceptions`、`GET /events?limit=5`、`GET /audit-logs?limit=4` | EDP-202 |
| 2 | 业务对象 | `/admin/registry` | `GET /objects`、`GET /objects/{id}` | EDP-203 |
| 3 | 业务对象-空态 | registry 空态分支 | 同上（空结果） | EDP-203 |
| 4 | 新建业务对象-弹窗 | registry 新建模态 | `POST /objects` | EDP-203 |
| 5 | 事件流 | `/admin/events` | `GET /events` | EDP-301 |
| 6 | 事件回放-执行流程 | events 回放向导 | `POST /admin/adapters/{name}/sync`（重放） | EDP-301 |
| 7 | 证据库 | `/admin/evidence` | `GET /evidence`、`GET /evidence?ref_type=&ref_id=` | EDP-302 |
| 8 | 证据重新索引-执行流程 | evidence 重索引向导 | 质量任务 API（W5） | EDP-302 |
| 9 | 数据质量 | `/admin/quality` | `GET /admin/quality/reports`、`GET /admin/quality/coverage` | EDP-303 |
| 10 | 重新校验-弹窗 | quality 重校验模态 | 质量任务 API（W5） | EDP-303 |
| 11 | 审计日志 | `/admin/audit` | `GET /audit-logs` | EDP-401 |
| 12 | 导出审计日志-弹窗 | audit 导出模态 | `GET /audit-logs`（导出参数） | EDP-401 |
| 13 | 新建审计策略-弹窗 | audit 策略模态 | `POST /admin/audit-policies`（策略 CRUD W4 随 EDP-401 契约化） | EDP-401 |
| 14 | 适配器管理 | `/admin/adapters` | `GET /admin/adapters`、`GET /admin/adapters/{name}/status` | EDP-402 |
| 15 | 新增适配器-弹窗 | adapters 新建模态 | `POST /systems` | EDP-402 |
| 16 | 测试适配器-弹窗 | adapters 测试模态 | `POST /admin/adapters/{name}/sync`（测试模式）+ status | EDP-402 |
| 17 | 数据源连接-弹窗 | adapters 连接向导 | `POST /systems`（auth_config） | EDP-402 |
| 18 | 任务日志-抽屉 | 通用任务抽屉（quality/adapters 共用） | 任务状态/日志 API（W5） | EDP-303/402 |
| 19 | 风险详情-抽屉 | 总览/事件流/案例详情共用抽屉 | `GET /events/{id}`、`GET /evidence?ref_type=` | EDP-403 |
| 20 | 租户管理 | `/tenants` | `GET /tenants/{id}`（含 usage）、`GET /tenants/{id}/members` | EDP-501 |
| 21 | 新建租户-弹窗 | tenants 新建模态 | `POST /tenants` | EDP-501 |
| 22 | 邀请成员-弹窗 | tenants 成员模态 | `POST /tenants/{id}/members` | EDP-501 |
| 23 | 权限分配-弹窗 | tenants 权限矩阵模态 | `PATCH /tenants/{id}/members/{mid}` | EDP-501 |
| 24 | 租户切换-弹窗 | 壳层租户切换器 | `POST /tenants/{id}/context` | EDP-103（静态）/ EDP-501（联调） |
| 25 | 删除确认-弹窗 | 通用危险确认组件 | 各资源 DELETE/状态接口 | EDP-104 |
| 26 | 搜索无结果-空态 | 全局搜索/列表空态组件 | `GET /search?q=`（跨索引聚合，W6 收口） | EDP-104（基线）/ EDP-601（收口） |

**原型差异处置**（13.4.4 冻结决策的执行记录）：套餐 professional/basic/enterprise → plan 枚举 STANDARD/PREMIUM/DEDICATED；角色六名 → 五角色；风险 L1/L2/L3 → P3/P2/P1；事件类型/来源系统走展示名字典；删除确认对象标识统一用短 ID + `<code>` 高亮。
