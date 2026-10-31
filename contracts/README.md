# contracts/ —— API 契约中立场

本目录存放 EDP 数据平台的对外 API 契约快照（单一事实来源 = 后端 FastAPI 应用定义）。
契约路径已含完整前缀（如 `/api/v1/auth/login`），消费方直接以部署根为 base URL 即可。

## 域契约包（V1.2 T02 起）

除 API 契约（openapi.json）外，`contracts/` 还存放 AEOS **企业语义契约**（JSON Schema，
Draft 2020-12），与 API 契约分离维护：

```text
object/        business-object.schema.json     业务对象语义契约（含四层归属/official 指针）
event/         event.schema.json               事件语义契约（Domain.Object.Action）
result/        result.schema.json              经营结果语义契约（evidence_refs 必挂）
evidence/      evidence.schema.json            证据语义契约（checksum/links 逆向穿透）
decision/      decision-record.schema.json     决策记录（V1.2 T22 对账导出）
action/        action-record.schema.json       行动记录（9 态状态机；V1.2 T22）
trace/         trace.schema.json               Agent 轨迹（V1.2 T22）
governance/    cleaning-rule.schema.json       清洗规则（版本化 + 修复留痕）
               classification.schema.json      多维分类（AI 建议 → 审核 → 正式）
               lineage.schema.json             数据血缘
               admission-state.schema.json     数据准入状态机（A1–A4）
metric|value/                                  W4 冻结（见迭代方案 V1.2 第九节）
```

域契约与 API 契约的关系：语义契约定义"企业事实长什么样"（跨系统一致口径），
API 契约定义"EDP 接口长什么样"（字段名以 openapi.json 为准，如语义契约的
`source_object_id` 对应 API 的 `source_id`）。两者冲突时以 openapi.json 为准，
语义契约同步修订。

## 快照与指纹

| 文件 | 说明 |
|---|---|
| `openapi.json` | **冻结基准**：由 `backend/scripts/export_openapi.py` 从 FastAPI app 导出的排序稳定 JSON（`indent=2, sort_keys=True, ensure_ascii=False`，UTF-8，尾部换行） |
| `openapi.sha256` | **指纹**：对 `openapi.json` 文件字节的 SHA-256，**纯 hex 一行**（无文件名后缀、非 GNU `sha256sum` 双空格格式），供 CI 与前端 SDK 指纹门禁比对 |

生成 / 校验命令（在 `backend/` 下）：

```powershell
uv run python scripts/export_openapi.py          # 重新生成快照 + 指纹
uv run python scripts/export_openapi.py --check  # 校验：不符 exit 1 并打印首个差异 JSON 路径
```

## 双门禁机制（CI）

任一门禁失败即 PR 失败，二者共同保证「代码 ↔ 契约 ↔ SDK」三方一致：

1. **后端导出 diff 门禁**（`.github/workflows/backend.yml` → `contract-gate` job）：
   重导出 OpenAPI 与磁盘快照逐字节比对（JSON 深度 diff 定位首个差异路径 + sha256 指纹校验），
   不一致 exit 1 —— 防止后端路由/模型变更未同步快照；
2. **前端 SDK 指纹门禁**（`.github/workflows/frontend.yml` → `contract-fingerprint-gate` job，T22 交付）：
   重算 `contracts/openapi.json` 的 sha256 与 `openapi.sha256`、
   `frontend/packages/api-sdk/src/generated/fingerprint.json` 三方比对，
   不一致 exit 1 —— 防止契约变更未重新生成 SDK。

另设 **域契约 schema 门禁**（`.github/workflows/backend.yml` → `schema-gate` job，V1.2 T07）：
校验 `contracts/**/*.schema.json` 均可解析、通过 Draft 2020-12 meta-schema 校验、
`$id` 与路径一致；本地运行 `make schema-gate`。

## 冻结后变更流程（三联动，缺一不可）

契约一经冻结（M1 出口条件），任何 `openapi.json` 变更必须**同一个 PR 内**完成：

1. **PR**：标题前缀 `[contract]`，正文附变更动机、影响面与向后兼容性说明；
2. **Tech Lead 评审**：评审人必须包含 Tech Lead，未经评审合入视为流程违例；
3. **SDK 重生成**：PR 内必须同时包含 `openapi.json` / `openapi.sha256` /
   前端 SDK 生成目录三者一致变更，并在 PR 描述记录 SDK 重生成 commit hash。

### 变更评审模板（复制至 PR 描述）

```markdown
## [contract] 变更说明

- **动机**：（为什么必须变更契约）
- **影响面**：（新增/修改/删除的路径、schema、错误码；是否破坏向后兼容）
- **后端实现**：（对应路由/模型 commit）
- **SDK 重生成**：`pnpm --filter api-sdk gen` 已执行，重生成 commit hash：<hash>
- **消费方确认**：（前端/Agent 接入方已知晓，@相关人）
- **评审**：Tech Lead @<name> ✔
```

## 生产环境注意

数据库角色（`edp_migrator` / `edp_app`）由迁移脚本在 dev/CI 创建；生产环境角色与密码由运维另行创建管理，不使用迁移内默认凭据。

## M1 冻结签署

| 项目 | 值 |
|---|---|
| 冻结基线 commit | _（T15 提交后回填）_ |
| 签署日期 | _待 M1 评审时填写_ |
| 签署人（Tech Lead） | _待 M1 评审时填写_ |
| 快照指纹（sha256 前 8 位） | _随签署时快照填写_ |
