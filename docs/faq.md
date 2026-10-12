# EDP FAQ（W6 归档，EDP-035）

**Q1 前端页面数据是假的？**
默认 MSW mock（`VITE_USE_MSW=1`）；真模式置 `VITE_USE_MSW=0` 并配 `VITE_API_BASE`（E2E 用 `.env.e2e` 同源构建）。

**Q2 `make seed-demo` 后页面数据变了？**
seed 幂等但 `--reset` 会清场重建（案例状态复位）；`--anchor ISO` 固定时间文本（视觉基线用）。

**Q3 切换租户后数据没变？**
租户切换弹窗会清空全站 query 缓存并重拉（13.8）；若用 API Key 会话需重签。平台 ADMIN 经 `POST /tenants/{id}/context` 切换，SUSPENDED 目标拒绝。

**Q4 前端测试偶发超时？**
宿主满载（Docker+多服务）下用 `--maxWorkers=2 --testTimeout=60000`（Makefile 已固化）；单跑恒绿为已知 flake。

**Q5 E2E 本地怎么跑？**
见 `frontend/apps/web/e2e/README.md`：起栈→seed→`build --mode e2e`→preview(4173)→`pnpm --filter web e2e`；视觉基线 `pnpm e2e:visual`。

**Q6 视觉快照 CI 失败怎么办？**
确认是真实 UI 偏差还是环境差异（win32/linux 基线各持）；偏差经 PR 评审后 `--update-snapshots` 更新并入库。

**Q7 409 TASK_CONFLICT 是什么？**
同 task_type 已有任务在执行（advisory lock 互斥，多副本安全）；等当前任务结束或查 ops.tasks。

**Q8 限流 429 太多怎么演示/压测？**
平台面 PATCH 配额临时提额（reason 必填、审计留痕、测后恢复）；压测先例 100→20000。

**Q9 Redis 为什么没上？**
W6 压测结论：P95 全达标、峰值 46.9rps 无热点租户形态 → 维持单副本语义；决策终节见 `docs/redis-evaluation.md` §7。

**Q10 覆盖率/召回率怎么算？**
覆盖率=quality coverage（已接入/注册对象）；召回率=十场景期望（P0/P1）vs 实测（放大实体排除）；一键 `make ops-report`。

**Q11 演练记录在哪？**
`deploy/drills/drill-records.json` + 前端演练回放页；手册见 `docs/drill-handbook.md`。

**Q12 契约变更流程？**
后端导出 → contracts/ 快照 + sha256 → api-sdk regen → `make contract-gate`；冻结后变更须 PR 评审（EDP-007）。

---

## V1.2 治理与事实层（2026-10 迭代）

- 数据准入状态机在哪？governance.admission_records（15 态 A1–A4）；审核经
  /governance/admission/{id}/source-review|management-review|archive
  （Human-Only，admission:review 权限）；worker 每 60s 自动机器预审
  （CLASSIFIED→SOURCE_REVIEW）。
- 数据四层在哪看？RAW=governance.raw_records（先留存后处理）；OFFICIAL
  标记在 master.business_objects.layer_status（CURATED/ARCHIVED）+ 血缘
  governance.lineage。
- 为什么 tools 读不到数据？official_only 缺省 true——对象须完成准入审核
  （OFFICIAL/ARCHIVED）；调试可传 official_only=false（过渡期开关）。
- 指标口径在哪定义？/metrics（Metric Registry，版本化生效区间）；EBMS
  报表经 registry（前端零公式）。AEOS 经营窗口（上月16~当月15）经
  /periods/aeos。
- CSV 导入？POST /admin/ingest/file（body=CSV 文本；列 object_type/
  source_id/occurred_at + payload 列，adapters:write）。
