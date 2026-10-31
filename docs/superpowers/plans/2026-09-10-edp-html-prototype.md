# EDP HTML Prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a self-contained, high-fidelity, clickable HTML prototype for the EDP data and evidence platform covering the full documented navigation.

**Architecture:** One standalone HTML document contains semantic markup, scoped CSS, deterministic mock data, client-side route state, and interaction handlers. A small view renderer maps route keys to page templates while shared shell components provide navigation, search, tenant context, drawers, modals, tabs, filters, and toast feedback.

**Tech Stack:** Native HTML5, CSS3, JavaScript; no runtime dependencies or network assets.

## Global Constraints

- 单个自包含 HTML 文件
- 原生 HTML、CSS、JavaScript，不引入未经项目确认的依赖
- 采用现代 SaaS 风格，同时保留 EDP 文档定义的企业级信息架构
- 不实现真实后端、鉴权、数据库或 API 请求；使用确定性 mock 数据模拟状态与交互
- 不添加代码注释
- 打开 HTML 后无需构建即可浏览

---

## Task 1: Create the standalone document shell

**Files:** `edp-prototype.html`

1. Create a complete HTML5 document with UTF-8 metadata, title `EDP 数据与证据平台`, and three top-level regions: app shell, overlay layer, toast region.
2. Add CSS variables for the documented colors, spacing, radii, typography, shadows, sidebar width, and topbar height.
3. Add responsive rules for widths below 1100px and 760px.
4. Add the shell markup for topbar, sidebar, breadcrumb, main content, drawer, modal, command/search overlay, and toast container.
5. Add the JavaScript bootstrap that renders `/admin/overview` on load and handles `hashchange`.

**Verification:** Open `edp-prototype.html` directly in a browser; the page must render without console errors and show the EDP shell.

## Task 2: Implement shared mock data and utility primitives

**Files:** `edp-prototype.html`

1. Define deterministic arrays for tenants, objects, events, evidence, cases, actions, incidents, adapters, audit records, traces, drills, and quota usage.
2. Define route metadata grouped under CASES, ADMIN, and TENANTS with the documented labels and route keys.
3. Implement utilities for status labels/classes, risk labels/classes, date formatting, IDs, escaping text, and simple SVG/chart drawing.
4. Implement application state for current route, current tenant, active filters, visible columns, selected tab, and drawer/modal state.
5. Ensure all mock data is scoped to the selected tenant where applicable.

**Verification:** Use the browser console or temporary UI interactions to switch tenants and confirm rendered tenant names and scoped counts change consistently.

## Task 3: Implement global shell interactions

**Files:** `edp-prototype.html`

1. Render grouped sidebar navigation with active route highlighting.
2. Render topbar brand, breadcrumb, global search trigger, tenant selector, refresh control, and user menu.
3. Implement tenant switching in a modal/popover and update route content after selection.
4. Implement global search with keyboard shortcut Ctrl/Cmd+K, categorized results, empty state, and route navigation on result click.
5. Implement sidebar collapse behavior and responsive mobile navigation.
6. Implement toast feedback and close behavior for drawers, modals, and overlays.

**Verification:** Click every sidebar group, switch tenants, open/close search, press Escape, collapse navigation, and confirm the URL hash and active navigation update.

## Task 4: Implement reusable list/detail patterns

**Files:** `edp-prototype.html`

1. Build a reusable page header with title, description, status summary, and primary action.
2. Build reusable filter bar with search input, select filters, removable filter pills, reset action, and separate display-options panel.
3. Build reusable data table with column definitions, sorting, empty state, row click handling, and visible-column toggles.
4. Build reusable detail drawer with tabs for overview, history, related records, and raw data.
5. Build reusable modal form, confirmation dialog, progress stepper, health card, metric card, badge, timeline, and evidence verification control.
6. Make controls keyboard reachable and add visible focus styles.

**Verification:** Exercise filtering, pill removal, column toggling, sorting, row details, tabs, drawer close, modal confirm/cancel, and evidence verification.

## Task 5: Implement CASES pages and evidence-chain workflow

**Files:** `edp-prototype.html`

1. Implement `#/cases` with risk/status filters, case table, progress indicators, and row navigation.
2. Implement `#/cases/:id` with case summary, lifecycle stepper, horizontal evidence chain, clickable nodes, evidence tabs, decision history, events, and actions.
3. Make evidence checksum verification update the selected evidence badge and show a toast.
4. Make chain nodes open the corresponding detail drawer.
5. Include a clear demonstration path from source event through decision and action to verified event.

**Verification:** Navigate from case list to case detail, click each lineage node, switch tabs, verify checksum, and return to list.

## Task 6: Implement ADMIN pages

**Files:** `edp-prototype.html`

1. Implement overview with coverage, Outbox backlog, today’s sync volume, checksum failures, PostgreSQL HA, worker health, and backup cards.
2. Implement registry, events, evidence, decisions, actions, quality, audit, adapters, systems, tools, memory, traces, and drills pages using the shared list/detail patterns.
3. Registry/events/evidence rows must open meaningful drawers with IDs, source, timestamps, related records, and technical metadata.
4. Actions must show all nine statuses, allowed next actions, and disabled Human-Only controls with an explanation.
5. Quality must show coverage/quality cards, heatmap-like rule matrix, incidents list, and incident detail workflow.
6. Audit must show HUMAN/AI/SERVICE actor types, GUARD_DENIED emphasis, and a permissions matrix tab.
7. Adapters and systems must show Mock/Real mode, sync history, primary/replica state, replication lag, Outbox, workers, backups, and alert channels.
8. Traces must show a timeline/DAG-like tool-call sequence; drills must show HA failover, PITR, and tenant recovery records.

**Verification:** Visit every ADMIN route; confirm no blank route exists, every table has mock rows or a designed empty state, and all key details open.

## Task 7: Implement TENANTS pages and lifecycle controls

**Files:** `edp-prototype.html`

1. Implement `#/tenants` with tenant list, plan/status badges, usage sparklines, and health indicators.
2. Implement `#/tenants/new` with a four-step provisioning wizard: basics, admin, quota, confirmation.
3. Implement tenant detail with lifecycle progress, quota summary, members summary, usage summary, and suspend/resume/cancel actions.
4. Implement members page with role badges, invitation modal, enable/disable controls, and audit toast.
5. Implement quotas page with the six documented dimensions, editable values, 80% warning and 100% read-only states.
6. Implement usage page with metric cards and inline SVG trends for API calls, events, storage, and rate limiting.
7. Keep cancellation and suspension actions mock-only, with confirmation dialogs and visible status updates.

**Verification:** Complete the provisioning wizard, edit a quota, trigger a warning state, suspend/resume a tenant, and confirm list/detail status consistency.

## Task 8: Implement error and status states

**Files:** `edp-prototype.html`

1. Implement login, 403, 404, and 500 views accessible from a small user/status menu or direct hash routes.
2. Implement suspended and cancelled tenant status pages with the documented copy and restricted actions.
3. Show request ID, retry behavior, and actionable next steps in error views.
4. Ensure error pages preserve enough shell context to explain tenant state without exposing data.

**Verification:** Navigate to each error route and confirm correct status styling, actions, and return navigation.

## Task 9: Polish visual fidelity and accessibility

**Files:** `edp-prototype.html`

1. Review spacing, typography, color contrast, borders, shadows, and component alignment against the approved design document.
2. Replace decorative gradients with restrained surfaces; reserve color for semantic states and primary actions.
3. Add reduced-motion handling through `prefers-reduced-motion`.
4. Add `aria-label`, dialog roles, live-region behavior for toast, and table/header semantics.
5. Ensure long IDs and checksum values wrap or truncate safely without breaking layout.
6. Verify the prototype works without network access, external fonts, images, or libraries.

**Verification:** Open in offline mode, resize to desktop/tablet/mobile widths, keyboard-tab through major controls, and inspect browser console for errors.

## Task 10: Final end-to-end verification

**Files:** `edp-prototype.html`

1. Start a local static server using `python -m http.server 8000` from the workspace root.
2. Visit the prototype and execute the route checklist: CASES (2), ADMIN (14), TENANTS (6), and error/status routes.
3. Validate the core flows: global search, tenant switch, case lineage, evidence verify, action transition, quality incident, provisioning wizard, quota save, suspend/resume.
4. Run repository-appropriate lint/typecheck commands if a frontend package is added; for a standalone HTML file, use browser console verification and a script syntax check with `node --check` against the extracted script if needed.
5. Inspect `git diff` and `git status --short`; keep only the prototype and approved design/plan files changed.

**Expected result:** Every documented major navigation item is reachable, core interactions visibly respond, and the standalone HTML opens offline without errors.
