# 租户编码自动生成设计（ten-YYYY-NNNN）

- 日期：2026-10-16
- 分支：feat/v13-realtime
- 状态：已确认（方案 A 计数表原子取号 + default 锚点除外）

## 1. 背景与问题

当前租户编码 = `platform.tenants.slug`（全局唯一，校验 `^[a-z0-9-]{2,32}$`），
开通租户（B.14）时由管理员在 `CreateTenantModal` 手工输入，冲突 409 行内报错。
问题：

- 编码质量不可控（拼音/缩写/随手敲，风格不统一）；
- 人工输入多一步交互，409 重试体验差；
- 编码无结构语义，无法从编码看出开通年份与序位。

## 2. 需求裁定

| 项 | 裁定 |
|---|---|
| 编码规则 | `ten-YYYY-NNNN`（小写），例 `ten-2026-0042` |
| 序号语义 | 按年重置（ten-2027-0001）；>9999 自然溢出 5 位（ten-2026-10042） |
| 交互 | 完全自动：前端删除编码输入框；API 请求体删除 `slug` 字段；不支持自定义 |
| 存量租户 | 一并迁移为新格式；**`default` 租户除外**（登录/CLI 缺省锚点，见 §5） |
| 存量可回滚 | 旧 slug 备份进 `attributes.legacy_slug`，downgrade 精确还原 |

## 3. 方案选型（已裁定 A）

| 方案 | 机制 | 结论 |
|---|---|---|
| **A. 计数表原子取号** | `platform.tenant_code_seq(year PK, last_no)`；`INSERT … ON CONFLICT (year) DO UPDATE SET last_no = tenant_code_seq.last_no + 1 RETURNING last_no` 单条 SQL 原子取号 | **采用**：无竞态无重试，确定性续号 |
| B. max+1 推号 | 查当年最大号 +1，唯一索引冲突重试 | 否决：并发重试窗口 + LIKE 解析脆弱 |
| C. 每年动态 sequence | 动态建 `seq_tenant_code_YYYY` | 否决：动态 DDL 有跨年竞态，权限管理繁琐 |

## 4. 数据库变更（迁移 0020）

### 4.1 计数表

```sql
CREATE TABLE platform.tenant_code_seq (
    year    INTEGER PRIMARY KEY,          -- 取号年份（created_at 所在年）
    last_no INTEGER NOT NULL DEFAULT 0,   -- 该年已发出的最大序号
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE ON platform.tenant_code_seq TO edp_app;
```

定位：控制面小表，与 tenants/tenant_quotas 同级（无 RLS——无租户语义，
平台管理员与开通流程使用；权限收敛 edp_app）。

### 4.2 存量迁移（upgrade）

1. 圈定范围：`slug NOT LIKE 'ten-\d{4}-%'` 且 `slug <> 'default'` 的租户；
2. 按 `date_trunc('year', created_at)` 分组、组内 `created_at, tenant_id`
   升序，依次重写为 `ten-<年份>-<四位序号>`（序号从 0001 起，溢出自然 5 位）；
3. 每次重写前把旧值写入该行 `attributes = attributes || '{"legacy_slug": "<旧值>"}'`；
4. 迁移完成后把各年已用最大序号回填计数表（`INSERT … ON CONFLICT (year)`），
   保证后续取号从存量之后续起；
5. 全程在迁移事务内，唯一索引兜底冲突（理论不可达：组内序号确定性生成）。

### 4.3 回滚（downgrade）

1. 从 `attributes.legacy_slug` 逐行还原 slug 并移除该键；
2. 删除计数表；
3. 裁定：downgrade 后新建于迁移期间的 `ten-*` 租户 slug 保持新格式不动
   （无 legacy_slug 可还原的行跳过），不阻塞降级。

### 4.4 验证

- alembic up/down/up 循环；
- 存量映射断言：迁移前 slug 清单 ↔ 迁移后 (slug, legacy_slug) 一一对应；
- 计数表初值 = 各年存量最大序号。

## 5. default 锚点裁定（除外不动）

`default` 租户是系统缺省锚点，被三处硬编码引用：

| 引用点 | 位置 | 语义 |
|---|---|---|
| 登录缺省 | `platform/service.py` `payload.tenant_slug or "default"` | 不填租户即 default（演示便利） |
| demo CLI | `modules/demo/cli.py --tenant-slug default` | 种子数据定位 |
| ingest CLI | `modules/ingest/cli.py --tenant-slug default` | 增量/对账定位 |

裁定：`default` 保持原名不迁移，登录/CLI/文档零改动；
若未来需要全量新格式，另行立项（缺省解析改"唯一租户自动解析"语义）。

## 6. 后端改动

### 6.1 tenantmgmt/service.create_tenant

- 删除 slug 入参与「先查再插 409」分支；
- 取号函数 `next_tenant_code(sess, year: int | None = None) -> str`：
  - `year=None` 时取 `now()` 所在年（UTC，与 created_at 同源）；
    显式传年仅供测试跨年重置语义，业务路径不传；
  - 单条 upsert-returning 取号（见 §4.1 SQL）；
  - 格式化 `f"ten-{year}-{no:04d}"`（no > 9999 时 f-string 自然溢出 5 位）；
- 保留 flush 处 `IntegrityError` 兜底（唯一索引冲突 → 409，理论不可达，
  防御计数表被外部改坏的场景）。

### 6.2 tenantmgmt/schemas

- `TenantCreateRequest` 删除 `slug` 字段（请求体不再接受；
  pydantic 默认忽略多余传入字段，不报错）；
- `TenantCreateResponse` 不变（`slug` 回传生成码）；
- 其余引用 slug 的响应模型（TenantSummary/CurrentTenant 等）不变。

## 7. 契约与 SDK

- 契约包 tenant-create JSON Schema 同步删除 `slug` 必填属性；
- schema-gate 本地跑绿；
- SDK 类型重生成，指纹更新。

## 8. 前端改动

- `CreateTenantModal.tsx`：删除编码输入框与 hint；必填校验去掉 slug 项；
  开通成功提示沿用现有 `created.slug` 展示生成码（无需新增 UI）；
- MSW handler：createTenant 去掉请求体 slug 断言，响应改为按年自增 mock。

## 9. 测试计划

| 层 | 用例 |
|---|---|
| 单测（service） | 取号格式/按年重置/溢出 5 位/并发取号不重号（asyncio.gather N 并发全不同） |
| 集成（迁移） | 0020 存量重写映射 + 计数表回填 + up/down/up + legacy_slug 还原 |
| 集成（API） | 开通请求体无 slug 字段 → 201 且响应 slug 匹配 `^ten-\d{4}-\d{4,}$`；两次开通序号递增；跨年重置（时钟注入或直接调取号函数按指定年） |
| 前端 | TenantsPage：删输入框后表单仍可提交；成功提示含生成码；原 409 用例改为无 slug 场景 |
| 回归 | 登录 default 缺省路径 / demo CLI / ingest CLI 不受影响（default 未迁移） |

## 10. 明确不做（YAGNI）

- 不支持自定义编码覆盖；
- 不做编码二次修改接口；
- 不迁移 default；
- 不给旧系统对接留 slug 别名解析（legacy_slug 仅回滚用，不参与查询路由）。
