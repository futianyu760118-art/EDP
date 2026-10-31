# EDP 控制台 MSW 模拟数据（W2+W3 六页）

| 项 | 内容 |
|---|---|
| 日期 | 2026-09-15 |
| 状态 | 已获用户批准（对话中确认：形态=前端 MSW 假数据；范围=W2+W3 六页全量） |
| 上游依据 | 《EDP数据平台开发计划_一阶段.md》EDP-201~203/301~304、《EDP数据平台系统设计文档_V2.0.md》13.6 页面规格 / 13.10 MSW 策略 / 附录 B API 契约、《AEOS一阶段执行计划》§10 十类评估场景 |
| 不改动 | `contracts/` 冻结物、后端代码、既有 W1 测试基线 |

## 1. 背景与目标

W1 已合并（M1 契约冻结），冻结契约仅含 auth/objects/events/tenants-current/healthz。W2/W3 前端六页（运营总览、业务对象、事件流、证据库、数据质量、系统健康）所需接口大半尚未实现（evidence/quality/health/adapters/ebms 等）。

按设计文档 13.10 策略：后端未就绪页面用 MSW handler 按附录 B 响应示例造数，切换仅改环境变量（已有 `VITE_USE_MSW=1` 机制）。本次交付完整的 MSW 数据层，使六页开发可先行，且数据故事与 AEOS §10 十类评估场景及 EDP-016（W3 演示 seed）对齐——后端就绪后逐页切真实 API，最终 MSW 数据集故事线可被 EDP-016 直接复用。

## 2. 用户已确认的决策

1. 交付形态 = 前端 MSW 假数据（非版本化工件 JSON、非直接写库 seed）；
2. 覆盖范围 = W2+W3 六页全量（含未冻结契约接口，按附录 B 示例造）；
3. 方案 A：fixtures（`data/`）+ handlers（按域拆分）分层，确定性固定数据，不用 faker。

## 3. 端点清单（27 个 handler）

### 3.1 已冻结契约（形状对齐 `@edp/api-sdk` 生成类型）

| 端点 | 用途（页面） | mock 语义 |
|---|---|---|
| GET /api/v1/objects | 业务对象列表 | 过滤（object_type/source_system/source_id/owner_domain/status）+ 游标分页 |
| GET /api/v1/objects/{id} | 对象详情 | 404 分支 |
| POST /api/v1/objects | 新建弹窗 | 首次 201 / 重复 200 且 revision+1；expected_revision 不符 → 409 + current_revision |
| GET /api/v1/objects/{id}/history | 详情历史 | revision 轨迹（与对象 revision 一致） |
| GET /api/v1/events | 事件流表格、总览时间线 | 过滤（object_id/event_type/risk_level/since/until）+ 分页 |
| GET /api/v1/events/{event_id} | 事件详情 | 404 分支 |
| POST /api/v1/events/batch | 幂等语义保真（能力结果回流通道，B.3） | Idempotency-Key 重放 → deduplicated=true + duplicated 计数 |
| GET /api/v1/tenants/current | 顶栏租户 | 固定租户 |
| POST login / refresh / me（既有） | 登录 | 保持现状，仅挪文件 |

### 3.2 未冻结契约（形状按附录 B 示例；类型定义在 `mocks/types.ts` 并标注 B.x 出处）

| 端点 | 出处 | 用途 |
|---|---|---|
| GET /api/v1/evidence（含 ?ref_type=&ref_id=） | B.4 | 证据库列表/链图逆向追溯 |
| GET /api/v1/evidence/{id} | B.4 | 证据详情 |
| GET /api/v1/evidence/{id}/verify | B.4 | verify 联动状态 pill |
| GET /api/v1/admin/quality/reports?date= | B.13 | 数据质量页维度评分/对账/孤儿/checksum |
| GET /api/v1/admin/quality/coverage | B.13 | 总览 Hero 指标 + 质量覆盖率 |
| GET /api/v1/health（?deep=true） | B.13 | 总览/系统健康的 HA、Outbox、备份卡 |
| GET /api/v1/admin/outbox/status | B.13 | 系统健康 Outbox 积压卡 |
| GET /api/v1/admin/adapters | B.12 | 总览适配器成功率、适配器清单 |
| GET /api/v1/admin/adapters/{name}/status | B.12 | 适配器状态 |
| POST /api/v1/admin/adapters/{name}/sync | B.12 | 事件回放向导（mode: incremental/full/replay）→ 202 |
| GET /api/v1/ebms/exceptions?severity=&status=&limit= | B.9 | 总览重点风险列表（含 case_id 关联） |
| GET /api/v1/audit-logs（+/{audit_id}） | B.6 | 总览审计动态/KPI、GUARD_DENIED 高亮数据 |

### 3.3 Mock 自有端点（后端任务落地后替换，代码注释标注）

| 端点 | 替换时机 | 用途 |
|---|---|---|
| POST /api/v1/admin/quality/rechecks → 202 {task_id} | EDP-030（W5） | 质量页重校验弹窗提交 |
| POST /api/v1/admin/evidence/reindex → 202 {task_id} | EDP-030/008 后评估 | 证据页重索引三步向导执行 |
| GET /api/v1/admin/quality/tasks/{task_id}（含日志） | EDP-030 | 任务日志抽屉 |

## 4. 数据故事（AEOS §10 十类场景 → 固定 fixtures）

固定 UUID（`00000000-0000-4000-8000-` + 递增序号，集中在 `data/ids.ts`）；固定演示时间锚 `DEMO_NOW = 2026-09-28T08:30:00Z`（附录 B 示例日期），保证测试与视觉回归可复现。数值与附录 B 示例一致（SO-2026-00123、X-100、S-021、C-008、PO-2026-00771、DC-20260928-007 等）。

| # | 场景 | 关键对象 | 关键事件/证据 |
|---|---|---|---|
| 1 | 正常订单 A | SO-2026-00122 | order.created；risk null |
| 2 | **M4 主线：关键料缺失 B** | SO-2026-00123 / X-100 / S-021 / PO-2026-00771 | capability.result.order_risk **P1**（缺口 1000、交期 10 天、预计延误 5 天）；证据=订单快照 v7/库存快照/PO 快照/交期快照；exceptions + case_id=DC-20260928-007 |
| 3 | 供应商延迟 C | SO-2026-00124 / S-118 | PO 预计到货推迟 2 周 → P2 |
| 4 | 新品未验证 D | 产品 P-D / rd 项目 PRJ-D（验证中） | readiness 未达产 → P2 |
| 5 | 高值低库存 E | SO-2026-00126 / 产品 P-F | order_quality P1（建议补料/通知客户） |
| 6 | VIP 客户 G | SO-2026-00128 / C-008 | 无风险（策略加权） |
| 7 | 组合风险 H | SO-2026-00129 | 部分缺料+产能紧张 → P0 综合高风险 |
| 8 | 数据不一致 I | SO-2026-00130 | 客户 ID 双记录 → 证据对比快照 + 人工确认事件 P2 |
| 9 | 供应商停产 J | SO-2026-00131 / S-030 | 多源依赖+停产通知 → P1（替代供应商建议） |
| 10 | 工具故障 | — | audit 中 GUARD_DENIED/UPSTREAM_UNAVAILABLE 记录 + events 中 adapter.sync.failed P2 |

fixtures 规模：objects ~24（10 订单 + 客户/物料/产品/供应商/PO/项目）、events ~60（含系统事件与能力结果回流）、evidence ~20、audit ~12、exceptions 8（P0×1=场景7、P1×3=场景2/5/9、P2×4=场景3/4/8/10，severity 过滤可验）、adapters 5（erp/mes/plm/mdm/crm，健康度含一个"降级"）、quality/health 按附录 B 示例扩展。

跨页一致性约束（写入测试断言）：events.object_id ⊆ objects；evidence.object_id/event_id 引用存在；exceptions.event_id ⊆ events；history 末位 revision = 对象 revision；链图 ref 链 Result→CASE→源记录可达。

## 5. 技术设计

### 5.1 目录结构（apps/web/src/mocks/）

```
mocks/
├── handlers.ts            # 聚合导出 [...auth, ...registry, ...eventsApi, ...evidence, ...quality, ...health, ...adapters, ...ebms, ...audit]
├── browser.ts / server.ts / msw-setup.ts   # 不变
├── types.ts               # 未冻结接口 TS 类型（注释标 B.x；冻结接口直接引用 api-sdk 生成类型）
├── lib/
│   ├── cursor.ts          # b64 offset 游标 encode/decode + paginate(list, params) 助手（返回 {items,next_cursor,total}）
│   ├── scenario.ts        # X-Mock-Scenario 请求头助手：429(RATE_LIMITED+Retry-After) / 503(UPSTREAM_UNAVAILABLE) / suspended(403 TENANT_SUSPENDED) —— 驱动 EDP-201 拦截器链联调
│   └── demo-time.ts       # DEMO_NOW 锚与日期助手
├── data/                  # ids.ts + objects/events/evidence/quality/health/adapters/ebms/audit（纯常量，无逻辑）
└── handlers/              # auth.ts（自 handlers.ts 迁入）/ registry.ts / events.ts / evidence.ts / quality.ts / health.ts / adapters.ts / ebms.ts / audit.ts
```

### 5.2 关键语义

- **游标分页**：cursor = base64(`offset:N`)；响应包裹 `{items, next_cursor, total}`。`total` 为 **mock 扩展字段**（冻结契约 Page envelope 无 total，但设计 13.7 模式 14 要求"共 N 条"文案）——记入契约偏差清单，待后端评审；前端 `total` 缺失时降级隐藏计数。
- **确定性**：无随机数、无 Date.now()；全部日期由 DEMO_NOW 相对偏移生成于模块加载时。
- **写语义**：mock 内部维护可变 Map（POST /objects upsert、events/batch 幂等档案、verify 结果缓存），仅影响当前会话——刷新即复位，符合演示 seed"可重放"定位。
- **场景注入**：`X-Mock-Scenario` 头仅在显式携带时生效，正常路径零影响。
- **mode 切换**：`VITE_USE_MSW=1` 启用（既有机制不变）；vitest 均走 `server.ts`。

### 5.3 测试（vitest，随 web 包 `pnpm test`）

1. `data/consistency.test.ts`：第 4 节跨页一致性约束全量断言；
2. handlers 分域测试：分页（limit/cursor/total/边界）、各过滤参数、objects upsert 409、events/batch 幂等、verify、ebms severity 过滤、sync 202、scenario 注入三分支；
3. 既有 W1 测试（auth handler、契约指纹等）保持绿。

## 6. 非目标

- 不做 W4/W5 页面（闭环案例/决策/行动/租户/审计页/演练回放）的完整数据——仅 audit-logs、exceptions 为总览页提供少量行；case_id 作前向引用常量存在；
- 不新增消息中心 API（EDP-303 验收中的"消息中心通知"由前端本地状态承接）；
- 不生成 MSW handler 的 OpenAPI 契约文件（未冻结端点以 `types.ts` + B.x 注释为准，M2/M3 后端实现时以真实契约回归）。

## 7. 风险

| # | 风险 | 缓解 |
|---|---|---|
| 1 | mock 形状与后续真实实现漂移 | types.ts 逐字段标 B.x 出处；后端每落地一组接口，对应 handler 删除并跑真实联调；差异记录进契约偏差清单 |
| 2 | Page envelope `total` 扩展造成前端依赖 | 前端封装分页组件时对 `total` 可选降级；偏差清单提醒 M2 评审 |
| 3 | 数据集与 EDP-016 seed 故事线不一致 | fixtures 的场景表（第 4 节）作为 EDP-016 输入；字段值对齐附录 B 示例 |
