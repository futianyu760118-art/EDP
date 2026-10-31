import { expect, test } from "@playwright/test";
import {
  API_V1,
  ADMIN_PASS,
  ADMIN_USER,
  bearerHeaders,
  loginViaAPI,
  loginViaUI,
} from "./helpers";

/**
 * M4 闭环叙事 E2E（W6 T10，EDP-602）——seed 场景 2（订单 SO-2026-00123 关键料
 * 缺失，P1）主线：登录 → 总览风险 → 案例证据链（追溯率断言）→ HITL 审批 →
 * 行动执行 → VERIFIED → 中枢回流 action.verified → 总览时间线闭环条目。
 *
 * 操作人 = admin（非 demo 叙事的 manager1，留痕：13.8 智能闭环导航组仅
 * PLATFORM_ADMIN/ADMIN 可见——manager1（MANAGER）虽有 decide/execute 权限但
 * 无导航入口；admin 为 HUMAN 且 ADMIN 角色持 decision:decide + action:execute，
 * Human-Only 边语义不受影响）。
 *
 * 选择器全 data-dom-id（967 锚点子集）；叙事对齐 backend M4 验收
 * test_m4_acceptance ①（浏览器视角重演）。
 *
 * 裁剪决策（docstring 留痕）：
 * 1. 行动创建无 UI 入口——风险抽屉「创建任务」为 W3 占位 stub（onClick 仅
 *    toast），案例详情行动区只读——故行动经 POST /actions API 创建（admin
 *    凭据），创建后的九态状态机（含 APPROVED→EXECUTING / COMPLETED→VERIFIED
 *    两条 Human-Only 边）全程经行动页抽屉按钮 UI 驱动；
 * 2. 决策意见落证为「决策记录不自动落证」契约的最小补建（W4-10 口径）——
 *    审批后经 POST /evidence 补 DECISION 层证据节点，使案例详情证据链呈现
 *    Result→Decision→Evidence→Source 四层全链（与 M4 验收同款）；
 * 3. EBMS 待办清零断言属后端验收 ⑤ 已覆盖的 API 口径，E2E 不重复；闭环
 *    「回流」段以 POST /events/batch 回流一条 action.verified 事件（幂等键
 *    含时间戳，重跑不撞），断言总览事件时间线出现闭环条目。
 *
 * 前置（README 复跑手册）：真栈 api 起在 E2E_API_BASE（默认
 * http://localhost:18000）+ `demo.cli seed --reset` 干净基线 + preview 前端
 * 构建期 VITE_API_BASE 指向同一 api。
 */

const API_BASE = process.env.E2E_API_BASE ?? "http://localhost:18000";
const ORDER_NO = "SO-2026-00123";
/** 行动六步（9 态状态机主线边；EXECUTING/VERIFIED 为 Human-Only 边）。 */
const TRANSITION_CHAIN = [
  "ASSIGNED",
  "ACCEPTED",
  "APPROVED",
  "EXECUTING",
  "COMPLETED",
  "VERIFIED",
] as const;

test("M4 闭环：总览风险 → 案例证据链（全链 VALID）→ HITL 审批 → 行动六步 VERIFIED → 回流时间线", async ({
  page,
  request,
}) => {
  // ---- 幕前（API）：定位 seed 场景 2 案例 + admin 会话 ----
  const adminToken = await loginViaAPI(request, API_BASE, ADMIN_USER, ADMIN_PASS);
  const admin = bearerHeaders(adminToken);
  const casesResp = await request.get(`${API_BASE}${API_V1}/decisions/cases?status=OPEN`, {
    headers: admin,
  });
  expect(casesResp.ok(), "待决案例列表不可达：seed 是否已跑？").toBeTruthy();
  const openCases = (await casesResp.json()).items as Array<{ case_id: string; question: string }>;
  const seedCase = openCases.find((item) => item.question.includes(ORDER_NO));
  expect(seedCase, `待决列表未见 ${ORDER_NO} 案例：请先 demo.cli seed --reset`).toBeDefined();
  const caseId = seedCase!.case_id;

  // ---- ① 登录 → 总览（默认跳转）----
  await loginViaUI(page, ADMIN_USER, ADMIN_PASS);
  await expect(page.locator('[data-dom-id="overview-risk-list"]')).toBeVisible();

  // ---- ② 总览风险叙事：P1 风险卡 → 抽屉（受影响对象/时间线/关联证据）----
  const riskCards = page.locator('[data-dom-id="risk-card"]');
  await expect(riskCards.first()).toBeVisible();
  await riskCards.first().click();
  await expect(page.locator('[data-dom-id="risk-drawer"]')).toBeVisible();
  await expect(page.locator('[data-dom-id="risk-drawer-object"]')).toBeVisible();
  await expect(page.locator('[data-dom-id="risk-drawer-evidence"]')).toBeVisible();
  await page.locator('[data-dom-id="risk-drawer-close"]').click();
  await expect(page.locator('[data-dom-id="risk-drawer"]')).toBeHidden();

  // ---- ③ 闭环案例详情：问题卡 + 关联风险联动 ----
  await page.locator('[data-dom-id="nav-cases"]').click();
  await expect(page.locator('[data-dom-id="cases-page"]')).toBeVisible();
  await page.locator(`[data-dom-id="cases-view-${caseId}"]`).click();
  await expect(page.locator('[data-dom-id="case-detail-page"]')).toBeVisible();
  await expect(page.locator('[data-dom-id="case-detail-question"]')).toContainText(ORDER_NO);
  await page.locator('[data-dom-id="case-detail-risk-btn"]').click();
  await expect(page.locator('[data-dom-id="risk-drawer"]')).toBeVisible();
  await page.locator('[data-dom-id="risk-drawer-close"]').click();

  // ---- ④ 证据链追溯率断言：EVIDENCE 层每条证据逐条校验 → 全部 VALID ----
  const evidenceLayer = page.locator('[data-dom-id="case-chain-layer-EVIDENCE"]');
  await expect(evidenceLayer).toBeVisible();
  const evidenceNodes = evidenceLayer.locator('[data-dom-id^="case-chain-node-"]');
  const nodeCount = await evidenceNodes.count();
  expect(nodeCount).toBeGreaterThan(0);
  for (let i = 0; i < nodeCount; i += 1) {
    const node = evidenceNodes.nth(i);
    await node.locator('[data-dom-id="case-chain-verify-btn"]').click();
    await expect(node.locator('[data-dom-id="case-chain-verify-state"]')).toContainText("VALID");
  }
  // 追溯率 100%：校验后无残留「校验」按钮（未验证节点为 0）
  await expect(evidenceLayer.locator('[data-dom-id="case-chain-verify-btn"]')).toHaveCount(0);

  // ---- ⑤ HITL 审批（Human-Only）：决策页 → 审批表单 → EXPEDITE ----
  await page.locator('[data-dom-id="nav-decisions"]').click();
  await expect(page.locator('[data-dom-id="decisions-page"]')).toBeVisible();
  const decisionRow = page.locator(`[data-dom-id="decisions-row-${caseId}"]`);
  await expect(decisionRow).toBeVisible();
  await page.locator(`[data-dom-id="decisions-approve-${caseId}"]`).click();
  await expect(page.locator('[data-dom-id="decision-form"]')).toBeVisible();
  await expect(page.locator('[data-dom-id="decision-human-only"]')).toBeVisible();
  await page.locator('[data-dom-id="decision-option-EXPEDITE"]').check();
  await page
    .locator('[data-dom-id="decision-form-comment"]')
    .fill("E2E 闭环：同意加急采购，优先保交付");
  await page.locator('[data-dom-id="modal-form-submit"]').click();
  await expect(decisionRow).toBeHidden();

  // ---- ⑥ 幕间（API）：决策意见落证（DECISION 层链节点，W4-10 最小补建）+ 建行动 ----
  const caseDetailResp = await request.get(`${API_BASE}${API_V1}/decisions/cases/${caseId}`, {
    headers: admin,
  });
  expect(caseDetailResp.ok()).toBeTruthy();
  const caseDetail = (await caseDetailResp.json()) as { event: { event_id: string } };
  const eventResp = await request.get(`${API_BASE}${API_V1}/events/${caseDetail.event.event_id}`, {
    headers: admin,
  });
  expect(eventResp.ok()).toBeTruthy();
  const objectId = ((await eventResp.json()) as { object_id: string }).object_id;

  const decisionEvidence = await request.post(`${API_BASE}${API_V1}/evidence`, {
    headers: admin,
    data: {
      source_system: "ebms",
      source_record_id: `decision:${caseId}`,
      object_id: objectId,
      snapshot: { comment: "E2E 闭环：同意加急采购，优先保交付" },
      captured_at: new Date().toISOString(),
      links: [{ ref_type: "DECISION", ref_id: caseId }],
    },
  });
  expect(decisionEvidence.status(), "决策意见落证失败").toBe(201);

  const actionResp = await request.post(`${API_BASE}${API_V1}/actions`, {
    headers: admin,
    data: {
      case_id: caseId,
      title: "加急采购物料X 1000 件（E2E）",
      action_type: "expedite_purchase",
      owner: "procurement_zhang",
      owner_role: "PROCUREMENT",
    },
  });
  expect(
    actionResp.status(),
    "创建行动失败（裁剪决策①：UI 无建行动入口，API 建后 UI 驱动状态机）",
  ).toBe(201);
  const action = (await actionResp.json()) as { action_id: string; status: string };
  const actionId = action.action_id;
  expect(action.status).toBe("PROPOSED");

  // ---- ⑦ 行动执行：行动页抽屉六步到 VERIFIED（UI 状态机，轮询等待 UI 更新）----
  await page.goto(`/actions?case_id=${caseId}`);
  const actionRow = page.locator(`[data-dom-id="actions-row-${actionId}"]`);
  await expect(actionRow).toBeVisible();
  await page.locator(`[data-dom-id="actions-detail-${actionId}"]`).click();
  const drawer = page.locator('[data-dom-id="action-drawer"]');
  await expect(drawer).toBeVisible();

  for (const toStatus of TRANSITION_CHAIN) {
    const transitionBtn = page.locator(`[data-dom-id="transition-btn-${toStatus}"]`);
    await expect(transitionBtn, `等待转移按钮 ${toStatus} 出现（抽屉按 allowed_to 重渲染）`).toBeVisible();
    await transitionBtn.click();
    await expect(page.locator('[data-dom-id="transition-modal"]')).toBeVisible();
    // Human-Only 边（EXECUTING/VERIFIED）：确认弹窗带 Human-Only 标注（HITL 留痕）
    if (toStatus === "EXECUTING" || toStatus === "VERIFIED") {
      await expect(page.locator('[data-dom-id="transition-modal-human-only"]')).toBeVisible();
    }
    await page.locator('[data-dom-id="transition-comment"]').fill(`E2E 转移：${toStatus}`);
    await page.locator('[data-dom-id="modal-form-submit"]').click();
    await expect(page.locator('[data-dom-id="action-drawer-status"]')).toContainText(toStatus);
  }
  // 终态断言：VERIFIED 无出边 + 验证人回填
  await expect(page.locator('[data-dom-id="action-drawer-transitions"]')).toContainText("终态");
  await expect(page.locator('[data-dom-id="action-drawer-meta"]')).toContainText("验证人");
  await page.locator('[data-dom-id="action-drawer-close"]').click();
  await expect(drawer).toBeHidden();

  // ---- ⑧ 案例详情回看：四层证据链全链 + 行动卡 VERIFIED ----
  await page.goto(`/cases/${caseId}`);
  await expect(page.locator(`[data-dom-id="case-action-${actionId}"]`)).toContainText("VERIFIED");
  await expect(page.locator('[data-dom-id="case-chain-layer-RESULT"]')).toBeVisible();
  await expect(page.locator('[data-dom-id="case-chain-layer-DECISION"]')).toBeVisible();
  await expect(page.locator('[data-dom-id="case-chain-layer-EVIDENCE"]')).toBeVisible();
  await expect(page.locator('[data-dom-id="case-chain-layer-SOURCE"]')).toBeVisible();

  // ---- ⑨ 回流：action.verified 事件 → 总览时间线闭环条目 ----
  const reflowResp = await request.post(`${API_BASE}${API_V1}/events/batch`, {
    headers: bearerHeaders(adminToken, {
      "Idempotency-Key": `e2e-closed-loop:${caseId}:${Date.now()}`,
    }),
    data: {
      events: [
        {
          event_type: "action.verified",
          object_id: objectId,
          source_system: "edp",
          occurred_at: new Date().toISOString(),
          actor_type: "SERVICE",
          actor_id: "edp",
          result_type: "ACTION",
          data: {
            order_no: ORDER_NO,
            action_id: actionId,
            summary: "行动已验证：加急采购物料X缺口闭环（E2E）",
          },
        },
      ],
    },
  });
  expect(reflowResp.ok(), "回流 action.verified 失败").toBeTruthy();

  await page.goto("/admin/overview");
  await expect(page.locator('[data-dom-id="overview-events-list"]')).toBeVisible();
  await expect(page.locator('[data-dom-id="overview-events-list"]')).toContainText("action.verified");
});
