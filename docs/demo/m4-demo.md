# M4 演示脚本（W4 收口版）

> 环境：Windows 宿主 + Docker Desktop。端口走本地 override 映射：db→**15432**、api→**18000**、web→**9080**。
> 种子凭据：`manager1 / Admin@123!`（MANAGER，闭环主角）、`admin / Admin@123!`（平台管理员，审计举证）。
> 场景（计划 7.1，AEOS §10 用例 2）：**订单 B（SO-2026-00123）关键料缺失——物料 X 缺口 1000、供应商 S-021 交期 10 天、预计延误 5 天**。
> 五幕 7 分钟：① 总览开场 1min → ② 风险抽屉下钻 1.5min → ③ 案例详情证据链 2min → ④ HITL 审批 + Action 闭环 1.5min → ⑤ 回总览回流 1min；⑥ 浏览器级彩排为人工清单（收口 W3-38）。
> **正式演示以 compose 为准**（api 18000 / web 9080）。①~⑤ 也可在无头环境用 venv uvicorn 18001 复现（同一 dev 库）；两种进程不可混用。
> 本文数值为 2026-09-18 实测（`make seed-demo RESET=1` 后按序执行）；读数口径见文末「读数说明」。

---

## 环境与前置

| 依赖 | 命令/说明 |
| --- | --- |
| Docker 服务（正式演示） | `docker compose -f deploy/docker-compose.dev.yml -f deploy/docker-compose.dev.override.yml up -d --build`（db/api/worker/web）。**必须带 `--build`**（W3-39）：旧镜像不含 W4 契约（actions/ebms 四端点/audit-policies/闭环聚合与新前端四页），会出现 `/api/v1/actions` 404、案例详情无 `evidence_chain`、web 无「闭环案例/决策/行动」页——重建后 W4 契约才生效 |
| 迁移 | 已迁移（compose api 启动即用；0012 含 audit.policies/cases 唯一索引/权限码）；如需重跑见 `m2-demo.md` ③ |
| 演示数据 | `make seed-demo RESET=1`（重锚重建；幂等口径见 ①） |
| 前端依赖 | `cd frontend && pnpm install`（compose web 容器已内置构建，仅本地 dev 模式需要） |

### 路径与变量约定

- `<repo>` = 仓库根（本机 `D:\wanghuazheng\project\数据平台`）；除注明外命令均从**仓库根**执行。
- `make` 需把 `<repo>\backend\.venv\Scripts` 加入 PATH（该目录含 `uv.exe`，Makefile 以 `uv run` 执行）：

  ```powershell
  $env:PATH = "<repo>\backend\.venv\Scripts;$env:PATH"
  ```

- ①~⑤ 用 `$BASE` 统一指向服务：正式演示 `http://localhost:18000`（compose）；无头冒烟 `http://127.0.0.1:18001`（venv，起法：`& "backend\.venv\Scripts\python.exe" -m uvicorn edp_api.main:app --port 18001`）。
- **中文 body 统一走下方 `Post-Json`/`Patch-Json` 辅助函数**：Windows GBK 控制台下 `curl.exe -d` 传中文会 JSON decode error（本轮实测踩坑）；ASCII body 可继续用 `curl.exe`（`\"` 转义惯例沿 m3-demo）。

  ```powershell
  function Post-Json($Uri, $Headers, $Body) {
    Invoke-RestMethod -Method Post -Uri $Uri -Headers $Headers `
      -ContentType "application/json; charset=utf-8" `
      -Body ([Text.Encoding]::UTF8.GetBytes(($Body | ConvertTo-Json -Depth 6)))
  }
  function Patch-Json($Uri, $Headers, $Body) {
    Invoke-RestMethod -Method Patch -Uri $Uri -Headers $Headers `
      -ContentType "application/json; charset=utf-8" `
      -Body ([Text.Encoding]::UTF8.GetBytes(($Body | ConvertTo-Json -Depth 6)))
  }
  ```

- 全程两个凭据头：`$H`（manager1 JWT，决策/行动主角）与 `$KH`（种子 Key `edp-dev-agent-hub-key`，SERVICE 轨道——AI 越权举证用）：

  ```powershell
  $BASE = "http://localhost:18000"    # 正式演示；无头冒烟改 "http://127.0.0.1:18001"
  $KEY = "edp-dev-agent-hub-key"
  $KH = @{ "X-API-Key" = $KEY }
  $login = Invoke-RestMethod -Method Post -Uri "$BASE/api/v1/auth/login" -ContentType "application/json" -Body '{"username":"manager1","password":"Admin@123!"}'
  $H = @{ Authorization = "Bearer $($login.access_token)" }
  ```

---

## ① 总览开场（1min：KPI + 风险卡）

**目的**：健康 KPI（六卡口径）+ EBMS 风险列表开场——P1 订单 B 在列且已关联决策案例。
**口径说明**：计划 7.2 的 `GET /admin/quality/coverage` 覆盖度周报为 M6 指标端点（未实现），总览开场以 `/health` KPI + `/ebms/exceptions` 替代。

```powershell
# 1. KPI 六字段
Invoke-RestMethod -Uri "$BASE/api/v1/health" -Headers $H | Select-Object -ExpandProperty ops_metrics

# 2. P1 风险列表（curl 口径，沿 m3-demo）
curl.exe -s "$BASE/api/v1/ebms/exceptions?severity=P1" -H "X-API-Key: $KEY"
```

实测（RESET 首跑后）：

- `ops_metrics`：`events_24h=53 ingest_peak_24h=53 p95_latency_ms=285 idempotency_hit_rate=0.0 dlq=0 evidence_count=53`
  （53 = 快照 43 + 回流 10；证据 53 同源——快照证据 + 10 条结果证据；RESET 首跑无重复事件 → 命中率 0.0。**注**：m3-demo 的 40/50 为 W3R mes-demo 产能 3 条并入前的旧口径，现 fetched=43。）
- `?severity=P1` → `items=3`：`SO-2026-00123`（**case_id 非空**，M4 主线）/ `SO-2026-00126` / `SO-2026-00131`，全部 `risk_level=P1`；订单 B 行 `summary=物料X缺口1000，预计延误5天`。
- 缺口读数旁白（tools 口径，见 ② 前置）：订单 12 万（`amount=120000.0`）含 `X-100×1000` 行；`inventory?material_code=X-100` → `total_available=3200.0`（WH-01=0 / WH-02=3200）、BOM 单耗 2.5、S-021 交期 10 天——推导出「缺口 1000 / 延误 5 天」的结果事件。

---

## ② 风险抽屉下钻（1.5min：时间线 + 证据）

**目的**：从风险列表下钻订单 B 风险事件详情 + 证据行（RESULT 可逆向追溯到源快照）。

```powershell
# 1. 定位订单 B 风险事件（object_source_id 派生字段过滤）
$events = Invoke-RestMethod -Uri "$BASE/api/v1/events?event_type=capability.result.order_risk&limit=20" -Headers $KH
$b = $events.items | Where-Object { $_.object_source_id -eq "SO-2026-00123" }
$rid = $b.event_id

# 2. 事件详情（派生读数）
Invoke-RestMethod -Uri "$BASE/api/v1/events/$rid" -Headers $KH

# 3. 证据行（抽屉「关联证据」同源）：RESULT link 逆向 + 对象维度
Invoke-RestMethod -Uri "$BASE/api/v1/evidence?ref_type=RESULT&ref_id=$rid" -Headers $KH
$objId = (Invoke-RestMethod -Uri "$BASE/api/v1/events/$rid" -Headers $KH).object_id
Invoke-RestMethod -Uri "$BASE/api/v1/evidence?object_id=$objId" -Headers $KH
```

实测：

- 事件详情：`risk_level=P1 score=0.86 result_type=ORDER_RISK ingest_latency_ms=259 delivery_status=DELIVERED object_source_id=SO-2026-00123`（`event_id` 为锚派生 UUIDv5，随 RESET 变化；`total=5` 为订单风险结果五场景）。
- `?ref_type=RESULT&ref_id=` → 1 行：`agent-hub/result:<event_id>`（回流结果证据）。
- `?object_id=` → 2 行（决策前）：`agent-hub/result:<event_id>` + `erp/SO-2026-00123#v1`（源快照证据）——抽屉短 ID 取尾 8 位；闭环完成后该对象证据增至 6 条（见 ④ 读数）。

---

## ③ 案例详情一屏证据链（2min：Result→Decision→Evidence→Source + verify）

**目的**：`/cases/:case_id` 一屏四区（问题卡/证据链横向图/Steps 时间线/关联行动卡）；API 层为闭环聚合端点。

```powershell
# 1. 找订单 B 案例
$cases = Invoke-RestMethod -Uri "$BASE/api/v1/decisions/cases?limit=10" -Headers $H
$c = $cases.items[0]                    # seed 后仅 1 条（场景 2）
$cid = $c.case_id

# 2. 案例详情（闭环聚合：event/steps/actions/evidence_chain）
$detail = Invoke-RestMethod -Uri "$BASE/api/v1/decisions/cases/$cid" -Headers $H
$detail.event                            # 源事件摘要
$detail.steps                            # 时间线（决策前 2 节点）
$detail.evidence_chain | Group-Object layer | Select-Object Name, Count

# 3. verify（证据链任一节点 → 即时校验）
$node = $detail.evidence_chain | Where-Object { $_.evidence_id } | Select-Object -First 1
Invoke-RestMethod -Uri "$BASE/api/v1/evidence/$($node.evidence_id)/verify" -Headers $H
```

实测（决策前 seed 态）：

- 列表：`items=1`，`case_no=DC-20260917-001`（**UTC 日期**——本地 9/18 上午时 UTC 仍为 9/17）、`risk_level=P1`、`status=OPEN`。
- 详情：`event.risk_level=P1`、`event.summary=物料X缺口1000，预计延误5天`；`context={order_amount:120000, material_gap:1000, source_event_id:<uuid>}`。
- `steps=2`：`EVENT → CASE_CREATED`（时间升序）。
- `evidence_chain`：`RESULT×1 EVIDENCE×3 SOURCE×3`——RESULT=`agent-hub/result:<event_id>`；EVIDENCE=seed CASE links（订单快照/X-100 库存/PO-2026-00771）；SOURCE=三层 `(source_system, source_record_id)` 投影去重。
- **DECISION 层此时为空（决策尚未发生）**——④ 审批后复读补齐四层（叙事口径：③ 讲链骨架，④ 讲链闭环，两次读数对比即「证据链生长」）。
- verify：`{"evidence_id":"<uuid>","valid":true,"verified_at":"..."}`——canonical checksum 重算一致（篡改场景走 `POST /evidence` 后改 snapshot 不可能，verify 失败路径由测试覆盖）。

---

## ④ HITL 审批 + Action 闭环（1.5min：审批 → 执行 → Verified）

**目的**：Human-Only 三连举证（AI 提交决策 403 / AI 推进 EXECUTING 403 / 非法转移 422）+ manager 审批 + 行动六步到 VERIFIED + 意见落证据链。

```powershell
# 1. AI 越权举证 ①：SERVICE Key 提交决策记录 → 403 GUARD_POLICY_DENIED
curl.exe -s -i -X POST "$BASE/api/v1/decisions/cases/$cid/records" -H "X-API-Key: $KEY" `
  -H "Content-Type: application/json" -d '{\"chosen_option\":\"EXPEDITE\"}'

# 2. 拒绝留痕举证（admin JWT 查审计行）
$aLogin = Invoke-RestMethod -Method Post -Uri "$BASE/api/v1/auth/login" -ContentType "application/json" -Body '{\"username\":\"admin\",\"password\":\"Admin@123!\"}'
$ADMIN = @{ Authorization = "Bearer $($aLogin.access_token)" }
Invoke-RestMethod -Uri "$BASE/api/v1/audit-logs?action=GUARD_DENIED&resource_type=decision.records&limit=5" -Headers $ADMIN

# 3. manager 审批（Human）→ 案例 DECIDED；ebms 待决清零
$dec = Post-Json "$BASE/api/v1/decisions/cases/$cid/records" $H @{
  chosen_option = "EXPEDITE"; decision_type = "HUMAN"; comment = "同意加急采购，优先保交付" }
Invoke-RestMethod -Uri "$BASE/api/v1/ebms/decisions/pending" -Headers $KH   # total_pending: 1 → 0

# 4. 决策意见落证据链（DECISION 层，最小补建口径——见缺口 W4-10）
$objId = (Invoke-RestMethod -Uri "$BASE/api/v1/events/$($detail.event.event_id)" -Headers $KH).object_id
Post-Json "$BASE/api/v1/evidence" $H @{
  source_system = "ebms"; source_record_id = "decision:$cid"; object_id = $objId
  snapshot = @{ comment = "同意加急采购，优先保交付" }
  captured_at = "2026-09-18T02:00:00Z"
  links = @(@{ ref_type = "DECISION"; ref_id = $cid }) }

# 5. 建行动（PROPOSED）
$act = Post-Json "$BASE/api/v1/actions" $H @{
  case_id = $cid; title = "加急采购物料X 1000 件"; action_type = "expedite_purchase"
  owner = "procurement_zhang"; owner_role = "PROCUREMENT" }
$aid = $act.action_id

# 6. 非法转移举证 ②：PROPOSED → VERIFIED → 422（extra.allowed_to 引导按钮组重渲染）
curl.exe -s -X PATCH "$BASE/api/v1/actions/$aid/status" -H "Authorization: Bearer $($login.access_token)" `
  -H "Content-Type: application/json" -d '{\"from_status\":\"PROPOSED\",\"to_status\":\"VERIFIED\"}'

# 7. 六步走（第 1 步带意见；其中第 4 步 EXECUTING 前先做 AI 越权举证 ③）
Patch-Json "$BASE/api/v1/actions/$aid/status" $H @{ from_status = "PROPOSED"; to_status = "ASSIGNED"; comment = "指派给采购张三，限两日内反馈" }
curl.exe -s -X PATCH "$BASE/api/v1/actions/$aid/status" -H "X-API-Key: $KEY" `
  -H "Content-Type: application/json" -d '{\"from_status\":\"PROPOSED\",\"to_status\":\"REJECTED\"}'   # 409 举证：from_status 过期
Patch-Json "$BASE/api/v1/actions/$aid/status" $H @{ from_status = "ASSIGNED"; to_status = "ACCEPTED" }
Patch-Json "$BASE/api/v1/actions/$aid/status" $H @{ from_status = "ACCEPTED"; to_status = "APPROVED" }
curl.exe -s -X PATCH "$BASE/api/v1/actions/$aid/status" -H "X-API-Key: $KEY" `
  -H "Content-Type: application/json" -d '{\"from_status\":\"APPROVED\",\"to_status\":\"EXECUTING\"}'  # 403 举证：Human-Only 边
Patch-Json "$BASE/api/v1/actions/$aid/status" $H @{ from_status = "APPROVED"; to_status = "EXECUTING"; comment = "采购下单完成，供应商 S-021 确认交期 10 天" }
Patch-Json "$BASE/api/v1/actions/$aid/status" $H @{ from_status = "EXECUTING"; to_status = "COMPLETED" }
Patch-Json "$BASE/api/v1/actions/$aid/status" $H @{ from_status = "COMPLETED"; to_status = "VERIFIED"; comment = "到货 1000 件已入库，缺口闭环" }

# 8. 行动详情 + 意见落证据读数
Invoke-RestMethod -Uri "$BASE/api/v1/actions/$aid" -Headers $H
Invoke-RestMethod -Uri "$BASE/api/v1/evidence?ref_type=ACTION&ref_id=$aid" -Headers $KH

# 9. 案例详情复读：四层链补齐 + steps 长出决策/行动节点
$detail2 = Invoke-RestMethod -Uri "$BASE/api/v1/decisions/cases/$cid" -Headers $H
$detail2.steps | ForEach-Object { "$($_.step_type)$(if ($_.human_only) {'(Human-Only)'}) $($_.title)" }
$detail2.evidence_chain | Group-Object layer | Select-Object Name, Count
```

实测：

- **403 举证①**：`{"error":{"code":"GUARD_POLICY_DENIED","message":"该操作仅限人工执行"}}`；审计行 `action=GUARD_DENIED actor_type=SERVICE actor=agent-hub resource=decision.records/{case_id}`，`detail={path:"/api/v1/decisions/cases/{cid}/records", reason:"Human-Only", scopes:[readonly,write:event,write:registry,write:decision,write:trace,write:memory,write:action]}`（AI 越权执行=0 的举证基础）。
- 决策：`{decision_id, case_status:"DECIDED"}`；`pending.total_pending` **1 → 0**。
- 行动创建：`{action_id, status:"PROPOSED", created_at}`。
- **422 举证**：`{"error":{"code":"INVALID_TRANSITION","message":"非法转移：PROPOSED → VERIFIED","allowed_to":[{ASSIGNED},{CANCELLED},{REJECTED}]}}`（`allowed_to` 即前端按钮组重渲染数据源）。
- **409 举证**：`{"error":{"code":"CONFLICT","message":"from_status 与当前状态不符：PROPOSED"}}`（当前已 ASSIGNED；前端文案「数据已被他人修改，已刷新」）。
- **403 举证③**：SERVICE Key 推 `APPROVED→EXECUTING`（Human-Only 边）→ 同 403 envelope + `GUARD_DENIED` 审计行（`resource=action.actions/{action_id}`）；状态仍 APPROVED（守卫先于写）。
- 六步后详情：`status=VERIFIED`、`completion_time/verified_at` 非空、`verified_by=<manager1 用户 UUID>`（口径同 memories.reviewed_by，非显示名）、`allowed_to=[]`（终态无出边）。
- **意见落证据**：`GET /evidence?ref_type=ACTION&ref_id=` → 3 行：`edp/{action_id}#ASSIGNED`、`#EXECUTING`、`#VERIFIED`（snapshot=`{"comment":...}`，checksum sha256）。
- 案例复读：`steps=5`——`EVENT → CASE_CREATED → DECISION(Human-Only) → ACTION(创建) → ACTION(当前状态：VERIFIED)`；`evidence_chain` 四层补齐：`RESULT×1 DECISION×1 EVIDENCE×3 SOURCE×4`；对象维度证据 2 → 6 条（+1 决策意见 +3 行动意见）。

---

## ⑤ 回总览——闭环事件回流（1min）

**目的**：模拟中枢回流 `action.verified` 事件（幂等重放）→ 待办清空 + KPI 变化 + 经营简报。

```powershell
# 1. 待办读数（决策 + 行动收口后）
Invoke-RestMethod -Uri "$BASE/api/v1/ebms/todos" -Headers $KH

# 2. 模拟中枢回流（action.verified；Idempotency-Key 必填）
$reflow = @{ events = @(@{
  event_type = "action.verified"; object_id = $objId; source_system = "edp"
  occurred_at = (Get-Date).ToUniversalTime().AddSeconds(-30).ToString("yyyy-MM-ddTHH:mm:ssZ")
  actor_type = "SERVICE"; actor_id = "edp"; result_type = "ACTION"
  data = @{ order_no = "SO-2026-00123"; action_id = $aid
            summary = "行动已验证：加急采购物料X缺口闭环" } }) }
$IK = @{ "X-API-Key" = $KEY; "Idempotency-Key" = "demo-m4:action-verified:v1" }
Post-Json "$BASE/api/v1/events/batch" $IK $reflow                 # 首发 accepted=1
Post-Json "$BASE/api/v1/events/batch" $IK $reflow                 # 重放 deduplicated=True

# 3. 回流读数：事件列表 + KPI + 经营简报
Invoke-RestMethod -Uri "$BASE/api/v1/events?event_type=action.verified" -Headers $KH
Invoke-RestMethod -Uri "$BASE/api/v1/health" -Headers $H | Select-Object -ExpandProperty ops_metrics
Invoke-RestMethod -Uri "$BASE/api/v1/ebms/reports/summary" -Headers $KH
```

实测：

- todos（收口后）：`pending_decisions=0 pending_actions=0 exceptions_to_confirm=9`（9 = 10 条风险事件 − 场景 2 一条已关联案例）。
- 回流首发：`{accepted:1, duplicated:0, rejected:0, deduplicated:false}`；**同 Idempotency-Key 重放**：`deduplicated=true`（存档命中，本轮 0 新增——幂等重放举证）。
- `?event_type=action.verified` → `total=1`，行含 `object_source_id=SO-2026-00123`、`data.summary=行动已验证：加急采购物料X缺口闭环`。
- KPI 变化：`events_24h` **53 → 54**、`evidence_count` **53 → 57**（+1 决策意见 +3 行动意见证据；action.verified 无 risk_level 不自动落结果证据）；`idempotency_hit_rate` 仍 0.0（**归档命中不计入**，W3-17）。
- `reports/summary`：`period=2026-09 objectives=3 kpis=3 recent_changes_summary=5`；kpis=`on_time_delivery=91.2%(锚当周) inventory_turnover=7.2次/月 risk_closure_rate=85.0%`（management seed 静态值，见读数说明）；`recent_changes_summary` 前 3：`订单 PLM PLM 同步失败…` / `订单 SO-2026-00129 部分物料短缺+产能紧张…` / `订单 SO-2026-00123 物料X缺口1000，预计延误5天`（风险事件派生文案，W4-05）。

---

## ⑥ 浏览器级彩排（演示彩排人工执行，5 步清单——收口 W3-38）

> 无头环境无法执行；彩排时按下列 5 步人工确认（正式演示走 compose：`http://localhost:9080`，勿设 `VITE_USE_MSW`；本地 dev 模式 `$env:VITE_API_BASE="http://localhost:18000"`）。前置：按「环境与前置」`up -d --build` + `make seed-demo RESET=1`，再按 ①~⑤ 走一遍 API 段（页面读真数据）。

1. **总览 KPI/风险抽屉**：登录 `manager1 / Admin@123!` → 运营总览 KPI 卡（24H 事件 53 等）；侧栏「事件流」→ 订单风险筛选 → 订单 B（SO-2026-00123）行「详情」→ 抽屉字段区 + 「关联证据」1 行（RESULT link）——风险抽屉下钻对应 ②。
2. **案例详情四区**：侧栏「闭环案例」→ `/cases` 列表（筛选/风险 pill）→ 订单 B 行「查看」→ `/cases/:case_id` 一屏四区：问题卡（context 影响说明 + options 只读）/ 证据链横向图（层标签 + 节点展开）/ Steps 时间线（Human-Only 节点人形图标 + tooltip「仅人工可执行」）/ 关联行动卡——对应 ③。
3. **verify 即时校验**：案例详情证据链任一 EVIDENCE 节点点「校验」→ 状态 pill 即时 VALID + toast——对应 ③ verify 读数。
4. **决策审批**：侧栏「决策审批」→ `/decisions` 待决列表（头部「待决 1」角标）→ 「审批」→ 表单（选项 radio + 意见 textarea + Human-Only 图标）→ 提交 → toast「决策已提交」+ 列表刷新移除；AI 轨道 403 → 「该操作仅限人工执行」提示（13.9.2 逐字）——对应 ④ 步骤 1/3。
5. **行动状态机**：侧栏「行动」→ `/actions` 列表 → 行点击 420px 抽屉：**9 态状态轴**（已走路径高亮、当前节点实心、REJECTED/CANCELLED 分支弱化）+ `allowed_to` 按钮组（human_only 转移人形图标）→ 转移弹窗（comment）提交；六步走完 → 状态轴全亮 VERIFIED、todos 清空——对应 ④ 步骤 5~7 + ⑤。

---

## 读数说明（锚、顺序与历史）

- 本文计数（seed 43/10、风险事件 10、P1×3、待确认异常 9、六步转移）由数据集常量决定，与锚无关；`event_id`/`case_id`/`action_id`/`evidence_id` 为 UUIDv5/UUIDv4 随锚与执行变化；`p95_latency_ms` 为 60~299ms 确定性回填值。
- **seed 计数 43**（erp 36 + mes 3 + plm 4）为 W3R mes-demo 并入后口径；m3-demo 的 40/50 读数对应其发布时点，不冲突。
- `events_24h` 等 24H KPI 依赖锚在近 24h 内：**演示前 `make seed-demo RESET=1`**；`idempotency_hit_rate` 随重放历史（RESET 首跑 0.0 → 二跑 ≈0.45；events/batch 归档命中**不计入**，W3-17）。
- `case_no`（DC-YYYYMMDD-NNN）日期为 **UTC**；本地时区晚于 UTC 时演示当日下午建案例会看到次日无偏、上午会看到昨日日期。
- `reports/summary` 的 kpis 为 management seed 静态值（91.2/7.2/85.0，period=锚 ISO 周），不随闭环动态重算；`recent_changes_summary` 仅含 `risk_level` 非空事件——`action.verified` 回流事件**不进**该列表（出现在 `/events` 与 KPI 计数中）。
- 决策前案例 `evidence_chain` 的 DECISION 层为空属预期（决策意见在 ④ 落链）；两轮案例详情对比（2→5 steps、三层→四层）即「证据链生长」演示点。
- ①~⑤ 本轮在 compose 18000 实测（W4 镜像 `--build` 重建后）；无头 18001 与 compose 共用同一 dev 库，读数等价（进程内单副本语义注意事项沿 m3-demo ⑥/⑦）。

---

## 缺口与备注（T13 实测）

- **W4-10 决策记录不自动落 DECISION 证据**：`POST /decisions/cases/{id}/records` 只写 decision.records + 案例 DECIDED，不自动创建 `ref_type=DECISION` 证据——案例详情证据链 DECISION 层需消费方最小补建（演示 ④ 步骤 4 / `test_m4_acceptance` 同口径）；后续在 submit_record 内同事务落证收口。
- **act③ 时点 DECISION 层为空**：演示叙事按「③ 链骨架 → ④ 链闭环」两轮读数对比呈现（非缺陷，口径说明）。
- **`/admin/quality/coverage` 未实现**：计划 7.2 覆盖度周报为 M6 指标端点；总览开场以 `/health` KPI + `/ebms/exceptions` 替代（① 口径说明）。
- **中文 body 控制台坑**：Windows GBK 控制台 `curl.exe -d` 传中文必现 JSON decode error——中文 body 统一走本文「路径与变量约定」的 `Post-Json`/`Patch-Json`（UTF-8 字节）；ASCII body 可继续 curl。
- 其余闭环相关缺口（steps 无逐转移史 W4-01 / 快照 human_only 语义 W4-02 / B.9 网关路径 W4-06）见 `m2-demo.md` W4 轮；本五幕已断言化为 `backend/tests/integration/test_m4_acceptance.py`（6 用例：全链闭环/Human-Only 403/非法转移 422/并发 409/ebms 口径/聚合完整），可随时回归。
