# SDD Progress Ledger — EDP W1

Plan: docs/superpowers/plans/2026-09-14-edp-w1.md
Spec: docs/superpowers/specs/2026-09-14-edp-w1-design.md
Branch: feat/w1

| Task | Status | Commit | Notes |
|---|---|---|---|
| T1 | DONE | 3933a58 | 根依赖聚合声明 workspace 成员（uv 必须）；testcontainers 4.x 无 postgresql extra（无害） |
| T2 | DONE | a79fbab | 宿主 5432/8000 被占——后续验证用 15432/18000 映射；frontend job 带 hashFiles 守卫（T16 移除）；worker stub 重启循环（T13 换常驻） |
| T3 | DONE | b05507f | RLS 8 表（含 systems/capabilities/skills）；audit_logs.audit_id 用 BIGSERIAL（PG16 分区表限制）；alembic.ini 需 ASCII |
| T4 | DONE | 8fe837f | 15 Schema/49 业务表/42 RLS 表；position 保留字加引号；0005 revision 留给种子 |
| T5 | DONE | be73689 | admin→ADMIN 角色+is_platform_admin 通配（T8 rbac 需实现）；Python3.12 无 uuid.NIL 用 UUID(int=0) |
| T6 | DONE | 26937d2 | 54 单测；RequestIDMiddleware 纯 ASGI |
| T7 | DONE | 1d6560a | 修复 RLS 空串缺陷（NULLIF）；testcontainers ~10s/次；app 连接 function 级引擎模式（T9/T10 沿用） |
| T8 | DONE | 00a10ff | 97 单测；发现 api_keys RLS×认证矛盾（T9 解决） |
| T9 | DONE | df2b5fa | 0006 SECURITY DEFINER lookup_api_key；refresh/me RLS 死锁（T10 解决）；import-linter 加 allow_indirect_imports |
| T10 | DONE | 769d97a | refresh claims 带 tenant_id；dummy argon2 时序加固；tenant_scoped 依赖在 modules 层；create_app 工厂 |
| T11 | DONE | 6866b66 | 乐观锁双保险（UPDATE WHERE revision + 唯一键冲突回退）；outbox 副本问题 T12 收敛 |
| T12 | DONE | b3fbf6e | uuidv5 以 str(object_id) 充当 source_id 槽位；事件行幂等键={批次键}:{下标}；发现 idempotency_keys 全局 PK 缺陷（T14 修复） |
| T13 | DONE | 3886590 | Windows Proactor 不支持 add_signal_handler（KeyboardInterrupt 兜底）；退避用应用侧时钟 |
| T14 | DONE | e7ebe6d | 0007 复合 PK (tenant_id,key)；50 集成+109 单测 |
| T15 | DONE | 0e6de03 | 契约 10 路径冻结，sha256 前 8 位 c0730e43；422 为 FastAPI 默认声明（运行时映射 400）；M1 签署栏待回填 |
| T16 | DONE | 6768aac | vitest 3（vite6 兼容）；storybook 锁 8.4；onlyBuiltDependencies |
| T17 | DONE | a4ffdbd | tokens 锁定测试；防 FOUC 内联脚本；暗色持久化实测 |
| T18 | DONE | 9061103 | 不传 algorithm+6 个原型覆写（原值直出）；补 @storybook/react 依赖 |
| T19 | DONE | 3f347b0 | 16 data-dom-id 浏览器实测；激活态 primary-50（原型 CSS 实测值）；22 条路由 |
| T20 | DONE | 68af7f2 | 9 组件/31 stories/39 新测试；修复 T19 两处 shared glob 路径 bug；CursorPagination 扁平 Props |
| T21 | DONE | efe2d10 | 指纹匹配 c0730e43；.gitattributes eol=lf（防 CRLF 门禁误炸）；非 ASCII 路径 temp 复制 workaround |
| T22 | DONE | 4218312 | 三演练 exit code 正确；job 名 contract-fingerprint-gate |
| T23 | DONE | d60ddd3 | compose 全链走通（登录/对象/事件幂等/worker published/web SPA）；后端 159+前端 112 测试 |

---

# SDD Progress Ledger — W2/W3 MSW 模拟数据

Plan: docs/superpowers/plans/2026-09-15-edp-msw-mock-data.md
Spec: docs/superpowers/specs/2026-09-15-edp-msw-mock-data-design.md
Branch: feat/w2-msw-mocks

| Task | Status | Commit | Notes |
|---|---|---|---|
| T1 | DONE | - | 基线 pnpm -r test 全绿（api-sdk/shared/web 14+） |
| T2 | DONE | b748840 | 9 测试绿；评审 Approved（Minor：lib/http.ts 为计划对 spec 目录树的合理补充） |
| T3 | DONE | 297290c | 评审 Approved；额外 bd9ebaf：实装 msw 2.15 需 HttpResponse<DefaultBodyType>（计划假设 2.6）——后续 handler task 沿用该写法 |
| T4 | DONE | 612f4f1 | 23 对象逐字对齐计划；评审 Approved |
| T5 | DONE | 6e54134 | 实际 55 条（计划标题笔误 57 已修订）；风险分布 P0=1/P1=3/P2=4/P3=2；场景1 A 编码为 P3（计划对 spec "risk null" 的细化）；评审 Approved |
| T6 | DONE | 230df5b | 计划 routine 数组缺 R1/R2（18≠20）已由实现者补齐并回写计划；评审 Approved |
| T7 | DONE | 95fe47a | 4 文件逐字对齐；evidence_count 动态引用防漂移；评审 Approved |
| T8 | DONE | 687ada0 | msw2.15 适配 unauthorized(): HttpResponse<DefaultBodyType>；全量 30/30 绿；评审 Approved |
| T9 | DONE | fe86959 | 20 测试绿；评审 Approved（Minor 备忘：逐项 duplicated 计数恒 0 为计划声明的 mock 简化） |
| T10 | DONE | e8bd610 | 24 测试绿；评审 Approved（Minor 备忘：verify 无缓存恒 true、reindex 字段 sync_id 与 spec 表格简写差异——均与计划一致） |
| T11 | DONE | 978e317 | 28 测试绿；评审 Approved（Minor：tasks/:taskId 注释缺 EDP-030 标注，源头在计划模板） |
| T12 | DONE | cc6de57 | 32 测试绿；评审 Approved |
| T13 | DONE | 6caa4d7 | 37 测试绿；评审 Approved 但发现 spec §3.1 tenants/current 计划遗漏 | 
| T13-fix | DONE | 1ff8328 | 补 tenant handler + 3 测试（40 绿）；聚合注释改 27；spec 标题"28"与表格 27 本身不符——记入偏差 |
| T14 | DONE | 16e5d3b | 50 测试绿；评审 Approved |
| T15 | DONE | - | lint 绿；178/178 测试（api-sdk 22/shared 92/web 64）；build 绿；node 冒烟 3/3（P1=3、tenants/current、health）；无需收尾 commit |

---

# SDD Progress Ledger — EDP W2（总览/对象页 + 数据链路）

Plan: docs/superpowers/plans/2026-09-16-edp-w2.md
Spec: docs/superpowers/specs/2026-09-16-edp-w2-design.md
Branch: feat/w2

## 第一波（前端 T1~T9）

| Task | Status | Commit | Notes |
|---|---|---|---|
| T1 | DONE | 6ca0580 | 14 键错误码映射（13.9.2 + NETWORK_ERROR）；shared 96 绿；评审 Approved |
| T2 | DONE | 6b847c5 | 常驻横幅 + Query/MutationCache 全局 toast（banner/login/page403 跳过）；66 绿；评审 Approved |
| T3 | DONE | 11d13b3 | 七 hooks（30s 轮询）+ PanelCard 四态；类型对 handler 实测形状修正（adapters 用 Page 包裹）；73 绿；评审 Approved（降级集成测试递延 T4） |
| T4 | DONE | a204f8e | Hero 三指标（fixtures 实值 96.8%/0.81s/99.5%）+ 8 KPI；双向降级测试闭环 T3 遗留；87 绿；评审 Approved（Minor：断点/“+今日”/注释 → T5 收） |
| T5 | DONE | e375ccf | 风险卡×3 + 420px 抽屉（对象卡/时间线 4 节点/证据 2 行——fixtures 实算）；T4 两 Minor 闭环；90 绿；评审 Approved |
| T6 | DONE | a0b41a4 | 事件时间线 + 三栏（SVG 柱图/环形/审计动态 GUARD_DENIED 高亮）；panel-audit -error 降级断言闭环；97 绿；评审 Approved（原型三栏无标题——以规格为准留痕） |
| T7 | DONE | 4e1e9f2 | 双视图/域筛选/派生分布（Blocking1/AtRisk3/DQ1/Watch4/Healthy14）/游标分页/空态；event_type 修正（ORDER_RISK 是 result_type，改三类 capability.result.* 合并）；109 绿；评审 Approved |
| T7-fix | DONE | fd0cfe4 | router 退出登录用例 timeout 放宽（宿主满载 flake，基线复现） |
| T8 | DONE | 3d4d13d | 新建弹窗（三行内文案逐字/409 行内/双弹防护）+ 详情抽屉（订单 B history 7 节点）；T7 三 Minor 闭环（DEMO_NOW 锚/resetCursor/DQ pill 断言）；115 绿；评审 Approved（Minor d：vitest 侧 VITE_USE_MSW 未注入——无断言风险，留观） |
| T9 | DONE | - | pnpm -r test 115+shared96+api-sdk 全绿；lint 0 error（1 既有 warning）；build 绿；dev-server 人工冒烟未做（无头环境）——M2 演示彩排时补 |

## 第二波（后端 T10~T18）

| Task | Status | Commit | Notes |
|---|---|---|---|
| T10 | DONE | bf2aa81 | 0008 迁移：审计当月起 3 月分区 + ensure_audit_partitions() 幂等 + REVOKE UPDATE/DELETE + systems.last_watermark + adapters/audit 权限码 |
| T11 | DONE | 6389b7b | 审计切面 before_flush 全 ORM 写捕获（脱敏/截断/自引用排除）+ registry/events SQL-update 分支显式补点 + GET /audit-logs（audit_id int 对齐 MSW） |
| T12 | DONE | 62dc611 | 证据 API：canonical_json 单实现（键排序+紧凑）/compute_checksum/verify 篡改→valid=false+EVIDENCE_VERIFY_FAILED P1 告警/links 逆向追溯/跨租户 404 |
| T13 | DONE | bd2d232 | edp_adapters：SourceAdapter 端口/AdapterRegistry/ErpMock 确定性数据集（BASE 60 + DELTA 8，random.Random(42)，时间窗冻结） |
| T14 | DONE | 52e3ec0+3fc5755 | ingest 管道：三元组单事务/UUIDv5 幂等（重放 full duplicated=60）/水位推进/reconcile 三计数齐等；3fc5755 修正 import-linter 方向（api→adapters） |
| T15 | DONE | 478a71a | 管道 CLI full/incremental/reconcile（逐记录独立事务，与 API 共用 process_record）+ make 三目标；reconcile 偏差 exit 1 |
| T16 | DONE | 217ce49 | B.12 sync API：POST /{name}/sync 202 异步（进程内 job 注册表）/status 轮询/清单；AdapterSyncResponse 三字段对齐 MSW |
| T17 | DONE | f444ec1 | EDP-024 租户生命周期：开通原子（tenants+admin+quota 单事务+临时口令）/suspend→403 TENANT_SUSPENDED 恢复墙/resume 复通/cancel 强确认 400 VALIDATION_ERROR+30d 保留窗 |
| T18 | DONE | b15d6f7 | 契约重导出（sha 886ea568，12 新路径）+ api-sdk regen；前端 115 测试/lint 零 schema 破坏；docs/demo/m2-demo.md 七段+六条已知契约缺口；verify-all 全绿（后端 215/前端 115） |

终审（整分支）：Approved——M2 七条出口条件全部有可执行证据；条件项（演示脚本 409 步骤改走成功路径 + 缺口清单补 3 条 + 本行计数更正）已随收口 commit 修复；W3 待办 13 项见对话归档。

---

# SDD Progress Ledger — EDP W3（M3 关键路径）

Plan: docs/superpowers/plans/2026-09-16-edp-w3-m3.md
Spec: docs/superpowers/specs/2026-09-16-edp-w3-m3-design.md
Branch: feat/w3-m3（就地分支；未用 worktree——避免前端依赖重装；工作区既有未提交改动与本轮无关，提交纪律=仅 add 任务文件）

| Task | Status | Commit | Notes |
|---|---|---|---|
| T1 | DONE | 5df5c10 | 评审 Approved（独立复跑全量 220 绿）；Minor 备忘：dev Key 哈希命中 0 行无告警（W4 补 rowcount）、四 schema 无 ALTER DEFAULT PRIVILEGES、downgrade 非独立幂等（正常 alembic 流程不可达） |
| T2 | DONE | cf56a41 | 13 表 ORM 与 0002/0004 DDL 逐列核对一致（评审独立编译比对）；36 单测绿；Minor：默认值断言抽查而非全覆盖（可接受） |
| T3 | DONE | a92d37a | 10 类投影器与 spec §2.2 逐字段一致；41 相关测试 + 全量 297 绿；评审 Important→T4 处理：NOT NULL FK（inventory.material_id/boms.product_id/bom_items.material_id/lead_times.supplier_id）未命中会抛 IntegrityError，投影须 savepoint 包裹；Minor：默认值绕过「仅非 None 覆盖」、更新不刷 updated_at、warning 覆盖不全 |
| T4 | DONE | 709952d | savepoint 隔离经评审变异验证（no-op 即 PendingRollback 失败）；13 表排除与 ORM fullname 零缺零多；全量 299 绿；计划外必要修正：test_adapters_api/test_cli 清场先删领域行（FK 顺序）；Minor：清场 SQL 未抽公共 helper（T7/T13/T19 需沿用逆依赖序）、投影失败无指标（记已知限制） |
| T5 | DONE | 9bf254a | 十场景常量与 MSW fixtures 逐字段/逐字对齐；19 单测 + 全量 211 绿；评审 Important→T6/T7：跨适配器依赖（ORDER(erp)→PRODUCT(plm)、BOM(plm)→MATERIAL(erp)）在分适配器 run_sync 下无法同时满足，seed 必须按全局序归并逐条处理；偏差清单待 T14/T20：WH-01/WH-02 与 B.8 冲突、00123 行合计≠amount、S-021 多一条 Y-200 交期、事件 10 条口径、业务日期固定、P3 是否入 exceptions |
| T6 | DONE | 8aadd06 | 端口锚 keyword-only 零破坏；demo 适配器纯函数/确定性；注册三行；全量 226 单测 + 集成绿；评审确认 T7 硬约束：按 SNAPSHOT_RECORDS 全局序归并逐条处理（不可两次 run_sync_per_record）；Minor 备忘：plm 管道事件 actor 仍 adapter:erp（W2 遗留，可见性低）、demo 两适配器同构重复 |
| T7 | DONE | 289d113 | 归并全局序 + 逐条独立事务落实硬约束（order_lines.product_id/bom_items.material_id 非空直证）；二跑 0 新增/RESET 行数一致；全量 336 绿 + make seed-demo 实测；评审 Important→T9：RESET 需清 platform.tenant_usage_daily（否则 KPI 翻倍）；→T10：seed 建 case/links 走 raw SQL 无审计，切 decisions_service 时补；Minor：case links 语义漂移（结果证据）、RESET=0 误触发等 |
| T8 | DONE | a305d7c + e0de4af | 首评 Needs fixes（Critical：rbac 未同步 tools:read；Important：拒绝审计提交请求会话、全局 405 文案写死）→ 修复后复评 Approved；B.8 逐字段保真 + 超集文档化；三层实测（405 envelope/双轨/独立会话 GUARD_DENIED/`SET LOCAL ROLE` 生效）；全量 352 绿；偏差待记：全路由 405/404 envelope 行为变更、orders 列表 envelope、采购 next_cursor 恒 null |
| T9 | DONE | 60611a4 + f791a8d | 首评 Needs fixes（详情缺 2 字段、演示延迟误伤真实管道事件、Page.total 外溢）→ 修复后复评 Approved；结果证据+RESULT link 幂等、usage 累加、RESET 清 usage（T7 Important 闭环）；全量 359 绿；T12 待办：归档命中不计 events_duplicated、P95 口径（入口→INSERT 前）；T14/T15 待办：非 events 列表端点省略 null（含 next_cursor）记偏差、MSW 形状对齐 |
| T10 | DONE | 354b8ab + b8bb491 | 首评 Needs fixes（Important：审计前缀按裸表名冲突 decision.records→EVIDENCE_CREATE；服务层死审计）→ 修复后复评 Approved（fullname 优先映射 + 共享独立会话守卫）；B.5 逐字段 + Human-Only 实证；seed 切 service 闭环 T7 Important；全量 371 绿；T20 待记：resource_type 裸名歧义、CASE_CREATE vs MSW CASE_CREATED、裸名回退提醒 |
| T11 | DONE | 611a061 | B.9 逐字段 + OPEN/RESOLVED 真实 join 语义 + 双轨鉴权（rbac ebms:read 四角色闭环 T8 留痕）；定向 59 + 全量 379 绿；Important 待 W4：cases 无 (tenant,source) 唯一约束 → 同事件多 case 时 exceptions join 行倍增（标量子查询或约束收口）；偏差待记：P3 入列（10 vs MSW 8）、result_type 可空 vs MSW 非空、cases source_id 无索引 |
| T12 | DONE | a591990 | 基础字段 + ops_metrics 六项与 MSW 逐字；deep 鉴权实测；全量 386 绿；T15 交接：MSW `idempotency_hit_rate` 99.4→0.994（比值量纲）、`db_ha` 改可选；T15/T16 交接：真实模式总览 KpiSection/HeroCard 需字段级 `!= null` 兜底（T12 激活 /health 后缺 4 扩展字段会渲染 undefined%/NaN）；偏差待记：db_ha 仅 deep、last_sync 键为 erp-demo/plm-demo、归档命中不计 hit_rate |
| T13 | DONE | 8570816 | replay=fetch_full+since 过滤+幂等 duplicated；SyncMode 单一来源 ingest；naive since 归一（T17 datetime-local 依赖）；定向 9 + 全量 389 绿；偏差待记：非法 mode 400（plan 写 422）、since 测试窗口 anchor-5h |
| T14 | DONE | d6088a5 | 契约 23→35 路径（tools×7/decisions×3/ebms/health），events 四字段 + mode replay/since；指纹 886ea568→f5ee32a8；SDK 独立 regen 验证一致；缺口清单 6→22 条（W3-01~22）；评审 Approved；T20 补记：cases source_id 索引、adapters envelope 子项、W3-04 归属措辞、ebms exclude 例外 |
| T15 | DONE | ebe17af | MSW 三字段/health 量纲 0.994/db_ha 可选/总览字段级兜底（T12 交接三项闭环）；全量 237 绿 + tsc 0；评审 Approved；T20 补记：cursor.ts 注释过时、Page.total mock 必填 vs 契约可选、BottomThree evidence_valid_rate 真模式渲染 0%（既有） |
| T16 | DONE | 997548f | KPI 四卡/9 列派生/分页文案/空态/router 替换；web 123 绿 + build；评审 Approved；T20 补记：描述列空值率高（SNAPSHOT data 无 summary）、类型字典缺例行类型、短 ID 截取位跨页不统一（EventsTimeline/RiskDrawer 取头 8）、分页无千分位、spec「原型无搜索框」表述有误（原型有）；T18 可选：total 降级分支补测、翻页竞态禁用、测试注释计数 |
| T17 | DONE | 0f3324f | 抽屉 420px + 三步向导逐项对齐原型（未选禁用/摘要卡/202/失败 errorSpec/datetime-local→since）；web 128 绿 + build；评审 Approved；T18 修：证据行 MonoId 取头 8 → 应取尾 8（MSW 下恒 ev-00000000，潜伏）；Minor：向导步骤 3 未回显开始时间、空筛选入口死路、证据失败同空态、useAdapterOptions 预取 |
| T18 | DONE | cc75c4e | 证据行尾 8 修复 + 可证伪用例；total 降级/翻页竞态/注释三项 T16 可选闭环；API 级冒烟全链通过（health 六字段/total=50/筛选 5/证据 RESULT link/replay 36=36）；249 前端测试绿；评审 Approved；T19 必须闭环：compose 镜像重建步骤（现 18000 为旧构建 404）、m3-demo 字段名（has_next_cursor 不存在）与路径注释、浏览器级冒烟限制说明 |
| T19 | DONE | 3cb0e28 | M3 演示脚本七段（seed 幂等/tools 六接口+evidence_hint/405/403+GUARD_DENIED/exceptions P1 case_id/replay duplicated==fetched/控制台段）+ `test_m3_acceptance.py` 5 用例断言化（②~⑥ 可随时回归）；实测读数与端口偏差（18001 venv）记入 m3-demo.md；无头环境浏览器级冒烟留待彩排；T20 补记：compose `--build`、读数依赖 seed 锚与重放历史、`_jobs` 同进程语义 |
| T20 | DONE | （本 commit） | verify-all 七 job 复核：backend-lint（ruff + import-linter 2 kept）/backend-test 394 绿/frontend-lint（0 error、1 既有 warning）/frontend-test 249 绿（22+96+131）/contract-export 重导出字节不变 + contract-gate 指纹 `f5ee32a8` 绿；backend-migrate-check 对已填充 dev 库在 0005_seed.downgrade 因 `tenant_usage_daily_tenant_id_fkey` 失败（W1/W2 既有偏差，非 W3）→ 一次性 `postgres:16` 容器（15433）等价全链 upgrade→downgrade→upgrade exit 0，dev 库单事务回滚无损（0010 head / 对象 40 / 事件 50）；缺口清单 22→41 条（W3-23~41，含 T14/T15/T16/T17/T18/T19 评审补记） |

终审（整分支）：**Approved with conditions**——M3 三条出口条件均有「测试 + 演示脚本 + 实测读数」三级证据（tools 六接口 evidence_hint 直证 / 回流→exceptions case_id / seed+replay 幂等）；范围无越界、契约 35 路径指纹 `f5ee32a8` 一致；无 Critical；条件项已闭环：① `_jobs` 跨租户可见性 → 缺口 W3-42；② migrate-check 破坏性说明 → Makefile 注释 + 一次性容器法；③ 终审行回填（本行）+ 合并后复跑 verify-all。跨任务风险备忘（W4 前）：W3-23 cases 索引/唯一约束、W3-38 浏览器冒烟彩排、`evidence.links` 审计前缀裸名（W3-13 同类）。

分支收口（终审通过后执行）：① `make verify-all` 七 job 真绿（migrate-check 以一次性容器等价验证，见 T20 行）；② 缺口清单终稿（W3-01~42）已落 `docs/demo/m2-demo.md`；③ `git checkout master && git merge --no-ff feat/w3-m3`；④ 合并后复跑 `make verify-all`（contract-gate 指纹应仍为 `f5ee32a8`）。

**收口记录（2026-09-16）**：已按 ③ 合并（merge commit `1d6cc1f`，107 文件 / +19803 / −2129）；④ 合并后复跑：backend-lint（ruff + import-linter 2 kept）绿、backend-test **394 passed**、frontend-lint 0 error、api-sdk 22 + shared 96 绿、contract-export 字节不变 + contract-gate 指纹 `f5ee32a8` 绿；migrate-check 沿 T20 一次性容器等价验证。web 套件在宿主满载（Docker Desktop + 其他项目 5 个 uvicorn 占用，collect 最慢 1090s）下默认 15s 超时会随机 flake（每轮失败集不同，均为超时）；放宽 `--maxWorkers=2 --testTimeout=60000` 复跑 **131/131 全绿**——判定为环境抖动（同代码 T20/终审两轮 249/249 已绿）。分支 `feat/w3-m3` 按 W2 惯例保留（无 remote）。

---

# SDD Progress Ledger — EDP W3 补齐（W3R）

Plan: docs/superpowers/plans/2026-09-16-edp-w3-remaining.md
Spec: docs/superpowers/specs/2026-09-16-edp-w3-remaining-design.md
Branch: feat/w3-remaining（自 master 4a1715c 切出）

| Task | Status | Commit | Notes |
|---|---|---|---|
| T1 | DONE | d073df5 | 评审（并入 T2 评审补核）Approved；交接：T3/T4 须同步 rbac.py（trace:read/memory:read/memory:review）+ test_auth 计数 + test_security ALL_CODES |
| T2 | DONE | 7d6a3d0 | B.7 八端点逐字段 + 双轨/409/局部更新/跨租户实证；共表不写水位列断言；全量 402 绿；Minor 待 T12 顺手：catalog/service.py docstring「显式 tenant_id 双保险」与实现不符（读路径纯 RLS）、游标翻页未实测（>limit 数据） |
| T3 | DONE | a2061df | B.10 逐字段 + ON CONFLICT 幂等无 TOCTOU + 跨租户撞主键 409（评审裁定可接受）；trace:read 四角色同步（rbac/ALL_CODES/test_auth）；TRACE_CREATE 显式审计；全量 407 绿；Minor：B.10 契约无顶层 error 字段（上游缺口记 T8 偏差） |
| T4 | 中断 | - | 2026-09-17 派发实现子代理时遇 5 小时用量限额（重置 18:42）——恢复时按计划「## T4」+ 台账 T1 交接（rbac memory:read/memory:review 同步）重新派发即可 |
| T4 | DONE | c05b34a | **内联实施**（限额期间子代理不可用）：memories 六件套 + Human-Only 评审（独立会话 GUARD_DENIED）+ rbac 两码同步（ALL_CODES 19/test_auth 19/MANAGER 矩阵含 memory:review）；集成 5 用例 + 定向 56 绿 + 全量 411 绿（计时 flake 单跑通过）；**评审债务：待限额恢复后补评** |
| T5 | DONE | 9ef02b4 | **内联实施**：mes-demo 适配器（3 条 CAPACITY，场景 7 L1 紧张）+ delivery.capacity 投影（14 表）+ 数据集/归并/注册（清单 4 行）；新增 test_capacity_projection（seed 3 行 + replay duplicated==fetched）；全量 418 绿；偏差：mes 单测并入 test_demo_adapters（未新建 test_mes_mock.py，覆盖等价）；**评审债务：待补评** |
| T6 | DONE | 2726d73 | **内联实施**：令牌桶（进程内 per-tenant，80% 告警每窗口一次）+ 429/Retry-After（EdpError extra→响应头）+ 独立会话审计/计数 + statement_timeout（SET LOCAL）+ batch_max_events + B.14 前置（get_quota/bump 扩展）；全量 429 绿；**spec 偏差（已裁定）**：api_calls 计量改独立短会话（同事务写法持有 usage 行锁至请求结束，并发请求互等；registry 并发用例放大为死锁）——语义从「受理成功调用」变「全部请求」，记缺口清单；测试基建：conftest 每用例复位配额三字段 + 14 处临时租户清场补 usage 删除；**评审债务：待补评** |
| T7 | DONE | 7155a94 | **内联实施**：`GET /tenants/{id}/usage`（平台 ADMIN，since/until 闭区间 + 游标）+ `query_usage`/`UsageItem`（events_duplicated 超集）；4 集成用例；**评审债务：待补评** |
| T8 | DONE | 379dd3a | **内联实施**：evidence `q`（ILIKE + 通配转义，含组合过滤/字面 % 用例）+ 契约导出（新增 15 路径 + q）→ 指纹 `f5ee32a8→09f2dae7` + SDK regen（22 测试绿）+ 缺口清单 W3R-01~12（限流单副本/api_calls 偏差/审计动作词表/usage 权限面等）；全量 434 绿；usage 用例隔离修正（前后全清，防他测今日行干扰） |
| T9 | DONE | 5364d52 | **内联实施**：证据库页（KPI 四卡真/降级、卡内搜索 q 防抖、双栏列表+链图、verify 联动本会话 pill、重索引三步向导 MSW-only 真模式禁用、空态建议关键词）；MSW evidence handler 补 q；5 用例 + 全量 136 绿；lint 恢复基线（helpers 拆 derive.ts） |
| T10 | DONE | dc2f33d | **内联实施**：数据质量页（KPI 4 卡/维度 5 条 <95 warning/异常卡走真 EBMS API + 合并提示/重校验弹窗默认全选+本地通知/任务日志抽屉轮询）；真模式面板降级 + 重校验禁用（404 模拟用例）；3 用例 + 全量 139 绿 |
| T11 | DONE | f363e68 | **内联实施**：系统健康页（HA/备份/Outbox/告警四卡 + 演练入口 + 10s 深层轮询；真模式 backup 降级/HA·Outbox 真值）；2 用例 + 全量 141 绿 |
| T12 | DONE | 05cbd0e | **内联实施**：m3-demo.md 补「W3 补齐」六段（catalog/trace/memory/capacity/限流+usage/前端三页人工清单）+ `test_w3r_acceptance.py` 5 用例（①~⑤ 端到端）；门禁：backend-lint 绿 / backend-test **439** / frontend-lint 0 error / frontend-test 259（22+96+141）/ contract-export 字节不变 + gate `09f2dae7` / migrate-check 一次性容器 exit=0 |

**评审债务（限额期间内联实施，待补独立评审）**：T4（memories）、T5（mes/产能）、T6（限流）、T7（usage API）、T8（证据 q+契约）、T9（证据库页）、T10（质量页）、T11（健康页）、T12（收口）——共 9 项任务评审 + 整分支终审未做（T1~T3 已评）。限额恢复后补做；发现问题的修复以新提交落 master。已内联验证证据：各任务定向测试 + 全量 439/259 绿 + lint/import-linter + 契约指纹 + migrate-check 容器等价。

**合并记录（2026-09-17）**：按用户决策「先合并，评审债务后补」合并 `feat/w3-remaining` → master（分支保留，无 remote）；合并后复跑契约指纹与后端 lint。

---

# SDD Progress Ledger — EDP W4（M4 闭环集成 + W3 遗漏收编）

Plan: docs/superpowers/plans/2026-09-17-edp-w4.md
Spec: docs/superpowers/specs/2026-09-17-edp-w4-design.md（ff84165 + 权限码修订 673fe4f）
Branch: feat/w4（自 master 673fe4f 切出；T1 后 rebase 吸收评审修复 f33ed13/a0d188f）

## 并行线：W3R 评审债务补评（开工即派发，先于 W4 主线闭环）

| 项 | 结论 | 处置 |
|---|---|---|
| 后端 T4~T8 五项 + 终审 | Approved with conditions（4 Important：capacity 审计排除/nginx 样例缺失/429 未声明/缺口漏录） | 修复批次 master f33ed13 |
| 前端 T9~T12 四项 + 终审 | Approved with conditions（5 Important：chips 全清/Derived 判定/KPI 全量/重校验刷新/m3-demo 变量） | 修复批次 master a0d188f |

## 主线任务表（子代理逐任务实施 + 主线抽查）

| Task | Status | Commit | Notes |
|---|---|---|---|
| T1 | DONE | 5f10373 | 0012 迁移（audit.policies + cases 唯一索引 W3-23 + audit:policy 两码 + write:action scope）；56 测试；容器 upgrade→downgrade→upgrade 全周期；RLS 键按仓库惯例 app.tenant_id |
| T2 | DONE | d0252f1 | 9 态转移表单点/422 extra.allowed_to/rowcount 409/Human-Only 独立会话审计/comment 落证据（object_id 经 case.source_id→event 解析，无源跳过留痕）；+108 测试（全量 552）；发现 test_adapters_api _set_demo_anchor NULL attributes 缺陷（W4-08） |
| T3 | DONE | b092c86 | B.9 四端点（summary/pending/todos/objectives）+ management seed 幂等；+6（558）；limit 越界 400 非 422 留痕 |
| T4 | DONE | 1de8038 | audit_policies 四端点 + 三维匹配打标（进程内缓存单副本 W4-03）；require_permission 直用（权限码非 resource:mode 形态）；+8（566）；record_explicit 路径不打标（W4-04） |
| T5 | DONE | dc49b18 | case detail 扩展（event/steps/actions/evidence_chain 向后兼容）+ ebms 标量子查询 + source 重复 409；+5（571）；steps ACTION 快照 human_only=下一转移语义（W4-02） |
| T6 | DONE | ba03e99 | 越权矩阵 41 用例（跨租户 16+3/角色 8/Key 轨 9/RLS 直查 5）进 CI 常驻；/tenants/{A} 为 403 非 404（授权先于存在性，留痕）；+41（612） |
| T7 | DONE | eca7848 | AdapterListResponse 补 next_cursor 恒 null（W3-24） |
| T8 | DONE | f0c4ad0 | 契约 44→53 路径（12 新操作）+ tools 7 端点 429 声明（B.8/W4-09）+ SDK regen；指纹 09f2dae7→687b6cd7；缺口 W4-01~09 初稿 |
| T9 | DONE | 09324ff | /cases 列表+详情四区（问题卡/证据链横向图 verify 联动/Steps 人形图标/行动卡）+ RiskDrawer 泛化提升 shared（尾 8 收口 W3-31）；web 141→148 |
| T10 | DONE | 02abdef | /decisions 待决+Human-Only 表单、/actions 9 态状态轴+allowed_to 按钮+409 逐字文案；422 重渲染经详情重拉（SDK 不透传 extra，W4 留痕）；148→160 |
| T11 | DONE | 1153fb2 | 7 列/五参筛选/chips 按键清除/导出 CSV（1000 上限+BOM）/策略 tab CRUD/GUARD 高亮/词表（W3R-03/13/14 收口）；160→174 |
| T12 | DONE | f0dc25b | 适配器页三弹窗+可回退向导+日志抽屉（W5 提示）+W3-37 useAdapterOptions 门控；fixtures 实为 5 适配器沿既有集；174→184 |
| T13 | DONE | c972e40 | m4-demo.md 七段实测读数（compose --build + RESET）+ test_m4_acceptance 6 用例（真·并发 409）+ 彩排清单（W3-38）+ W4-10；+6（618） |
| T14 | DONE | 97665ef | staging 双节点（etcd×1+patroni×2 自建镜像+pgbackrest）双向 switchover 2/2、/healthz 40/40、lag 3.2ms、全量备份 32.3MB、rollback 实测；单写入口不自动跟随（W5 HAProxy）；EDP_JWT_SECRET 弱密钥留 W5 |
| T15 | DONE | 38bf833+（本行随收口 commit） | verify-all：backend-lint/test（make 顺序证绿）/frontend 302（184+22+96，Makefile 防抖参数固化）/contract 687b6cd7/migrate-check 一次性容器 15433 exit 0；终审 Approved with conditions 两项闭环（W4-11~13 + spec 同步） |

终审（整分支）：**Approved with conditions→已闭环**——16 节逐节核对（终审代理报告）：范围零越界（无关文件零混入）、契约三处指纹一致、波 2 零 contracts/ 改动、四页与 SDK 类型对齐、越权矩阵/演示读数/staging 演练全实证。条件项：① I-1 PATCH 双轨超 B.5「仅 JWT」→ 保留有意行为，W4-11 + spec §3 同步；② T15 收口 → 本行 + verify-all 全绿。Minor 顺手闭环：POLICY 审计前缀、ACTION_UPDATE resource fullname 统一（W4-13）；其余 Minor（422 extra 透传/词表预留前缀/notify_channel 演示文案/JWT 弱密钥）留 W5。

收口记录（2026-09-18）：feat/w4 15 任务 + 并行评审线全部闭环；测试基线 439/259 → 618/302；缺口清单 W4-01~13 终稿落 docs/demo/m2-demo.md；M4 出口三条：7 分钟脚本（m4-demo.md 实测读数）+ 越权矩阵 0 泄露进 CI（test_security_matrix.py 41 用例）+ 彩排 ≥2 次中 1 次仓库内可复现（浏览器级 5 步清单人工执行）——三方彩排与 PM/Tech Lead 签认线下补。

# SDD Progress Ledger — EDP W5（M5 可靠性与质量 + W4 遗留收编）

Plan: docs/superpowers/plans/2026-09-20-edp-w5.md
Spec: docs/superpowers/specs/2026-09-20-edp-w5-design.md（d2848d8）
Branch: feat/w5（自 master 0e6bf76 切出）

## 主线任务表（子代理逐任务实施 + 逐任务评审）

| Task | Status | Commit | Notes |
|---|---|---|---|
| T1 | DONE | bf38340 | 0013 迁移（ops.tasks + quality:read/run）；55 定向 + 全量 622 绿；评审 Approved（幂等三重容器验证：重跑/downgrade 回退/stamp 重执行）；Minor 备忘：DROP POLICY 表缺失时报错（沿 0012 仓库模式） |
| T2 | DONE | 50fa456+5a1719b | B.14 七端点（PATCH/context RLS 真断验/members 双轨/quotas 七字段/current-usage W3R-04 收口）；+5（627→修复后绿）；评审裁定：校验 422→400 VALIDATION_ERROR（三处，cancel 同构先例）+ from_tenant effective 语义（修复 commit）；Minor：配额空更新 200、check-then-act 竞态 docstring 登记（T17 覆盖） |
| T3 | DONE | 76db8c8 | reports/coverage 四段 + kpi/dimensions 逐字对齐 mocks；+16；评审 Approved；Important 移交 T4：checksum 抽样 evidence_id 升序冻结问题改 captured_at DESC；裁定：ingest 副作用计量接受留痕、dimensions 四段标识 T13 按真形状消费、source_count 可空 T9 契约注意 |
| T4 | DONE | 10c0719+beb3229 | rechecks 202/tasks 轮询/质量事件/TASK 审计前缀；评审证伪 FOR UPDATE 可见性探测（PG16 RC 不等未提交 INSERT）→ 修复有界重试 + 完成事件移出终态事务 + 抽样排序专项（25 绿）；T3 移交抽样 captured_at DESC 一并落地；裁定：object 锚定/进程存亡留痕可接受 |
| T5 | DONE | be31da9 | _jobs 迁 ops.tasks + jobs 端点（keyset 游标）；契约形状逐字不变（对照冻结 openapi）；+回归 15 绿；评审 Approved；Minor 移交 T6：并发触发语义 docstring、FAILED 路径测试、第三次复制时抽 _wait_task_visible 公共 helper |
| T6 | DONE | c6c1457 | reindex 202/keyset 分批全量重算/原值不回写/聚合失配事件 + wait_task_visible 抽公共实现（quality 单点）；+23 绿；评审 Approved；裁定：evidence↔quality 双向 service 引用接受（运行时属性访问 + docstring 防线，无 no-cycles 契约）；T5 移交 Minor 全落地 |
| T7 | DONE | 685c199 | drill-records.json（switchover 回填 W4 实测、pitr/tenant_restore PLANNED）+ GET /admin/drills 容错直读；5 绿；主线抽查 Approved；备忘：drill_type 用 tenant_restore 下划线（T11 前端对齐）、rto=0 语义=healthz 零中断（DB 写面读数在 readings） |
| T8 | DONE | 1cbd616 | staging JWT 强密钥（api/worker 同值）/QUALITY_* 前缀派生（POLICY_* 核实既有覆盖仅锚定）/notify_channel 文案；audit 16 绿 + compose config 过；主线抽查 Approved（4 文件范围内）；备忘：pnpm 包装器 ChildProcess.kill 工具层问题（vitest/eslint 直跑等价）、mocks 策略 fixture notify_channel 旧文案留 T13 顺带 |
| T9 | DONE | 3ed08fa | 契约 53→65 路径（+15 操作，26 新 schema，既有 schema 零改）；指纹 687b6cd7→4b576ee5（contract-gate 主线复跑绿）；api-sdk 22 绿；缺口 W5-01~10 初稿；顺带修复 W4-11~13 三行 GBK 混入转 UTF-8（内容零改）；波2 起契约冻结 |
| T10 | DONE | 1e46bf4 | 租户列表/详情/成员/配额 + 4 弹窗 + context 切换链（token/clear/store 真断言）；web 184→205；评审 Approved；裁定：usage 与 /admin/users mock 扩展接受（后者记缺口 W5-11，T18 落清单）、operator_ticket 留痕不下发；Minor：切换弹窗「· 生产环境」硬编码、配额预览未做、权限矩阵表后续可选 |
| T11 | DONE | d3af575 | 演练回放页三卡（PLANNED 降饱和/RTO-RPO 千分位/readings 键值/manual 文本）；+3 用例 42 文件全绿；主线抽查 Approved（8 文件范围）；备忘：RPO 折 ms 口径、全量套件偶发负载 flaky（复跑绿） |
| T12 | DONE | 7d7a999 | 工具试查/Trace 抽屉 token_usage 三卡+两级树/记忆只读；+16（224）；评审 Approved（6 条契约驱动偏差抽验全成立——CANDIDATE 枚举/扁平 tool_calls/本地过滤先例等）；Minor：traces/hooks 注释失实（T13 顺手修）、capability 三处硬编码留 follow-up |
| T13 | DONE | 6786b28 | 质量真形状/重校验单选+轮询/日志抽屉历史/重索引两终态/备份卡 drills/Bell 未读清零；231 全绿 + tsc/eslint/build；评审 Approved；裁定：客户端过滤记缺口（FEED_WINDOW=50 挤出风险）、失实 UI 修正非退化、OverviewPage 连带合规；Minor：清零竞态毫秒级/备份卡键名语义/两处注释 |
| T14 | DONE | 0dcef18 | minio+init-minio 增量上栈零中断；repo1 迁 S3 实测（全量 32.3MB/9.9s、1576 对象、4.8MiB）；关键发现：pgbackrest 2.59.1 明文 S3 需 http:// 前缀+path uri-style；.gitattributes eol=lf 防 CRLF 超清单报备；主线抽查 Approved |
| T15 | DONE | cf3ea07+2b21855+40cc4ec | 三项演练实测：a) 备份 cron 容器内循环 + verify 3/3 GREEN（check 0.6-1.0s/restore 9.5-9.7s）；b) PITR RTO=22.1s/RPO=0s（端口 15433 避 dev 占用）+ timeline 污染加固（--target-timeline=current + archive_mode=off）；c) 租户恢复 RTO=23.8s（events 120/120/120 + checksum 5/5，api 断言降 DB 层等价留痕）+ drill-records 回填 + test_drills 断言同步；主栈零重启 |
| T16 | DONE | 5b69c89 | HAProxy 单写入口（httpchk /primary 选主）；双向 switchover 2/2、healthz 80/80 零中断、DB 写面 120/120 经代理、自动跟随 ≈0.6s 回挂/≈1.1s 摘除；主栈零扰动；顾虑：healthz 无 DB 依赖（写面单列证）、切换窗口旧连接单次报错（预期语义留痕）、staging api 镜像待 --build 见 quality 模块 |
| T17 | DONE | 3c39113 | Redis 外置评估文档 170 行（三点位×三方案+人日估计+建议）；W6 决策输入 |
| T18 | DONE | d03b40d+68efffa+4783473+（本行随收口 commit） | verify-all 七 job 全绿：backend-lint / backend-test **663 passed**（618→663）/ frontend-lint 0 err / frontend-test **349**（web 231+api-sdk 22+shared 96）/ migrate-check 一次性容器终态 0013 / contract-export 字节不变 / gate 指纹 **4b576ee5**；收口修复三件：测试隔离（W3 老测试补 ops.tasks 清场 + w5 RLS 断言解耦，d03b40d）、Makefile 前端防抖参数生效（pnpm `--` 透传致 vitest 参数失效，68efffa）、终审 I-1 drills JSON 容器供给（4783473，staging 容器实测挂载生效）；缺口终稿 W5-01~21 |

终审（整分支）：**Approved with conditions→已闭环**——终审代理报告：范围零越界（138 文件全在预期前缀，脏文件零提交）、契约纪律零违规（T9 后 contracts/ 零改动，三处指纹一致 4b576ee5）、跨任务集成自洽（ops.tasks 三生产者语义一致/wait_task_visible 单一实现/前端冻结 SDK 对齐）、证据一致（演练数字两文档全等、663+349 实测）、缺口覆盖抽查 6/6。条件项：① I-1 演练 JSON 容器供给 → 4783473 修复 + staging 容器实测闭环；② T18 收口 → 本行。Minor 三项（adapter FAILED stats 空/switchover rto=0 口径/drills 读权限）留 W5-21。

收口记录（2026-09-21）：feat/w5 18 任务 + 逐任务评审 + 整分支终审全部闭环；测试基线 618/302 → **663/349**；契约 53 路径 687b6cd7 → **65 路径 4b576ee5**；M5 出口三项：Patroni 三项演练归档（W4 切换 + T15b PITR RTO 22.1s + T15c 租户恢复 RTO 23.8s）、质量覆盖率端点可用、备份可恢复性连续 N≥3 等价证据（W5-07 偏差）；演练读数终稿 w5-drills.md + drill-records.json；缺口清单 W5-01~21 终稿落 m2-demo.md。环境备忘：dev db 重建时遇 FinalShell（用户 SSH 工具）占用宿主 5432 无法绑定，dev 栈 db/api 待端口释放后 `up -d db api` 恢复（不影响本分支交付与测试——测试走 testcontainers）。

合并记录（2026-09-21）：`git merge --no-ff feat/w5` 落 master（merge commit 见 `git log -1`；合并树与分支树字节一致）。合并后 verify-all 复跑：backend-lint / frontend-lint（0 err）/ frontend-test（231+22+96）/ migrate-check（一次性容器 15433 终态 0013）/ contract-export 字节不变 / contract-gate 4b576ee5 全绿；backend-test 唯一失败为 W1 既有登录时序加固用例（test_tenant_context.py::test_login_timing_user_enumeration_hardened，宿主满载 18:40 下 argon2 时序抖动：missing 475ms vs wrong_pw 280ms）——隔离复跑 1 passed（11.7s）确认负载 flake，同树 pre-merge 全量 663 passed 已绿，非本分支回归（W2 同类 flake 有基线复现先例）。

# SDD Progress Ledger �� EDP W6��M6 ������������ + W5 �����ձࣩ

Plan: docs/superpowers/plans/2026-09-22-edp-w6.md
Spec: docs/superpowers/specs/2026-09-22-edp-w6-design.md��181bde5��
Branch: feat/w6���� master be84ff4 �г���

## ������������Ӵ���������ʵ�� + ����������

| Task | Status | Commit | Notes |
|---|---|---|---|
| T1 | PENDING | | |
| T2 | PENDING | | |
| T3 | PENDING | | |
| T4 | PENDING | | |
| T5 | PENDING | | |
| T6 | PENDING | | |
| T7 | PENDING | | |
| T8 | PENDING | | |
| T9 | PENDING | | |
| T10 | PENDING | | |
| T11 | PENDING | | |
| T12 | PENDING | | |
| T13 | PENDING | | |
| T14 | PENDING | | |
| T15 | PENDING | | |
| T1 | DONE | 37c4b79+98231eb | search �����ۺ�+events ǰ׺������+9 ������23 �̣������� Needs fixes���ѱջ���C1���ֶ� 422 �ŷ� INTERNAL���� 400 VALIDATION_ERROR ����ֿ������cancel ͬ����������Minor ���ۣ�ILIKE ͨ�����ת�壨docstring ���������� |
| T2 | DONE | 1a04f0c | outbox status��FILTER �����������/admin users��keyset��/health ���ֶΣ�+9 ������ȫ�� 680 �̣����� Approved���ھ� a~d ȫ Accept����**������**���ٿ��⻧�û�Ŀ¼�ϵ㣨require_platform_admin ���� act_tenant ��λ��context �л����Ի����⻧�û�����ѡ ?tenant_id bind/effective_tenant_id/SECURITY DEFINER���Ǽ� T9 ��+T14 ��Լ�嵥����MSW PlatformUser[] ���������ʵ Page{items} ��״���䣨T9 �ظģ�����Minor��outbox max(published_at) �� FILTER����д·������ʽ������ֱ�岻�����У� |
| T3 | DONE | cafc0d1 | TaskMutex ר������ try-lock���� ops.task:{type}[:ref_name]�������Զ�������+drills �ս� quality:run+ingest internal ���� bump_usage_daily+pg_stat ������compose/pg-init/patroni����+5 ����ȫ�� 685 �̣����� Approved������ a/b/c ȫ Accept��W5-21-a ��ʵ W5 ����������ԣ���Minor ���� 4 ����BaseException ȡ������/hint ��ѯ����/���⻧��ȡ��spec �ھ���/hashtext ��ײ���� |
| T4 | DONE | 5a70ab6 | ��Լ 65��68 ·����search/outbox-status/admin-users + events prefix ���� + ops_metrics 5 �ֶ� + BackupMetric �� 8 schema����ָ�� 4b576ee5��d1929b21��SDK 22 �̣��ṹ�� diff �����˶���Ԥ����仯��ȱ�� W6-01~09����Ŀ 92~100�������߸��� contract-gate �̣�**����**��quality ���� 409 TASK_CONFLICT δ����Լ������T3 �� error_responses ��·����spec ��9 δ�С�������ʱ�� 409/SDK ����ѡ��W6+ �� Go/No-Go �ö��� |
| T5 | DONE | 6a9dc63 | seed --scale N��ê��־û��� UUIDv5 �ݵȣ���� raw SQL �� 1000 ��д outbox/��ơ�������ѹ��Ⱦ��������׺ 6 λ�����˻��� 5 λβ�Σ������� 43/53/53��N=116��4988/49503/10033��147s����+5 ����ȫ�� 690 �̣����� Approved�����ö����飺outbox ������ѹ��д·����������6 λ��׺ȫ�����߼��ȶԣ���Minor ���ۣ�N>1e6 �߽�/ˮλ���Ŵ�ƫ��/usage duplicated ���� |
| T6 | DONE | f4015f0+5a1ac15+629f47d | locust ����ʵ�⣨9 �ӿ� P95 31ms~1.0s ȫ��ꣻ��ֵ 46.9rps@50VU��100VU DB �ر��ͳ�β��������֤�ݹ���+RLS ˫�죨��� +97.1%/���� +3.3ms��������ղ�� ��0.5ms �����ذ壩+pg_stat top20 �鵵��tenant_usage_daily upsert �ܺ�ʱ��һ��+���油��ʽ˫�ж���T12 �Ž��ɾ��Կھ�����������������27 �� P95 ����������ƫ����� Approved��ѹ���ڼ� B.14 ��ʱ����������������+�ָ�����׼��������**T7 ǰ�ø�����**��events count �����ɵ㣨��Ϊ health ops_metrics ���� events �б��������������� 8000 ռ���� override ӳ�� |
| T7 | DONE | 2cc843e+27c6635 | count ������EXPLAIN ʵ֤��events count 0.096ms ����ɨ��10ms ��ʵΪ health _ingest_peak/_p95_latency 3613 ���Ǻϣ��鵵 explain-t7-count.txt��+�� 0014 Ǩ�ƣ�top20 �� >500ms��usage upsert 9.65ms ϵ������̻Ự�̶�����������ȱʧ��uq_usage_daily �� 0001 �ѽ���+�� 10+20 Ӳ�������� W7+ �����滮+Redis ��7 �սڣ�����λȫ�����룬������������������+Ԥ�ۺϱպϣ�reports P95 420ms@100VU<2s��m2-demo 73 ��ע�ǣ������߳������� |
| T8 | DONE | 5d30209+b6037cc | ServerErrorPage+RouteErrorBoundary ����״��һ�Ҹ� errorElement��RequireRoles ��������/tenants* ƽ̨ ADMIN��drills ADMIN+ ���� T3����SearchPage ����+��̬��MSW fixture �������� Schemas ���ͷ�Ư�ƣ�����ҳ��̬�տ�+Health �ö����裨������� 0 ��ѹ=Ŀ��̬����+12 ���������� Approved�����ö� Accept����Լƫ������֡���revision/risk/verify δ����СͶӰ�� T1 ������ƣ�Health ��̬���壩��Minor �޸�������b6037cc��docstring ����+W6-10 �Ǽ�+��Ա�� isError�������ۣ�Topbar ������ URL q�����ţ� |
| T9 | DONE | 0189592+de40a5a | useCapabilities ���� hook����̬���� FALLBACK��fixture �����������б�����+InviteMemberModal Page �ŷ�/404 ���併��+Bell event_type_prefix=quality.+switchover rto ��ע��+9 ���� 371 �̣����� Approved�����ö� Accept��tools ҳ�� capability UI ������ʵ����ʵΪ traces/memory+mocks label�����ػ��˲��ڸǹ��Ͽ�֤α��362 ����ϵǰ�α����������ļ�����Minor ��������de40a5a�����б���������+�ŷ�����ͳһ�������ۣ������� UI �źţ�����������ʾ��/ȫ�� 4 ������ flaky����ʱ�ͣ������̣�/MSW drills fixtures ������ļ� |
| T10 | DONE | f5614c4+e81f061 | Playwright ����+closed-loop���Ŷ����£�׷���ʶ���=DOM ʵ��������֤�� verify+�������������ս����ж� API ��+UI ��̬�ƽ��������뽨����Ϊ stub �ü����ۣ�+tenant-isolation��5 API ����+analyst1 �������+UI ���� toHaveCount(0)��B �⻧�ű��ڿ�ͨ 409 ���ã�+e2e.yml ��ջ job+README��61 �� locator 100% data-dom-id������ 3 ���̣�8.7s/1.6s����CORS �ⷨ=ͬԴ����+preview.proxy�������� nginx ͬ������֤����ȫ���������� Needs fixes�����ޣ�html reporter ���� artifact+��־�ϴ� e81f061����CI �̴� push ��������֤���ջ������� admin��13.8 ������Լ���� |
| T11 | DONE | 64c7bf4 | �Ӿ��ع�˫�㣺��� 34 story��storybook-static index.json �Զ����棩+ҳ�� 18 ·�ɣ���ջ��ҳ����ȷ���������ף�seed �̶�ê --anchor ����+ʱ�� setFixedTime+��̬�� mask����win32/linux �� 52 ���ߣ�linux �� v1.63.0-noble �ٷ���������=�� CI ubuntu-24.04 ͬԴ��preview --host+allowedHosts ���ף�������������+���������̣�CI ���루�̶�ê���� seed��build-storybook��e2e:visual��������ִ�У��Ӵ����޶��web 253 ������ |
| T12 | DONE | ca8ac9b | ops_report.py����ָ�꣺������/׷����/�ٻ���/�ջ���/ԽȨ/���������/P95/����/HA��BYPASSRLS ƽ̨ȫ��+locust ֱ��ͼ P95+drills/e2e-result JSON ��ȡ��+make ops-report+���� JSON/Go-No-Go md+5 ���ԣ��տ�ð��+װ��+��������dev ʵ�����ȫ PASS��closure 0/0 �ռ��ھ���ʵ��ʾ����T15 �տ�ǰ�� E2E �ջ��������ݣ�������ִ�� |
| T13 | DONE | (�� commit) | trial-patrol.ps1��5 ̽��/P0~P3 �ּ�/TSV ��־��+staging ����deploy-staging.ps1 �´��뾵��leader=staging-pg1��+seed --reset+ʵ�� 3/3 ����ȫ OK��healthz 200/18-57ms��deep OK��outbox 0 ��ѹ��coverage 200���� �ȼ��տڣ�ƫ���3 ���� N��3 ���ڵȼۣ�2min ���ٴ��ڣ�/staging ����/˲ʱ̽�����ȣ�w6-trial-run.md �鵵������ִ�� |
| T14 | DONE | (�� commit) | frontend/README.md����� 9+·�� 18������+ö���ֵ�+13 �������߲��+MSW/E2E ά��+Memory ����ӹ�С�ڣ�+ops-runbook������/�ճ�/����о�/���ϴ��ñ���+drill-handbook����������鵥��+faq��12 �ʣ�+prod-deploy-design��HAProxy ˫ʵ��+keepalived/VIP+�����д���+�����嵥�����ĵ���������ִ�� |
| T15 | IN_PROGRESS | (����) | verify-all ���ܣ���� 694 �� 1 �ܣ�ops-report ð�̿տ���衪�����ޣ��ṹ��Ǣ����+���븴�� 5 �̣���ȫ�����ܣ���**ʣ��**����make verify-all ȫ�������̣���E2E closed-loop ʵ�ܺ����� make ops-report���� closure/audit �����ݣ��滻 0/0 �ռ�������ȱ���ո帴�ˣ�W6-01~10 ���� m2-demo.md������git merge --no-ff feat/w6 �� master ���� verify-all+ָ�Ʋ��䣻��̨�������� |
| T15 | DONE | 0024c9a+ee0a6c3+���� commit�� | verify-all �ȼ�ȫ�̣�backend-lint �̣�backend-test **695 passed**������ 1 ��=ops-report ð�̿տ������ṹ��Ǣ�����޸�����frontend 371��253+96+22��T11 ����ǰ�˴���������migrate-check һ�����������Σ�upgrade��downgrade base��upgrade��ȫ����dev ��ײ���� 0005 FK ��Ϊ��Ԥ�ڣ�Makefile ע�Ϳھ�����contract-export �ֽڲ��� + gate ָ�� **d1929b21**��E2E ���ű������̣��ջ�+���룬7.8s����ops-report �հ� closure/audit ������ 1/1�������� 3/3 �ȼ��տ� |

**W6 �տڼ�¼��2026-09-22��**��feat/w6 15 ����ȫ���ջ���T1~T14 �Ӵ���/����ʵ�� + ����������T15 �տڣ������Ի��� 663/349 �� **695/371**����Լ 68 ·��ָ�� 4b576ee5 �� **d1929b21**��ȱ�� W6-01~10��m2-demo.md ��Ŀ 92~101����M6 ���ڣ�ѹ�� P95 ȫ <2s + RLS ˫�ھ����桢��Ӫ�����ָ��ȫ PASS�������� 3/3 ���ڵȼۡ��ĵ�����鵵��������CI e2e.yml push ����֤��prod �����д��ڣ����ڣ���

**W6 ��������2026-09-22��fix/w6-followups��**��D-13 ���񻥳� 409 ��������Լ��error_responses �������ǲ��� + ���˵�������ָ�� d1929b21��**2b9ed988**��SDK regen+gate �̣���D-14 Topbar ���� URL q��+2 ���ԣ���D-15 capability ���������źţ�isFallback+�������嵥�����á���ʾ��+ MSW drills fixtures �������ļ���pitr/tenant_restore SUCCEEDED ʵ��ֵ����������ҳ���Զ��������ݡ�����ȫ�����ݡ��������ļ��ޡ���С��������pitr ���иĶ������������Ž������ 695 / ǰ�� 257��+4��/ ruff/lint-imports/contract-gate ȫ�̡�ʣ�ࣺA-1��push ���� e2e.yml����D-16��outbox FILTER СӲ������D-17��health Seq Scan ��ģ��������D-18~20/E������/���ڣ���

**W6 ��ȫ�޳���2026-09-23��master��**��staging ��ʵ��Կ��MinIO root ����/JWT secret���Ӳֿ���**ȫ����ʷ**�޳������������� deploy/.env ע�루compose ��Ĭ��ֵ + PGBACKREST_REPO1_S3_KEY_SECRET ��������ע�� pgbackrest�������ļ�ȥ��Կ��+ ģ�� deploy/.env.example��git filter-repo --replace-text ��дȫ�� 8 ��֧��ʷ���� HEAD 0cec8ea��+ ǿ�� Gitee����֤������/Զ����ʷ 0 ������8 ��֧Զ��=���ء�staging ȫ��·ʵ��ͨ������¼/���/pgbackrest info ok����**���죺�ѹ�����Կ�����ֻ�**������ deploy/.env �� up -d �ؽ� patroni/pgbackrest/minio����
