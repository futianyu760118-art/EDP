# M2 演示脚本（W2 收口版）

> 环境：Windows 宿主 + Docker Desktop。端口走本地 override 映射：db→**15432**、api→**18000**、web→**9080**。
> 种子凭据：`admin / Admin@123!`（平台管理员）、`manager1 / Admin@123!`、`analyst1 / Admin@123!`。
> 顺序建议：①②（MSW 保底）→ ③起真实环境 → ④数据链路（**必须 full + incr 都跑**）→ ⑤篡改 → ⑥租户生命周期 → ⑦对账收尾。

---

## ① MSW 模式：运营总览页（无需后端）

```powershell
cd frontend
$env:VITE_USE_MSW = "1"
pnpm --filter web dev
```

浏览器打开 `http://localhost:5173`，登录（mock 接受任意非空密码，推荐 `manager1`）。

**预期**：

- Hero 状态卡：「今天的 EDP 状态：证据链健康，1 个 P1 风险需要处理」+ 三指标（对象覆盖率 96.8% / P95 0.81s / 适配器成功率 99.5%）
- 8 张 KPI 卡（业务对象 / 24H 事件 / 证据存储 / 适配器成功率 / DLQ 队列 / P95 延迟 / 审计日志量 / 策略命中）
- 风险抽屉：点击任一风险卡（或 Hero「查看风险详情」）→ 右侧 420px 抽屉：RSK- 前缀、受影响对象卡金额、4 节点事件时间线、≥2 行关联证据
- 三栏：数据健康（24 柱 SVG 柱图）/ 证据链健康（环形有效率）/ 审计动态（GUARD_DENIED 行 error 高亮）
- Network 面板可见各面板 30s 轮询

## ② MSW 模式：业务对象页交互

导航「业务对象」（或 `/registry/objects`，以侧栏实际入口为准）。

**预期**：

- 23 个 fixture 对象卡片；分页文案「显示 1–20 条，共 23 条」
- 搜索 `SO-2026-00123` → 仅 1 卡；状态筛选「At Risk」→ 3 卡；域筛选联动
- 卡片↔表格视图切换；派生状态 pill（Blocking/At Risk/DQ Exception/Watch/Healthy）
- 「新建对象」弹窗：空提交三条行内错误逐字；合法值提交 201「对象已创建」+ 列表刷新见新卡（**409 冲突分支由单测覆盖**——MSW 与真实后端对重码均为 upsert 200，现场演示走成功路径）
- 卡片「详情」→ 右抽屉基本信息 + revision 时间线（订单 B 7 节点）

## ③ 切换真实后端

```powershell
# 1. 起全套（db/api/worker/web，本地端口 override）
docker compose -f deploy/docker-compose.dev.yml -f deploy/docker-compose.dev.override.yml up -d --build

# 2. 数据库迁移（compose 内网执行，无需 override）
docker compose -f deploy/docker-compose.dev.yml run --rm --no-deps `
  -e EDP_DATABASE_URL="postgresql+asyncpg://edp_migrator:edp_dev@db:5432/edp" `
  api alembic upgrade head

# 3. 冒烟
curl http://localhost:18000/healthz     # {"status":"ok"}

# 4. web dev 切真实模式（新终端）
cd frontend
Remove-Item Env:VITE_USE_MSW -ErrorAction SilentlyContinue   # 或 $env:VITE_USE_MSW="0"
$env:VITE_API_BASE = "http://localhost:18000"
pnpm --filter web dev
```

**预期**：登录 `manager1 / Admin@123!` 成功（真实 JWT）；总览页各面板降级显示「该面板暂不可用」或「—」为**正常现象**（coverage/health 深检等 M3+ 端点尚缺）——见文末「已知契约缺口」。

## ④ 数据链路：全量 → 增量（缺增量则对账必偏差）

```powershell
# 全量：BASE 60 条（40 订单 + 10 客户 + 10 物料）
make pipeline-full
# 期望输出：fetched=60 registered=60 duplicated=0 failed=0

# 增量：DELTA 8 条（5 订单更新 revision→2 + 3 新订单）——T15 评审必记步骤
make pipeline-incr
# 期望输出：fetched=8 registered=8 duplicated=0 failed=0
```

**或经 sync API 触发**（演示服务端异步链路）：

```powershell
# 平台管理员登录拿 token
$TOKEN = (curl.exe -s -X POST http://localhost:18000/api/v1/auth/login `
  -H "Content-Type: application/json" `
  -d '{\"username\":\"admin\",\"password\":\"Admin@123!\"}' | ConvertFrom-Json).access_token

# 触发全量同步 → 202
curl.exe -s -X POST http://localhost:18000/api/v1/admin/adapters/erp/sync `
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" `
  -d '{\"mode\":\"full\"}'
# 期望：{"sync_id":"<uuid>","status":"RUNNING","started_at":"..."}

# 轮询状态至 SUCCEEDED
curl.exe -s http://localhost:18000/api/v1/admin/adapters/erp/status `
  -H "Authorization: Bearer $TOKEN"
# 期望：{"adapter":"erp","mode":"mock","last_sync":{...,"stats":{"fetched":60,"registered":60,...}},"health":"OK"}
```

**幂等彩排**（可选）：再跑一次 `make pipeline-full` → `duplicated=60 registered=0`，库内计数不变。

## ⑤ 对象页真实数据 + 证据篡改检测

前端：真实模式下打开业务对象页 → 60+ 卡片（erp 源 SO-2026-00xxx / C-1xx / M-3xx）。

**篡改演示**（psql 直改一条 snapshot → verify 探测 + 审计告警）：

```powershell
# 1. 取一条证据 ID（管理员 token；也可 psql 查）
$EID = (curl.exe -s "http://localhost:18000/api/v1/evidence?limit=1" `
  -H "Authorization: Bearer $TOKEN" | ConvertFrom-Json).items[0].evidence_id

# 2. 篡改前 verify：valid=true
curl.exe -s "http://localhost:18000/api/v1/evidence/$EID/verify" -H "Authorization: Bearer $TOKEN"
# 期望：{"evidence_id":"...","valid":true,"verified_at":"..."}

# 3. psql 进容器篡改 snapshot（绕过应用层，模拟存储层篡改）
docker compose -f deploy/docker-compose.dev.yml -f deploy/docker-compose.dev.override.yml exec db `
  psql -U edp_migrator -d edp -c `
  "UPDATE evidence.records SET snapshot = snapshot || '{\"tampered\": true}'::jsonb WHERE evidence_id = '$EID';"
# 期望：UPDATE 1

# 4. 再 verify：valid=false（checksum 重算不一致）
curl.exe -s "http://localhost:18000/api/v1/evidence/$EID/verify" -H "Authorization: Bearer $TOKEN"
# 期望：{"evidence_id":"...","valid":false,"verified_at":"..."}

# 5. 审计出现 P1 告警行
curl.exe -s "http://localhost:18000/api/v1/audit-logs?action=EVIDENCE_VERIFY_FAILED&limit=3" `
  -H "Authorization: Bearer $TOKEN"
# 期望：items[0].action = "EVIDENCE_VERIFY_FAILED"，detail.risk = "P1"，resource_id = $EID
```

## ⑥ 租户生命周期（curl 序列）

```powershell
# 1. 开通 acme 租户（平台 admin token）→ 201 + 一次性临时口令
curl.exe -s -X POST http://localhost:18000/api/v1/tenants `
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" `
  -d '{\"slug\":\"acme\",\"name\":\"Acme 试点\",\"plan\":\"TRIAL\",\"admin\":{\"username\":\"acme-admin\",\"email\":\"admin@acme.io\",\"display_name\":\"Acme 管理员\"}}'
# 期望 201：{"tenant_id":"<TID>","slug":"acme","status":"ACTIVE","temporary_password":"<TMP>",...}

# 2. acme 管理员登录（tenant_slug 必填）
$ACME = (curl.exe -s -X POST http://localhost:18000/api/v1/auth/login `
  -H "Content-Type: application/json" `
  -d '{\"username\":\"acme-admin\",\"password\":\"<TMP>\",\"tenant_slug\":\"acme\"}' | ConvertFrom-Json).access_token
curl.exe -s http://localhost:18000/api/v1/objects -H "Authorization: Bearer $ACME"
# 期望 200：{"items":[],...}（新租户空数据，RLS 与 default 完全隔离）

# 3. 暂停 → 业务 API 即时 403
curl.exe -s -X POST http://localhost:18000/api/v1/tenants/<TID>/suspend -H "Authorization: Bearer $TOKEN"
# 期望 202：{"tenant_id":"...","status":"SUSPENDED","operation":"suspend",...}
curl.exe -s http://localhost:18000/api/v1/objects -H "Authorization: Bearer $ACME"
# 期望 403：error.code = "TENANT_SUSPENDED"

# 4. 恢复 → 复通
curl.exe -s -X POST http://localhost:18000/api/v1/tenants/<TID>/resume -H "Authorization: Bearer $TOKEN"
# 期望 202：status="ACTIVE"；同 acme GET /objects → 200

# 5. 注销强确认：缺 confirm → 400；确认 → 202 CANCELLED
curl.exe -s -X POST http://localhost:18000/api/v1/tenants/<TID>/cancel `
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" `
  -d '{\"confirm\":false,\"reason\":\"试点结束\"}'
# 期望 400：error.code = "VALIDATION_ERROR"（B.0 权威映射，非 422）
curl.exe -s -X POST http://localhost:18000/api/v1/tenants/<TID>/cancel `
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" `
  -d '{\"confirm\":true,\"reason\":\"试点结束\"}'
# 期望 202：status="CANCELLED"；GET /tenants/<TID> → cancel_scheduled_at 非空（now+30d）
```

## ⑦ 对账收尾（必须在 ④ 含增量之后）

```powershell
make reconcile
```

**期望输出**（full+incr 后源-库三计数齐等）：

```
source_system  object_type  source  objects  events  evidence  ok
erp            CUSTOMER     10      10       10      10        True
erp            MATERIAL     10      10       10      10        True
erp            ORDER        48      43       48      48        True
偏差行数 0 / 共 3 行
```

（ORDER：40 BASE + 8 DELTA 记录 = 48 事件/证据，实体对象 43——5 条更新复用同一对象，revision→2。）

---

## 已知契约缺口（W3 版；真实后端 vs MSW，后续里程碑对齐）

> W3 契约冻结随本清单更新（35 路径，指纹前 8 位 `f5ee32a8`）。原 M2 条目按 W3 实现修订：原「mode:"replay" → 422」已由 T13 闭环，替换为 W3-19；编号 W3-nn 供 T20 台账引用。**T20 收口补记 19 条（W3-23~41：T14~T19 评审遗留）——本清单为 W3 终稿。**

**契约形态**

1. **W3-01 adapters 清单列**（W4 EDP-402）：后端 `GET /admin/adapters` 仅 `adapter/mode/status/health/last_sync_at`（W3 起为 erp/erp-demo/plm-demo 三行）；MSW `AdapterSummary` 另有 `access/team/health_pct/isolation` 演示列且为 6 适配器全集，时间字段命名 `last_sync` ≠ `last_sync_at`——适配器页面化时对齐（响应 envelope 缺 `next_cursor` 见 W3-24）。
2. **W3-02 GET /objects 无 total**：真实后端分页响应只有 `items/next_cursor`（B.0 契约）；`total` 为 MSW mock 扩展。W3 起 `core.pagination.Page` 已增可选 `total`，但**仅 events 填充**（EDP-301 分页文案），objects 等其余端点仍缺省——对象页总数文案真实模式显示「—」。
3. **W3-03 cancel 缺 confirm = 400**：`VALIDATION_ERROR` 经 B.0 权威映射返回 400（OpenAPI 声明 422 为 FastAPI 默认），非 422。
4. **W3-04 MSW-only 端点**：`GET /audit-logs/{audit_id}`（审计详情）与 `POST /admin/evidence/reindex`（重索引）后端未实现——分别待 W4/W5 页面化时落地。
5. **W3-05 全路由 405/404 统一 envelope（行为变更，已获认可）**：T8 为 tools 补 `StarletteHTTPException` 处理器后，**所有路由**的框架 404/405 由 FastAPI 默认 `{"detail": ...}` 变为统一 `ErrorEnvelope`（`METHOD_NOT_ALLOWED` / `NOT_FOUND`）；消费方若解析 `detail` 需改用 `error.code/message`。
6. **W3-06 非 events 列表端点省略 null 字段**：`response_model_exclude_none` 下，audit/evidence/objects/tenants/decisions/health 等响应中值为 null 的可选字段（含 `next_cursor`）不出现；MSW fixtures 常显式给 `next_cursor: null`——前端按可选处理。
7. **W3-07 orders 列表 envelope 形态**：B.8 原文「同上述结构数组」（裸数组），实现为 `{"items": [...], "next_cursor": null}` envelope（`OrderListResponse`）——与采购/B.0 分页形态一致，B.8 示例待文档化收口。
8. **W3-08 采购 next_cursor 恒 null**：`GET /tools/purchase-orders` 本轮不实现游标分页（固定 `next_cursor: null`，`limit` 生效）——后续补游标（对齐 events 锚 `{o,i}` 模式）。

**语义与审计**

9. **W3-09 exceptions status 语义**：真实后端 `OPEN` = 无「已 DECIDED 案例」关联（`decision.cases.source_id = event_id`）、`RESOLVED` = 有；MSW 约定为固定事件（`EVT_ORDER_I_DQ`）标 RESOLVED——页面文案与演示脚本按真实语义表述。
10. **W3-10 exceptions 含 P3**：真实条件仅 `risk_level IS NOT NULL`，seed 后 10 条（含 P3×2）；MSW `data/ebms.ts` 8 条（不含 P3）——列表数量差异非缺陷，severity 过滤可对齐。
11. **W3-11 result_type 可空**：`event.events.result_type` 列可空，响应保留 `result_type: null` 可能（seed 恒有值）；MSW 类型为非空——前端渲染需兜底。
12. **W3-12 展示型事件不迁入 seed**：真实数据为 `{TYPE}_SNAPSHOT` + `capability.result.*` / `adapter.sync.failed`；MSW 的 `order.created` 等展示型事件类型不迁入（避免双轨）。
13. **W3-13 审计 resource_type 裸名歧义**：审计切面 `resource_type` 写**裸表名**（`records`/`cases`/`events`/`business_objects`），MSW 写全名（`evidence.records`/`decision.cases`/`registry.objects`）；`evidence.records` 与 `decision.records` 裸名同为 `records`，靠 action 前缀（`EVIDENCE_*` / `DECISION_*` / `CASE_*`）消歧——审计页筛选/展示需按 action 前缀或映射表处理。
14. **W3-14 CASE_CREATE vs MSW CASE_CREATED**：真实 action 为 `CASE_CREATE`（切面 `{PREFIX}_{VERB}` 命名），MSW 为 `CASE_CREATED`——审计页动作文案映射时对齐。

**health / KPI（T12/T13）**

15. **W3-15 db_ha 仅 deep=true**：`GET /health` 非 deep 响应不含 `db_ha`（`response_model_exclude_none`），MSW 恒返回；`?deep=true` 需 `audit:read`（ADMIN 角色集）。另 MSW `replication_lag_mb: 0.4` 为演示值，真实开发库恒 0（无副本）。
16. **W3-16 last_sync 键为 erp-demo/plm-demo**：真实 `last_sync` 按已同步适配器命名（seed 后为 `erp-demo`/`plm-demo`）；MSW 为 `erp/mes/plm/mdm/crm` 演示全集——总览页适配器健康卡需容忍键差异。
17. **W3-17 归档命中不计入 idempotency_hit_rate**：`Idempotency-Key` 重放（`deduplicated=true` 存档响应）不累加 `events_duplicated`，故不计入命中率；口径为近 24h `events_duplicated/(events_in+events_duplicated)` 日粒度近似。
18. **W3-18 P95 口径**：`ingest_latency_ms` 为「函数入口 → INSERT 前」处理耗时（不含 DB 提交/出站），seed 回填 60~299ms 确定性值；`p95_latency_ms` 取近 24h `percentile_cont(0.95)`。
19. **W3-19 非法 mode 400（非 422）**：`POST /admin/adapters/{name}/sync` 非法 `mode` 由服务层校验返回 400 `VALIDATION_ERROR`（计划原写 422）；`mode:"replay"` 已支持（T13），`since` 仅 replay 消费。

**演示数据（T5）**

20. **W3-20 tools 数据与 B.8 示例差异**：演示数据集以 MSW fixtures 与场景故事线为准，与设计 B.8 示例存在三处有意偏差：① `X-100` 库存 WH-01=0/0（场景 2 缺口来源）、WH-02=3200/800，B.8 示例为 WH-01=3200/800；② `SO-2026-00123` 行合计（P-F×500×240 + X-100×1000×12.5 = 132500）≠ 头金额 120000（fixtures 原值）；③ `S-021` 除 X-100=10 天外另有 Y-200=7 天交期（fixtures 补齐，B.8 仅示例 X-100）。
21. **W3-21 回流事件 10 条口径**：spec §3.2 写「8 条能力结果 + adapter.sync.failed」、计划 T5 标题写 9 条，实际 **10 条**（对齐 MSW events fixtures：A P3/B P1/C P2/H P0/J P1/E P1/G P3/PRJ-D P2/I P2/adapter P2）——以实际常量为准。
22. **W3-22 业务日期固定**：快照段 `order_date`/`delivery_date` 等业务日期为 fixtures 固定字面量（如 2026-09-15），仅 `occurred_at` 随 seed 锚平移——跨锚重放业务日期不随动（演示可接受，真实适配器由源系统提供）。

**后端与契约（T14 评审补记）**

23. **W3-23 cases 缺 (tenant_id, source_id) 索引**（性能，W4）：`decision.cases` 仅有 `idx_cases_status`；EBMS exceptions 的 case 关联 join 与 seed 幂等查询（`find_case_by_source`）均按 `(tenant_id, source_id)` 过滤走顺序扫描。W4 补索引；同事件多案例时 join 行倍增的收口（唯一约束或标量子查询）一并处理。
24. **W3-24 adapters 清单无 next_cursor**：`GET /admin/adapters` 响应仅 `{items}`（`AdapterListResponse`），无 B.0 分页的 `next_cursor`；MSW 以 `Page` 包裹（含 `next_cursor: null`/`total`）——适配器页面化（W4 EDP-402）时补齐分页形态或前端按可选处理。
25. **W3-25 ebms exceptions 的 total 例外**：路由以 `response_model_exclude={"total"}` 剔除 `Page.total`（B.9 形状 items+next_cursor），但 OpenAPI schema `Page_ExceptionItem_` 仍声明可选 `total`——契约「声明存在、响应恒缺」，消费方不得依赖该字段。

**前端事件流页（T15~T17 评审补记）**

26. **W3-26 cursor.ts 注释过时**：`mocks/lib/cursor.ts` 的 `PageResult` 注释仍称「冻结契约 Page envelope 无 total」——T14 契约已含可选 `total`（仅 events 填充），注释待更新（代码行为无需改）。
27. **W3-27 Page.total mock 必填 vs 契约可选**：MSW `Page.total: number` 必填（全部 mock 列表恒填充），真实契约 `total` 可选且仅 events 填充；前端类型以 mock 为准，真实模式其余页需按可选处理（events 页已降级，其余页接真端点时对齐）。
28. **W3-28 总览证据有效率真模式 0%**：真实 `/health` `ops_metrics` 无 `evidence_valid_rate`（MSW 为 100），`BottomThree` 环形与数值以 `?? 0` 兜底 → 真实模式渲染 0%（既有降级；待后端补字段或前端改「—」）。
29. **W3-29 事件描述列空值率高**：SNAPSHOT 事件 `data` 无 `summary/reason/note` → 描述列回退「—」（seed 50 条中 40 条快照事件为空，实测 `ORDER_SNAPSHOT` data 仅 `{"via":"pipeline"}`）；W4/seed 补 summary 后改善。
30. **W3-30 类型字典缺例行事件类型**：`EVENT_TYPE_LABELS` 仅覆盖 `capability.result.*`/`adapter.sync.failed`/`*_SNAPSHOT`；MSW 例行类型 `order.created/updated/confirmed/delivery_date_changed`、`inventory.changed`、`decision.case_created` 未入字典（回退原值 + muted）——与 W3-12「展示型事件不迁入 seed」策略一并决定是否补录。
31. **W3-31 短 ID 截取位跨页不统一**：事件流页（表格/抽屉/向导）取尾 8（`slice(-8)`，T18 修复），总览 `EventsTimeline` 与 `RiskDrawer` 仍取头 8（`slice(0, 8)`）——同一事件两处展示的短 ID 不同，后续统一为尾 8。
32. **W3-32 分页总数无千分位**：`CursorPagination` 直出 `共 {total} 条`（如 `18421`），原型为 `18,421`；web 已有 `fmt()` 千分位工具但 shared 组件未使用——后续统一。
33. **W3-33 spec §7.1「原型无搜索框」表述有误**：原型 `事件流.html` 实有 `data-dom-id="event-search"` 搜索框；本轮不设搜索的真实原因是 `q` 契约参数未定（「原型无」不成立），spec 修订时更正。
34. **W3-34 回放向导步骤 3 未回显开始时间**：步骤 2 选择的 `since` 在步骤 3 摘要仅回显适配器与回放模式——补「开始时间」行（未填显示「未设置」）。
35. **W3-35 空态「清空筛选」死路**：列表为空且未设任何筛选（如 24H 窗口无事件）时，空态主按钮「清空筛选」无实际效果（仍为空态）——需按有无筛选切换按钮语义（如「扩大时间范围」）。
36. **W3-36 证据加载失败与空态同呈现**：详情抽屉证据区在查询失败时也显示「无关联证据」（无 `isError` 分支）——需区分错误态与真空态。
37. **W3-37 useAdapterOptions 预取**：`ReplayWizard` 常驻挂载，向导未打开即请求适配器清单（`useAdapterOptions` 在组件体调用）——可改 `enabled` 门控到打开/步骤 2 再请求。

**演示与冒烟（T18/T19 评审补记）**

38. **W3-38 浏览器级真 API 冒烟待彩排**：T18/T19 在无头环境仅完成 API 级冒烟（`Invoke-RestMethod` 复刻前端调用序列）；浏览器级（KPI/翻页/抽屉/向导/适配器页）按 `m3-demo.md` 文末 5 步清单留待演示彩排人工执行。
39. **W3-39 compose 镜像需 `--build` 重建**：18000/9080 旧镜像不含 W3 契约（`/health` 404、events 无 `total`、web 无事件流页）；演示前必须 `docker compose ... up -d --build`（已写入 `m3-demo.md` 环境前置）。
40. **W3-40 冒烟数值依赖 seed 锚与重放历史**：事件时间/`ingest_latency_ms`/`event_id`/`case_id` 随锚变化；`idempotency_hit_rate` 随重放历史（RESET 首跑 0.0 → 二跑 ≈0.44 → replay 后 ≈0.60）——演示前 `make seed-demo RESET=1`，读数口径见 `m3-demo.md`「读数说明」。
41. **W3-41 `_jobs` 私有接缝**：`adapters_admin/service.py` 以模块级 `_jobs` dict 存任务状态（M2 单副本语义），`/status` 轮询必须命中同一进程、重启即失——跨进程/多副本需外置任务状态（W4+）。
42. **W3-42 `_jobs` 未按租户分键（跨租户可见性）**：`_jobs` 以适配器名为 key（`adapters_admin/service.py`），任意租户持 `adapters:read` 的用户经 `GET /{name}/status` 可读到他租户触发的 `sync_id/stats/error`，且不同租户触发会互相覆盖——终审补记，W4 外置任务状态时按 `(tenant_id, adapter)` 分键。

**W3 补齐轮（W3R，2026-09-17）**

43. **W3R-01 限流为单副本语义**：`tenantmgmt/ratelimit.py` 令牌桶为进程内 per-tenant，多副本部署实际速率 ≈ limit×副本数；网关侧全局样例见 `deploy/nginx-limit-req.conf.example`，租户维度归应用层（需鉴权后信息，nginx 无法分键）——多副本前需外置（Redis）或由网关按租户头限流（W4+）。
44. **W3R-02 `api_calls` 计量改独立短会话（spec 偏差）**：原 spec 为「同请求事务（失败不计入）」，实现改独立会话立即提交——原因是 usage 行 upsert 持锁至请求结束，并发请求在同租户 usage 行上串行互等（并发用例放大为死锁）；语义随之变为「全部请求（含失败）」。
45. **W3R-03 80% 水位告警动作词表外扩展**：限流审计 `action=RATE_LIMITED` / `RATE_LIMIT_WARNING`（B.6 动作词表未列）——审计页（EDP-401）过滤字典需并入。
46. **W3R-04 B.14 usage 最小版仅平台 ADMIN**：`GET /tenants/{id}/usage` 未开放「租户内 ADMIN 查本租户」（B.14 原文）；W5 租户页按需补租户轨道。
47. **W3R-05 usage 含 `events_duplicated` 超集字段**：B.14 未列（W3-M3 计量列）；SDK 消费方按可选处理。
48. **W3R-06 产能数据暂无消费面**：`delivery.capacity` 已投影（mes-demo），但 tools 六接口不含产能查询——ProductReadiness 真实接入（EDP-017 完整版）时按需加工具或能力直读。
49. **W3R-07 B.10 无顶层 `error` 字段**：trace.traces DDL 有 `error JSONB`，B.10 请求体未定义——失败轨迹错误只能进 `tool_calls.error`/`output_structured`；补契约时同步详情投影。
50. **W3R-08 跨租户 trace_id 撞主键 409**：trace_id 为全局主键（客户端 UUID），他租户同 id 重发 → 409（不泄露内容但暴露存在性）——UUIDv4 碰撞概率可忽略，留痕。
51. **W3R-09 `evidence?q` 为契约扩展**：B.4 未列 `q`（证据库页卡内搜索真源）；LIKE 通配符按字面转义。
52. **W3R-10 平台级路由不计量/不限流**：`/auth/*`、`/tenants` 平台管理、`/healthz` 不挂 tenant_scoped——api_calls/限流只覆盖租户域（设计 3.5 语义；平台运营路由的滥用防护归网关/W4+）。
53. **W3R-11 MES 单测并入既有文件**：计划命名 `tests/unit/test_mes_mock.py`，实现并入 `test_demo_adapters.py`（覆盖等价：确定性/过滤/兜底/合并全量），留痕。
54. **W3R-12 Memory 评审流转仅最小版**：`PATCH /memories/{id}/review`（Human-Only）已交付，候选→知识库的完整流转与中枢界面接管归 W6（设计 A.7 注明）。
55. **W3R-13 证据状态 pill=本会话校验语义**：证据库列表契约无状态字段，卡片状态 pill 来自用户本会话 verify 结果（未校验为中性、刷新即失）——非持久化校验状态。
56. **W3R-14 `/admin/outbox/status` 未实现**：系统健康页 Outbox 卡以 `/health` 的 `outbox_pending`/`dlq` 字段近似（pending/死信计数）；细粒度 outbox 状态端点（oldest_pending/published_last_hour 等）后端未实现，MSW 为 mock 扩展。
57. **W3R-15 429 未逐端点声明**：租户域端点运行时可返回 429 `RATE_LIMITED` + `Retry-After` 头（EDP-025 应用层限流），冻结契约（W3 35 路径）未逐端点声明 429——SDK/前端按可选处理，W4 契约窗口评估补声明。

> Minor 备忘：`memories.reviewed_by` / `decisions.decided_by` 落 user UUID（B.11 示例为用户名）——SDK 消费方按 UUID 口径处理。

**W4 闭环集成轮（W4，2026-09-18；初稿——波 1 后端 T1~T8 契约冻结实测，53 路径，指纹前 8 位 `687b6cd7`；波 2 T13/T15 续记终稿）**

58. **W4-01 闭环 steps 无逐转移史**：case detail 的 `steps[]` 中每个行动仅两个节点（创建 + 当前状态快照），无逐转移明细——转移历史经审计页按 `ACTION_UPDATE`（resource_id=action_id）查询；后续按需补 `action_transitions` 历史表（最小版留痕）。
59. **W4-02 steps 的 ACTION 快照 human_only 语义**：快照节点 `human_only` =「当前 status 的**下一转移**是否存在 Human-Only 边」（仅 APPROVED/COMPLETED 为 true，对应 EXECUTING/VERIFIED 两条边），**非**「到达该状态的边」——前端应按「待人工动作」渲染（人形图标 + tooltip），而非「该步为人工完成」。
60. **W4-03 进程内单副本语义三处同类**：adapters `_jobs`（W3-41/42）、限流令牌桶（W3R-01）、审计策略缓存（W4 新增 `audit_policies/service.py` 进程内 `dict[tenant_id, list]`，模块内写路径失效）均为进程内单副本——多副本部署前需外置，W5+ 评估 Redis。
61. **W4-04 policy_hits 仅覆盖切面 ORM 写路径**：审计策略命中打标挂在 `audit/aspect.py` 切面（ORM flush 路径）上；`record_explicit` 显式补点的审计行（GUARD_DENIED/EVIDENCE_VERIFY_FAILED/ACTION 状态转移拒绝等独立会话审计）**不参与** policy_hits 匹配——策略命中统计按此口径读。
62. **W4-05 recent_changes_summary 为派生文案**：`GET /ebms/reports/summary` 的 `recent_changes_summary` 按风险事件动态拼装（`"订单 {order_no} {summary}"`，B.9 示例风格），非常量文案——内容随 seed/事件数据变化，前端按动态列表渲染。
63. **W4-06 B.9 网关复用路径未实现**：B.9 列出的 `/ebms/decisions/{case_id}`、`/ebms/evidence/{id}`（EBMS 前端复用网关路径）未实现——消费方直接复用 B.5/B.4 既有路径（`/decisions/cases/{id}`、`/evidence/{id}`）；按消费方需要再落地。
64. **W4-07 适配器日志抽屉仅最近一次 sync**：`GET /admin/adapters/{name}/status` 只保留最近一次 sync 的 status/stats（`_jobs` 覆盖语义）；适配器页日志抽屉按单次呈现，完整任务日志 W5（EDP-030）。
65. **W4-08 test_adapters_api._set_demo_anchor 对 NULL attributes 静默无效**：`_set_demo_anchor` 用 `jsonb_set(attributes, ...)` 更新 seed 锚，当行 `attributes IS NULL` 时 jsonb_set 返回 NULL、更新静默无效（既有测试基建缺陷，当前 seed 行恒有 attributes 故未触发）——建议改 `jsonb_set(coalesce(attributes,'{}'), ...)`；本轮契约冻结不动他人测试，留待后续。
66. **W4-09 tools 组 429 已逐端点声明，其余租户域仍缺**：本轮契约冻结 tools 组 7 端点统一补 429 `RATE_LIMITED` 声明（B.8 明文统一行为，经 `error_responses` 仅影响 OpenAPI 文档、不改运行时）；其余租户域端点运行时可 429 但未逐端点声明（沿 W3R-15 口径）——SDK/前端按可选处理。
67. **W4-10 决策记录不自动落 DECISION 证据**：`POST /decisions/cases/{id}/records` 只写 decision.records + 案例置 DECIDED，不自动创建 `ref_type=DECISION` 证据——案例详情 `evidence_chain` 的 DECISION 层需消费方补建（M4 演示脚本 ④ 与 `test_m4_acceptance` 均按「决策意见落证最小补建」口径先 `POST /evidence` 再读链）；后续在 submit_record 内同事务落证收口。
68. **W4-11 Action 状态转移 PATCH 双轨（有意超 B.5「仅 JWT」口径）**：`PATCH /actions/{id}/status` 实现为 JWT `action:execute` / API Key `write:action` 双轨——SERVICE Key 可执行**非 Human-Only** 转移（如 ACCEPTED→APPROVED），Human-Only 两转移（APPROVED→EXECUTING、COMPLETED→VERIFIED）仍仅 HUMAN（Guard + 独立会话审计完好）。设计文档 B.5 原文为「仅 JWT」，此为有意超集（演示中中枢可推进非 HITL 步骤）；W4 spec §3 表已同步口径。若需回退 JWT-only 需连带 `test_actions_api`/`test_m4_acceptance` 断言。
69. **W4-12 人工操作者标识为 user UUID 口径**：`action.actions.verified_by`、`memory.memories.reviewed_by`、`decision.records.decided_by` 均落 principal.id（UUID），B.5/B.11 示例为用户名（"manager1"）——SDK/前端按 UUID 缩写展示（m4-demo.md 已留痕，此处收编为正式条目）。
70. **W4-13 显式审计 resource_type 统一 fullname**：ACTION_UPDATE 显式补点原写裸名 `actions`，本轮统一为 `action.actions`（与 GUARD_DENIED 一致）；`audit.policies` 切面前缀由裸表名回退 `POLICIES_{VERB}` 修正为 `POLICY_{VERB}`（aspect ACTION_PREFIXES 补映射，前端词表同步）。

**W5 平台运营与质量轮（W5，2026-09-21；初稿——波 1 后端 T1~T9 契约冻结实测，65 路径，指纹前 8 位 `4b576ee5`；波 2 T13/T15 续记终稿）**

71. **W5-01 usage 双轨取 /tenants/current/usage 新路径**：B.14「租户内 ADMIN 查本租户使用量」经新路径 `GET /tenants/current/usage` 落地（W3R-04 收口）——复用平台面 `query_usage`（`GET /tenants/{id}/usage` 平台面契约不变）；`require_tenant_admin` 下 MANAGER 及以下 403。B.14 原文路径语义按此双轨口径消费（平台面照旧、租户面走 current）。
72. **W5-02 context token 经响应体返回**：`POST /tenants/{id}/context` 切换成功后重签 access token（claims 附加 `act_tenant`，复用既有签发参数与过期语义）**经响应体 `access_token` 字段返回**——B.14 未定义 token 交付通道，此为最小可行口径；前端持有后替换本地凭据、全站缓存清空重拉（设计 13.8，T10 对接），后续业务请求由 tenant_scoped 按 act_tenant 优先解析（SUSPENDED 目标复用状态墙即时拦截）。
73. **W5-03 quality reports 实时计算无预聚合**：`GET /admin/quality/reports` 四段聚合（对账/覆盖率/孤儿/checksum 抽检）+ kpi/dimensions **恒实时计算**——`date` 参数接受并原样回显（缺省=请求日），**不回溯**（传历史 date 不产生历史快照，仅回显）；预聚合/物化 W6。另 reconciliation 行 `source_count` 可空（None = real/无水位降级：deviation_pct=0.0、ok=true，不计覆盖率分母）——SDK 消费方按可选处理（T3 评审裁定 T9 留痕项）。**W6 闭合（T7/EDP-033）**：压测实测 P95 = 69/77/420 ms（20/50/100 VU，最差 420 ms@100 VU）<2s——条件不触发，预聚合登记不做（读数 `docs/demo/w6-loadtest.md` §1；条件项口径见 W6-04）。
74. **W5-04 异步任务执行互斥单副本**：quality recheck / evidence reindex / adapter sync 三类后台任务**状态落库**（ops.tasks 行级回写、终态幂等）多副本安全；**执行互斥不保证**——多副本并发同租户触发可并行执行（无分布式锁，两行 RUNNING），单副本部署语义可接受（W3-41/W4-03 同类；Redis 外置 T17 评估）。
75. **W5-05 GET /admin/outbox/status 未做**：细粒度 outbox 状态端点（oldest_pending/published_last_hour 等）W5 仍未实现（沿 W3R-14 口径：系统健康页 Outbox 卡以 `/health` 的 `outbox_pending`/`dlq` 近似）——W6 EDP-034 评估。
76. **W5-06 prod 试运行缺口**：M5 可靠性演练（HA switchover/备份任务化/PITR/租户级恢复）以 staging 环境兼任（etcd×1+patroni 双节点、pgbackrest 本地双仓），无独立 prod 试运行——用户批准口径，prod 上线前需补试运行窗口（W6+）。
77. **W5-07 备份验证「连续 3 天」等价口径**：M5 出口的「备份验证连续 3 天」以 `backup-verify.ps1` **连续 N≥3 次全绿**（cron 持续实测，压缩/等待/手动三种调度等价）任务化证据等价——偏差登记、演练报告归档（T15a 落地，非自然日口径）。
78. **W5-08 quality:read 角色集宽于 B.13「ADMIN」原文**：0013 迁移将 `quality:read` 授 PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST（对齐 audit:read 消费面口径）、`quality:run` 授 PLATFORM_ADMIN/ADMIN——B.13 原文仅 ADMIN，读面为有意超集（看板/报告消费宽于触发执行）；quality 面无 SERVICE scope 轨道（readonly API Key 恒 403，dependencies docstring 留痕）。
79. **W5-09 checksum 抽检 ingest 计量副作用**：quality 抽检失配行经 `events.ingest_batch` 落 `quality.checksum_failed` 事件（UUIDv5 幂等：occurred_at 取证据 captured_at，同失配重复抽检恒同 event_id）——复用 ingest 写通道带既有副作用（api_calls 计量/审计/outbox）：质量抽检/对账自身产生租户计量计数（T3 评审裁定接受留痕）；内部来源豁免 W6 评估。
80. **W5-10 evidence↔quality 双向 service 引用**：evidence.service 与 quality.service 互相引用（reindex 复用 quality 的 OpsTask 映射/`wait_task_visible` 公共 helper；quality 复用 evidence 的 `compute_checksum` 单一实现）——模块别名引用（运行时取属性）防部分初始化期名字导入竞态 + docstring 防线，无 import-linter no-cycles 契约（T6 评审裁定接受）；加 no-cycles 契约时重构拆公共模块。

81. **W5-11 平台用户目录端点缺失（邀请成员 mock 扩展）**：租户页「邀请成员」用户下拉在 MSW 走 mock 扩展 `GET /api/v1/admin/users`（真模式 404 → 占位 option「用户目录暂不可用」，邀请功能受限）——后端无平台用户目录端点（B.14 未定义），W6 按需补契约。
82. **W5-12 Bell 消息中心客户端前缀过滤**：最小消息中心取最近 50 条事件客户端过滤 `quality.` 前缀（`GET /events` 的 `event_type` 为精确匹配，契约冻结不改）——`FEED_WINDOW=50` 常量留痕；事件量增长超窗时最旧质量事件静默挤出，后续宜后端前缀过滤入契约（W6 评估）。
83. **W5-13 Agent 三页 capability 清单硬编码**：tools/traces/memory 三页 capability 下拉/chips 为演示 fixture 常量（`CAPABILITY_LABELS` 等三处，label 重复维护）——`GET /capabilities` 契约已存在（W3R 注册中心），W6 接入收敛单点。
84. **W5-14 operator_ticket UI 留痕不下发**：租户注销弹窗的 operator_ticket 字段仅 UI 留痕（B.14 cancel 契约仅 `confirm/reason`），测试锁定请求体形状；B.14 补字段后随契约接入。
85. **W5-15 HAProxy staging 单点**：单写入口 HAProxy 为 staging 单实例（生产需双实例 + keepalived/VIP）；切换窗口单次探测最长 ≈3.6s（含 Windows `docker compose exec` 开销，非纯 DB 延迟）；api 未开 `pool_pre_ping`，极少数持旧连接请求可能报一次错（预期语义，文档标注）。
86. **W5-16 演练记录 JSON 容器供给（终审 I-1 闭环）**：`GET /admin/drills` 默认按 cwd 相对路径读 `deploy/drills/drill-records.json`，而 api 镜像构建上下文为 `backend/`（WORKDIR `/workspace`）不含该文件——终审发现 compose 环境恒空态（健康页备份卡同受「—」影响）；**收口修复：dev/staging compose 的 api 服务补只读挂载 + `EDP_DRILLS_FILE` env（本文件闭环）**。另 T16 演练时 staging api 镜像早于 W5 quality 模块，`--build` 重建后新代码方生效（部署例行事项）。
87. **W5-17 前端全量套件负载 flake 与 Makefile 参数修复**：宿主满载下 registry 页单用例超时偶发（W3/W4 同类）；**W5 收口实测发现原 Makefile `pnpm ... test -- --maxWorkers=2 --testTimeout=60000` 的 `--` 被 pnpm 原样透传给 vitest 成为「文件过滤器」，参数实际未生效（超时仍 15000ms）**——已改 `pnpm --filter web exec vitest run --maxWorkers=2 --testTimeout=60000` 并复跑全绿（web 231/api-sdk 22/shared 96）。
88. **W5-18 租户页 Minor 三项**：租户切换弹窗副标题「· 生产环境」硬编码（原型 DEMO 行为「测试环境」，宜删或数据驱动）；新建租户弹窗未做原型的配额预览（契约无对应字段，PLAN_QUOTAS 可推导）；租户管理稿权限矩阵表未落地（任务卡未列，后续可选）。
89. **W5-19 备份卡键名语义与 Bell 清零竞态**：健康页备份卡「可恢复性」行取 readings["切换成功率"]（标签与键名语义错位，展示取舍待对齐）；Bell 未读清零用旧 items[0] 推水位（毫秒级竞态，看过仍可能计未读，影响极小）。
90. **W5-20 租户恢复演练断言口径**：T15c api 层断言降为 DB 层等价（tenant-b 成员 JWT 未配置，脚本头/readings 已注）；后续补 tenant-b 凭据配置后恢复 api 层端到端断言。

91. **W5-21 终审 Minor 三项**：adapter sync FAILED 时 stats 置空（quality/evidence 保留已完成段/批进度，语义可辩护，统一留 W6）；switchover `rto_seconds=0` 为 healthz 零中断口径（DB 写面 3.6s 在 readings，前端展示建议加注）；`GET /admin/drills` 用 quality:read（含租户 MANAGER/ANALYST，内容为基础设施元数据、无凭据，低风险）。

**W6 试运行与验收轮（W6，2026-09-22；初稿——波 1 后端 T1~T3 契约冻结实测（T4），68 路径，指纹前 8 位 `d1929b21`；波 2 续记终稿）**

92. **W6-01 试运行 ≥3 天以连续 N≥3 巡检周期等价**：M6 出口「试运行 ≥3 天」以 `trial-patrol.ps1` 连续 N≥3 个巡检周期无 P0/P1 任务化等价收口（W5-07「备份验证连续 3 天」同款口径：任务化 + 日志归档，非自然日）——读数追加 `deploy/logs/trial-run.log`、缺陷分级登记 `docs/demo/w6-trial-run.md`；日历 3 天后续自然累计（spec §10.1 批准口径）。
93. **W6-02 RLS 开销以 DB 层双会话计时为口径**：租户隔离 RLS 性能开销以 DB 层同查询双会话（RLS 绑定会话 vs bypass 会话）计时对比为等价证据——API 层无 bypass 通道（鉴权边界不允许绕过路径），spec §10.2 批准口径；压测报告与 Go/No-Go「接口响应 <2s」读数按此口径呈现。
94. **W6-03 视觉回归 26 稿以双层合计覆盖**：「26 设计稿关键状态」以组件层 11 story（storybook-static 逐 story `toHaveScreenshot`）+ 页面层 18 路由（E2E 真栈逐路由截图基线）合计覆盖，不逐稿建页面 story（工作量与收益不匹配，spec §10.3）；基线快照入库 `e2e/__screenshots__/`，偏差 CI 失败 → `--update-snapshots` 走 PR 评审。
95. **W6-04 预聚合/限流外置（UPSERT）为压测后条件项**：quality reports 预聚合（W5-03）与限流外置 UPSERT（W3R-01 单副本语义）均为条件工作项——压测结论达标（接口 P95 <2s 等）即登记不做，不达标再启动（spec §10.4 闭合口径）；运营报告（T12）以压测 JSON 为数据源。
96. **W6-05 prod 形态仅设计文档**：HAProxy 双实例 + keepalived/VIP 生产形态与 prod 试运行窗口仅落 `docs/prod-deploy-design.md` 设计文档（W5-06 延续），实施留二期——本轮交付不含 prod 环境搭建（spec §10.5）。
97. **W6-06 Redis 不引入**：任务互斥以 PG advisory lock 落地（同 task_type 单执行 + 409 TASK_CONFLICT，多副本安全）；限流令牌桶/审计策略缓存维持进程内单副本语义 + 文档化——Redis 本轮不引入（视压测结论记 W6+ 工作项，spec §10.6）。
98. **W6-07 跨租户用户目录通道未定（T2 评审裁定）**：`GET /admin/users` 挂 require_platform_admin（平台级、无租户绑定）；RLS 下 bind_tenant 到平台管理员**主租户**——目录范围 = 主租户内用户，act_tenant 会话无租户归位语义。跨租户目录候选方案（`?tenant_id` 显式 bind / effective_tenant_id / SECURITY DEFINER）T9 前端对接与 T14 归档时裁定（B.14 未定义平台用户目录，W6 不扩契约）。
99. **W6-08 /admin/users 响应为 Page 信封**：响应为 `Page[AdminUserItem]`（`items/next_cursor/total`，username ASC keyset 游标、user_id tiebreak，display_name 可空透传）——MSW 旧 fixture（W5-11 邀请成员下拉 mock）为**裸数组**，T9 前端接线按 Page 信封适配（MSW 数据形状同步修正）。
100. **W6-09 events 互斥双参 400 VALIDATION_ERROR（非 422）**：`GET /events` 新增 `event_type_prefix`（LIKE prefix% 前缀过滤）与 `event_type` 精确匹配**互斥**，双参同传语义校验返 400 `VALIDATION_ERROR`——B.0 权威映射、仓库惯例（W3-03/W3-19 同款；spec §8 原文 422，按 T1 评审 C1 修正落地）；OpenAPI 沿 events.get 既有 400 声明（W3 起冻结，本轮契约无响应形态变化）。
101. **W6-10 搜索结果行 revision/risk_level/verify 状态契约未含**：T1 search 最小投影有意设计（`5a70ab6` 冻结）——前端降级呈现（updated_at/类型 pill/来源+source_record_id），空态文案自设计稿 21 证据库语境改编（「未找到相关结果/清除搜索」）；如需原字段须契约变更+api-sdk regen，Go/No-Go 裁定留痕。
