# M3 演示脚本（W3 收口版）

> 环境：Windows 宿主 + Docker Desktop。端口走本地 override 映射：db→**15432**、api→**18000**、web→**9080**。
> 种子凭据：`manager1 / Admin@123!`（MANAGER）、`admin / Admin@123!`（平台管理员）。
> 顺序：① 演示数据 → ②~⑥ 后端 API 举证（tools / 405 / 403 / 回流 / replay）→ ⑦ 控制台段。
> **正式演示以 compose 为准**（api 18000 / web 9080）。②~⑥ 也可在无头环境用 venv uvicorn 18001 复现（同一 dev 库）；两种进程不可混用（见 ⑥ 与 ⑦.0）。
> 本文数值为 2026-09-17 实测（`make seed-demo RESET=1` 后按序执行）；读数口径见文末「读数说明」。

---

## 环境与前置

| 依赖 | 命令/说明 |
| --- | --- |
| Docker 服务（正式演示） | `docker compose -f deploy/docker-compose.dev.yml -f deploy/docker-compose.dev.override.yml up -d --build`（db/api/worker/web）。**必须带 `--build`**：旧镜像（W3 前构建）不含 tools/events 扩展/新前端 bundle，会出现 `GET /api/v1/health` 404、events 无 `total`、web 无「事件流」页——重建后 W3 契约才生效 |
| 迁移 | 已迁移（compose api 启动即用）；如需重跑见 `m2-demo.md` ③ |
| 演示数据 | `make seed-demo RESET=1`（重锚重建；幂等口径见 ①） |
| 前端依赖 | `cd frontend && pnpm install`（compose web 容器已内置构建，仅本地 dev 模式需要） |

### 路径与变量约定

- `<repo>` = 仓库根（本机 `D:\wanghuazheng\project\数据平台`）；除注明外命令均从**仓库根**执行。
- `make` 需把 `<repo>\backend\.venv\Scripts` 加入 PATH（该目录含 `uv.exe`，Makefile 以 `uv run` 执行）：

  ```powershell
  $env:PATH = "<repo>\backend\.venv\Scripts;$env:PATH"
  ```

- ②~⑥ 用 `$BASE` 统一指向服务：正式演示 `http://localhost:18000`（compose）；无头冒烟 `http://127.0.0.1:18001`（venv，起法见 ⑦.0）。
- ④ 的临时 Key 插入/清理走 compose `db` 容器 psql（同一 dev 库，对 18001 同样生效）。

---

## ① 演示数据 seed：首跑 / 二跑幂等（EDP-016）

**目的**：把 40 条快照（erp 36 + plm 4，跨适配器依赖序）+ 10 条回流结果事件 + 场景 2 决策案例灌入 default 租户；并验证重放幂等（二跑 0 新增）。

```powershell
make seed-demo RESET=1   # 首跑：复位重建 + 重锚到当前整点
```

实测（首跑）：

```
fetched=40 registered=40 duplicated=0 failed=0 events_accepted=10 events_duplicated=0 case_created=True
```

```powershell
make seed-demo           # 二跑：幂等（全量 duplicated）
```

实测（二跑）：

```
fetched=40 registered=0 duplicated=40 failed=0 events_accepted=0 events_duplicated=10 case_created=False
```

说明：

- **锚**：`RESET=1` 重锚 = 当前时刻截整点（UTC），事件 `occurred_at` = 锚 + 固定偏移。演示前用 `RESET=1`；不带 RESET 的二跑只验幂等、不刷新锚，旧锚会让 24H KPI 滑出窗口。
- 旧库缺 RESULT link 时也必须 `RESET=1`（不带 reset 重跑只会 duplicated）。
- 重建后证据 50 条（40 快照 + 10 结果）；RESULT link 由 `POST /events/batch` 同事务自动落库（events/service.py:311）。

---

## ② tools 六接口（`X-API-Key` + evidence_hint）

**目的**：三大能力经 tools 只读接口联调——六类接口（订单详情/列表、库存、采购、BOM、供应商交期、客户，共 7 条路径）全部 200，且每个对象带 `evidence_hint`（object_id + 该对象最新 `{TYPE}_SNAPSHOT` 事件 id）。

```powershell
$BASE = "http://localhost:18000"                       # 正式演示；无头冒烟改 "http://127.0.0.1:18001"
$KEY = "edp-dev-agent-hub-key"                         # 种子 Key（含 readonly scope）

curl.exe -s "$BASE/api/v1/tools/orders/SO-2026-00123" -H "X-API-Key: $KEY"          # 订单详情
curl.exe -s "$BASE/api/v1/tools/orders?customer=C-008" -H "X-API-Key: $KEY"         # 订单列表
curl.exe -s "$BASE/api/v1/tools/inventory?material_code=X-100" -H "X-API-Key: $KEY" # 库存
curl.exe -s "$BASE/api/v1/tools/purchase-orders?material_code=X-100" -H "X-API-Key: $KEY"
curl.exe -s "$BASE/api/v1/tools/bom?product_code=P-F" -H "X-API-Key: $KEY"          # BOM
curl.exe -s "$BASE/api/v1/tools/supplier-lead-times?supplier_code=S-021" -H "X-API-Key: $KEY"
curl.exe -s "$BASE/api/v1/tools/customers/C-008" -H "X-API-Key: $KEY"               # 客户
```

预期输出摘要（实测）：

| 接口 | 200 摘要 |
| --- | --- |
| orders/SO-2026-00123 | `customer={C-008,某客户,VIP}`、`amount=120000.0`、`lines=[P-F×500, X-100×1000]` |
| orders?customer=C-008 | `items=2`（SO-2026-00123、SO-2026-00128）、`next_cursor=null` |
| inventory?material_code=X-100 | `warehouses=2`（WH-01 available=0 / WH-02=3200）、`total_available=3200.0` |
| purchase-orders?material_code=X-100 | `items=1`（PO-2026-00771，S-021，2000 件，在途） |
| bom?product_code=P-F | `bom_version=V3`、`items={X-100:2.5, Y-200:1.0}` |
| supplier-lead-times?supplier_code=S-021 | `lead_times={X-100:10, Y-200:7}` |
| customers/C-008 | `name=某客户`、`level=VIP` |

- 每个对象响应含 `evidence_hint={"object_id":"<uuid>","event_id":"<uuid>"}`；`event_id` 为该对象最新快照事件（实测与 `event.events` 直查一致）。
- 列表接口（orders / purchase-orders）为 `{items, next_cursor}` envelope，`evidence_hint` 在每行内。
- 分层：对象不存在 → 404（不泄露存在性）；对象存在但无数据 → 200 空数组 + `evidence_hint.event_id=null`。

---

## ③ 405 举证（非 GET → 统一 envelope）

**目的**：Read-Only 第①层（应用层）——tools 路由仅注册 GET，非 GET 由统一处理器收敛为 405 envelope（路由先于鉴权：无凭据同样 405）。

```powershell
curl.exe -s -i -X POST "$BASE/api/v1/tools/orders/SO-2026-00123" -H "Content-Type: application/json" -d "{}"
```

实测：

```
HTTP/1.1 405 Method Not Allowed
allow: GET
{"error":{"code":"METHOD_NOT_ALLOWED","message":"方法不允许","request_id":"<uuid>"}}
```

PUT/DELETE/PATCH 同结论；405 为全路由行为（`/healthz` 亦收敛为同一 envelope）。

---

## ④ 403 + GUARD_DENIED 审计举证

**目的**：Read-Only 第③层（审计层）——SERVICE Key 缺 `readonly` scope → 403，且拒绝**先**落 `GUARD_DENIED` 审计行（resource_type=tools，含 path/reason/scopes）。

```powershell
# 1. 造临时 Key：只有 write:event、无 readonly（hash 与生产同实现）
$HASH = & "<repo>\backend\.venv\Scripts\python.exe" -c "from edp_api.core.security.apikey import hash_key; print(hash_key('demo-no-readonly-key'))"
docker compose -f deploy/docker-compose.dev.yml -f deploy/docker-compose.dev.override.yml exec db `
  psql -U edp_migrator -d edp -c "INSERT INTO platform.api_keys (key_id, key_hash, tenant_id, principal_type, principal_id, scopes, status) SELECT gen_random_uuid(), '$HASH', tenant_id, 'SERVICE', 'demo-no-readonly', ARRAY['write:event'], 'ACTIVE' FROM platform.tenants WHERE slug='default';"

# 2. 该 Key 调 tools → 403
curl.exe -s -i "$BASE/api/v1/tools/orders/SO-2026-00123" -H "X-API-Key: demo-no-readonly"

# 3. 审计举证（admin JWT）
$ADMIN = (curl.exe -s -X POST "$BASE/api/v1/auth/login" -H "Content-Type: application/json" `
  -d '{\"username\":\"admin\",\"password\":\"Admin@123!\"}' | ConvertFrom-Json).access_token
curl.exe -s "$BASE/api/v1/audit-logs?action=GUARD_DENIED&resource_type=tools&limit=5" `
  -H "Authorization: Bearer $ADMIN"

# 4. 清理临时 Key 与审计行（演示后可重复执行）
docker compose -f deploy/docker-compose.dev.yml -f deploy/docker-compose.dev.override.yml exec db `
  psql -U edp_migrator -d edp -c "DELETE FROM platform.api_keys WHERE principal_id='demo-no-readonly'; DELETE FROM platform.audit_logs WHERE actor_id='demo-no-readonly';"
```

实测：

- 403 body：`{"error":{"code":"FORBIDDEN","message":"缺少 scope：readonly","request_id":"<uuid>"}}`
- 审计命中 1 行：`action=GUARD_DENIED`、`actor_id=demo-no-readonly`、`resource_type=tools`、`detail={"path":"/api/v1/tools/orders/SO-2026-00123","reason":"缺少 scope：readonly","scopes":["write:event"]}`。
- 对照：种子 Key（含 readonly）同路径 200（对象存在）——403 由 scope 缺失而非路由/租户。

---

## ⑤ 回流 → EBMS exceptions（P1 含 case_id）

**目的**：回流结果事件（`risk_level`/`result_type`）可经 EBMS 查询；场景 2（SO-2026-00123）关联 seed 决策案例（`case_id` 非空）。

```powershell
curl.exe -s "$BASE/api/v1/ebms/exceptions?severity=P1" -H "X-API-Key: $KEY"
```

实测：

- `items=3`：`SO-2026-00123`（场景 2）/ `SO-2026-00126`（场景 5）/ `SO-2026-00131`（场景 9），全部 `risk_level=P1`。
- 场景 2 行 `case_id=<seed 案例 uuid>`（= `decision.cases` 中 seed 创建的唯一案例）、`summary=物料X缺口1000，预计延误5天`；其余两条 `case_id=null`。
- 偏差留痕：真实条件为 `risk_level IS NOT NULL`，故 P3（场景 1/6）也在默认列表中——`severity` 过滤可对齐（见 `m2-demo.md` W3-10）。

---

## ⑥ replay 202 → status duplicated==fetched

**目的**：演示数据可重放（EDP-016）——`mode=replay` 全量重放已入库记录，UUIDv5 幂等 → 全 duplicated、不推 revision。

```powershell
$ADMIN = (curl.exe -s -X POST "$BASE/api/v1/auth/login" -H "Content-Type: application/json" `
  -d '{\"username\":\"admin\",\"password\":\"Admin@123!\"}' | ConvertFrom-Json).access_token

# 1. 下发 replay → 202
curl.exe -s -X POST "$BASE/api/v1/admin/adapters/erp-demo/sync" `
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" -d '{\"mode\":\"replay\"}'

# 2. 轮询状态（同进程！）
curl.exe -s "$BASE/api/v1/admin/adapters/erp-demo/status" -H "Authorization: Bearer $ADMIN"
```

实测：

- 202 body：`{"sync_id":"<uuid>","status":"RUNNING","started_at":"..."}`。
- status（任务完成后）：`last_sync.status=SUCCEEDED`、`stats={fetched:36, registered:0, duplicated:36, failed:0}` → **duplicated==fetched**（erp 段 36 条全部幂等重放）。
- **同进程前提**：`/status` 读 API 进程内的内存任务注册表（M2 单副本语义）——下发与轮询必须命中**同一进程**（都用 compose 18000，或都用 venv 18001）；重启 api 后 last_sync 历史丢失。
- 幂等直证：重放后 `master.business_objects` 的 erp 对象数不变（36）且 `revision` 全为 1。

---

## ⑦ 控制台段（T18 真 API 冒烟 + 浏览器人工清单）

**目的**：EDP-301 事件流页 / 详情抽屉 / 回放向导走真实数据。本任务执行环境无浏览器（无头/CLI），浏览器级冒烟无法自动执行，故此处记录 **API 级冒烟**（以 `Invoke-RestMethod` 复刻前端调用序列，验证端点契约与数据形态），浏览器级留待演示彩排按文末「5 步清单」人工执行。

### 0. 起后端（二选一）

```powershell
# 正式演示：compose（已按「环境与前置」up -d --build）——无需额外步骤，BASE=http://localhost:18000
# 无头冒烟：venv uvicorn（从仓库根执行；端口 18000 已被 compose api 占用，故用 18001，同一 dev 库）
& "backend\.venv\Scripts\python.exe" -m uvicorn edp_api.main:app --port 18001
```

### 0.1 seed-demo（reset 重建）

```powershell
$env:PATH = "<repo>\backend\.venv\Scripts;$env:PATH"   # 用 venv PATH 前缀替代 uv run
python -m edp_api.modules.demo.cli seed --reset        # workdir=backend
```

实测输出：

```
fetched=40 registered=40 duplicated=0 failed=0 events_accepted=10 events_duplicated=0 case_created=True
```

> 说明：dev 库若为早期 seed（无 RESULT link），不带 `--reset` 重跑只会 `duplicated`，须 `--reset` 重建。重建后证据 50 条（40 快照 + 10 结果），RESULT link 由 `POST /events/batch` 同事务自动落库（events/service.py:311）。

### 1. 登录（manager1）

```powershell
$BASE = "http://127.0.0.1:18001"   # 无头冒烟；正式演示改 http://localhost:18000
$login = Invoke-RestMethod -Method Post -Uri "$BASE/api/v1/auth/login" -ContentType "application/json" `
  -Body '{"username":"manager1","password":"Admin@123!"}'
$H = @{ Authorization = "Bearer $($login.access_token)" }
```

实测：`tenant=default user=manager1 roles=MANAGER expires_in=7200`。

### 2. health（KPI 带数据源）

```powershell
Invoke-RestMethod -Uri "$BASE/api/v1/health" -Headers $H | Select-Object -ExpandProperty ops_metrics
```

实测六字段（RESET 首跑后）：`events_24h=50 ingest_peak_24h=50 p95_latency_ms=268 idempotency_hit_rate=0.0 dlq=0 evidence_count=50`
（`idempotency_hit_rate` 为 0~1 比值；RESET 后无重复事件 → 0.0，二跑/replay 后由 usage 日表累计 >0，见文末读数说明；`p95_latency_ms` 为 60~299ms 确定性回填值，随锚变化但恒 >0。）

### 3. 事件列表（total + 三派生字段）

```powershell
$events = Invoke-RestMethod -Uri "$BASE/api/v1/events?limit=20" -Headers $H
```

实测：`total=50 items=20 next_cursor=<非空 cursor 字符串>`；首行 `event_type=adapter.sync.failed ingest_latency_ms=251 delivery_status=DELIVERED object_source_id=PRJ-D`——`total`（分页文案，仅 events 端点填充）与 `ingest_latency_ms / delivery_status / object_source_id` 三派生字段均就位。

### 4. 类型筛选

```powershell
$filtered = Invoke-RestMethod -Uri "$BASE/api/v1/events?event_type=capability.result.order_risk&limit=20" -Headers $H
```

实测：`total=5 items=5`（订单风险结果 P0/P1/P2/P3，含场景 2）。

### 5. 事件详情（派生字段）

```powershell
$rid = $filtered.items[0].event_id
Invoke-RestMethod -Uri "$BASE/api/v1/events/$rid" -Headers $H
```

实测：`event_type=capability.result.order_risk risk_level=P0 score=0.93 ingest_latency_ms=298 delivery_status=DELIVERED object_source_id=SO-2026-00129`（P0 为场景 7 多条件组合风险）。

### 6. 证据行（RESULT 逆向追溯）

```powershell
$ev = Invoke-RestMethod -Uri "$BASE/api/v1/evidence?ref_type=RESULT&ref_id=$rid" -Headers $H
# 列表为简投影（不含 links，W3-06）——链接以详情端点复核：
Invoke-RestMethod -Uri "$BASE/api/v1/evidence/$($ev.items[0].evidence_id)" -Headers $H
```

实测：列表 `items=1`；详情 `source_record_id=result:<event_id>`、`links=[{"ref_type":"RESULT","ref_id":"<event_id>"}]`。前端抽屉证据行由此端点渲染（短 ID 取尾 8 位，T18 修复）。

### 7. 回放下发（202）

```powershell
$sync = Invoke-WebRequest -UseBasicParsing -Method Post -Uri "$BASE/api/v1/admin/adapters/erp-demo/sync" `
  -Headers $H -ContentType "application/json" -Body '{"mode":"replay"}'
```

实测：`HTTP 202`，body `{"sync_id":"<uuid>","status":"RUNNING","started_at":"..."}`。（控制台「回放向导」的底层调用与 ⑥ 相同。）

### 8. 适配器状态（duplicated==fetched）

```powershell
Invoke-RestMethod -Uri "$BASE/api/v1/admin/adapters/erp-demo/status" -Headers $H
```

实测：`last_sync.status=SUCCEEDED stats={fetched:36, registered:0, duplicated:36, failed:0}` → **duplicated==fetched**（replay 幂等重放全部已入库记录）。注意与 ⑥ 相同的**同进程前提**：下发与轮询须命中同一 api 进程。

### 9. 前端回归命令（T18）

```powershell
cd frontend
pnpm -r test -- --maxWorkers=2     # api-sdk 22 + shared 96 + web 131 = 249 全绿（宿主满载 flake，限 2 worker）
pnpm -r lint                       # 0 error（1 条既有 TenantSuspendedBanner warning）
pnpm --filter web build            # tsc --noEmit + vite build 成功
```

### 浏览器级冒烟（演示彩排人工执行，5 步清单）

> 无头环境无法执行；彩排时按下列 5 步人工确认（正式演示走 compose：`http://localhost:9080`，勿设 `VITE_USE_MSW`；本地 dev 模式 `$env:VITE_API_BASE="http://localhost:18000"`）。

1. **登录**：打开 `http://localhost:9080`（或 `pnpm --filter web dev` → 5173）→ `manager1 / Admin@123!` → 进入运营总览。
2. **事件流页**：侧栏「事件流」→ KPI 带四卡（24H 事件 50 / P95 延迟 / 幂等命中率 / 死信队列）→ 9 列表格 20 行 + 分页「显示 1–20 条，共 50 条」。
3. **筛选/翻页**：类型选「订单风险」→ 5 行；点「下一页」→ 行数变化，且翻页请求在途时上/下一页禁用（T18 防竞态）。
4. **详情抽屉**：任一行「详情」→ 右侧 420px 抽屉 → 字段区八格 + data JSON + 「关联证据」1 行（RESULT link 事件）或「无关联证据」（其余事件）。
5. **回放向导**：「回放事件」→ 选事件 → 选适配器 `erp-demo` → 执行 → 202 成功面板「回放已下发」+ sync_id；回适配器管理页确认状态空闲。

---

## 读数说明（锚、顺序与历史）

- 本文计数（seed 40/10、事件 50、P1 3 条、replay 36）由数据集常量决定，与锚无关；事件时间与 `ingest_latency_ms`、`event_id`、案例 `case_id` 随锚/随机生成变化。
- `events_24h` 等 24H KPI 依赖锚在近 24h 内：**演示前 `make seed-demo RESET=1`**（重锚）；跨日未重跑时计数会滑出窗口。
- `idempotency_hit_rate` 随重放历史变化：RESET 首跑后 0.0；二跑（40 快照 duplicated 计入）后 ≈0.44；再 replay（36 计入）后 ≈0.60。恒 >0 即证明幂等计量生效（归档命中不计入，W3-17）。
- ②~⑥ 在 venv 18001 实测；compose 18000 为正式演示路径，两者共用同一 dev 库与同一进程内任务注册表语义（**不可跨进程轮询 status**）。

---

## 缺口与备注（T18 实测 + T19 收口）

- **W3-06**：evidence 列表为简投影（无 `links`/`snapshot`），链接/快照走详情端点；前端抽屉证据行仅消费列表字段。
- **W3-12 / W3-21**：真实事件为 `{TYPE}_SNAPSHOT` + `capability.result.*` + `adapter.sync.failed` 共 50 条；MSW 展示型类型（`order.created` 等）不迁入。
- **端口偏差**：18000 为 compose api，本文件无头冒烟用 18001 venv 进程（同一 dev 库）；正式演示以 compose 18000 / web 9080 为准（前置须 `up -d --build`）。
- **T19 已补**：tools 六接口 + evidence_hint、405 举证、403 + GUARD_DENIED、回流 exceptions（P1 含 case_id）、replay 幂等——②~⑥ 已断言化为 `backend/tests/integration/test_m3_acceptance.py`（5 用例），可随时回归。

---

# W3 补齐（W3R）：注册中心 / Trace / Memory / 产能 / 限流

> 环境同前：venv 18001 或 compose 18000；`$H = @{ "X-API-Key" = "edp-dev-agent-hub-key" }`。
> 以下 ①~⑤ 已断言化为 `backend/tests/integration/test_w3r_acceptance.py`（5 用例），可随时回归。
> ③~⑤ 用到 JWT 的段落先做两个登录赋值（④ `$manager` / ⑤ `$admin`）：

```powershell
$mLogin = Invoke-RestMethod -Method Post -Uri "http://localhost:18001/api/v1/auth/login" -ContentType "application/json" -Body '{"username":"manager1","password":"Admin@123!"}'
$manager = @{ Authorization = "Bearer $($mLogin.access_token)" }
$aLogin = Invoke-RestMethod -Method Post -Uri "http://localhost:18001/api/v1/auth/login" -ContentType "application/json" -Body '{"username":"admin","password":"Admin@123!"}'
$admin = @{ Authorization = "Bearer $($aLogin.access_token)" }
```

## ① 注册中心（EDP-011）

```powershell
# 注册 Delivery.OrderRisk（B.7 示例）
$body = '{"name":"Delivery.OrderRisk","domain":"delivery","input_schema":{"type":"object"},"output_schema":{"type":"object"},"risk_level":"L2","permission":"READ_ONLY","endpoint":"agent-hub://capabilities/delivery-order-risk","owner":"wuyangpeng"}'
$r = Invoke-RestMethod -Method Post -Uri "http://localhost:18001/api/v1/capabilities" -Headers $H -Body $body -ContentType "application/json"
$r.capability_id   # 201：capability_id/name=Delivery.OrderRisk/status=ACTIVE/created_at
Invoke-RestMethod -Uri "http://localhost:18001/api/v1/capabilities?domain=delivery" -Headers $H | ConvertTo-Json -Depth 4
# 重名重发 → 409 CONFLICT
```

## ② Trace（EDP-013）

```powershell
$trace = '{"trace_id":"' + [guid]::NewGuid() + '","agent_id":"agent:delivery-order-risk","task_id":"task-w3r-001","started_at":"2026-09-17T08:00:00Z","finished_at":"2026-09-17T08:00:41Z","status":"SUCCEEDED","input_context":{"order_no":"SO-2026-00123"},"output_structured":{"risk_level":"P1","score":0.86},"token_usage":{"prompt":3120,"completion":480,"total":3600},"tool_calls":[{"seq":1,"tool_name":"get_inventory","input":{"material_code":"X-100"},"output":{"total_available":3200},"status_code":200,"latency_ms":85},{"seq":2,"tool_name":"get_order","input":{"order_no":"SO-2026-00123"},"status_code":200,"latency_ms":42}]}'
Invoke-RestMethod -Method Post -Uri "http://localhost:18001/api/v1/traces" -Headers $H -Body $trace -ContentType "application/json"
# 重发同 trace_id → 200（幂等，不重写 tool_calls）；GET /traces/{id} 含 2 条 seq 升序
```

## ③ Memory（EDP-014）

```powershell
$mem = '{"source_type":"decision","source_id":"' + [guid]::NewGuid() + '","content":{"lesson":"VIP客户订单优先保交付"}}'
$m = Invoke-RestMethod -Method Post -Uri "http://localhost:18001/api/v1/memories" -Headers $H -Body $mem -ContentType "application/json"
# 201：status=CANDIDATE；SERVICE 评审 → 403 GUARD_POLICY_DENIED + GUARD_DENIED 审计
Invoke-RestMethod -Method Patch -Uri "http://localhost:18001/api/v1/memories/$($m.memory_id)/review" -Headers $H -Body '{"status":"APPROVED"}' -ContentType "application/json"
# HUMAN（manager1 JWT）评审 → 200（reviewed_by/reviewed_at）
```

## ④ 产能（EDP-017 剩余）

```powershell
# seed 后：delivery.capacity 三行（L1/2026-W40=1200 紧张、L2/2026-W40=3600、L1/2026-W41=2400）
# mes-demo 重放 → 202 → status：fetched=3 duplicated=3 registered=0
Invoke-RestMethod -Method Post -Uri "http://localhost:18001/api/v1/admin/adapters/mes-demo/sync" -Headers $manager -Body '{"mode":"replay"}' -ContentType "application/json"
```

## ⑤ 限流配额 + 用量日报（EDP-025 / B.14）

```powershell
# 把 default 租户 api_rate_limit 调 2 → 前 2 次 200，第 3 次 429 + Retry-After（秒）
# 审计 RATE_LIMITED + tenant_usage_daily.throttled_429=1
# <tenant_id> 取值：default 租户经 GET /api/v1/tenants/current（$manager 凭据）取 tenant_id
Invoke-RestMethod -Uri "http://localhost:18001/api/v1/tenants/<tenant_id>/usage" -Headers $admin
# → items[0]：usage_date/api_calls/events_in/events_duplicated/storage_gb/throttled_429
```

## ⑥ 前端三页（人工 5 步清单）

1. **证据库** `/admin/evidence`：KPI 四卡（证据数量真值）→ 卡内搜索 `SO-2026-00123` → 选中订单 B 快照 → 链图 2 节点 + 链上校验计数 → 点「校验」→ 状态 pill 即时 VALID；
2. **重建索引**：MSW 模式（`VITE_USE_MSW=1`）页头「重建索引」可用 → 三步向导 → 202；真模式按钮禁用（tooltip「W5 交付」）；
3. **数据质量** `/admin/quality`：KPI 四卡（97.8/99.2/98.7/7）→ 维度 5 条（PLM 94.2 warning 色）→ 异常卡 3 条 + 合并提示 → 「重新检查」弹窗（默认全选）→ 提交后通知 + 任务日志抽屉（TASK-.../运行中/日志时间线）；
4. **系统健康** `/admin/systems`：HA（主库/0.4 MB/1 副本）+ 备份（PASSED）+ Outbox（3/6）+ 告警渠道四卡；「演练回放」链接；每 10s 深层轮询；
5. **真模式回归**（`VITE_USE_MSW=0`）：证据库列表/verify 走真 API；数据质量面板降级「—」、重校验禁用；系统健康 HA/Outbox 真值、备份卡提示「W5 交付」。
