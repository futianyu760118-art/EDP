import { Navigate, createBrowserRouter, type RouteObject } from "react-router-dom";
import { ActionsPage } from "../features/decisions_actions/ActionsPage";
import { DecisionsPage } from "../features/decisions_actions/DecisionsPage";
import { DrillsPage } from "../features/drills/DrillsPage";
import { MemoryPage } from "../features/memory/MemoryPage";
import { ToolsPage } from "../features/tools/ToolsPage";
import { TracesPage } from "../features/traces/TracesPage";
import { AdaptersPage } from "../features/adapters/AdaptersPage";
import { AuditPage } from "../features/audit/AuditPage";
import { CasesPage } from "../features/cases/CasesPage";
import { CaseDetailPage } from "../features/cases/CaseDetailPage";
import { LoginPage } from "../features/auth/LoginPage";
import { EventsPage } from "../features/events/EventsPage";
import { EvidencePage } from "../features/evidence/EvidencePage";
import { HealthPage } from "../features/health/HealthPage";
import { ForbiddenPage, NotFoundPage } from "../features/placeholder/PlaceholderPage";
import { RouteErrorBoundary } from "../features/placeholder/RouteErrorBoundary";
import { OverviewPage } from "../features/overview/OverviewPage";
import { ProfilePage } from "../features/profile/ProfilePage";
import { QualityPage } from "../features/quality/QualityPage";
import { RegistryPage } from "../features/registry/RegistryPage";
import { SearchPage } from "../features/search/SearchPage";
import { TenantDetailPage } from "../features/tenants/TenantDetailPage";
import { TenantsPage } from "../features/tenants/TenantsPage";
import { AppLayout } from "../shell/AppLayout";
import { RedirectIfAuthed, RequireAuth, RequireRoles, ROUTE_ROLE_GUARDS } from "./guards";

export interface RouteHandle {
  title: string;
}

/** 13.3 路由表全量：除 /login 外全部落在壳层布局内；根 errorElement 收口渲染异常（EDP-601）。 */
export const routes: RouteObject[] = [
  {
    errorElement: <RouteErrorBoundary />,
    children: [
      {
        path: "/login",
        element: (
          <RedirectIfAuthed>
            <LoginPage />
          </RedirectIfAuthed>
        ),
        handle: { title: "登录" } satisfies RouteHandle,
      },
      { path: "/", element: <Navigate to="/admin/overview" replace /> },
      {
        element: (
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        ),
        children: [
          {
            path: "admin/overview",
            element: <OverviewPage />,
            handle: { title: "运营总览" } satisfies RouteHandle,
          },
          {
            path: "admin/registry",
            element: <RegistryPage />,
            handle: { title: "业务对象" } satisfies RouteHandle,
          },
          {
            path: "admin/events",
            element: <EventsPage />,
            handle: { title: "事件流" } satisfies RouteHandle,
          },
          {
            path: "admin/evidence",
            element: <EvidencePage />,
            handle: { title: "证据库" } satisfies RouteHandle,
          },
          {
            path: "admin/quality",
            element: <QualityPage />,
            handle: { title: "数据质量" } satisfies RouteHandle,
          },
          {
            path: "admin/audit",
            element: <AuditPage />,
            handle: { title: "审计日志" } satisfies RouteHandle,
          },
          {
            path: "admin/adapters",
            element: <AdaptersPage />,
            handle: { title: "适配器管理" } satisfies RouteHandle,
          },
          {
            path: "admin/systems",
            element: <HealthPage />,
            handle: { title: "系统健康" } satisfies RouteHandle,
          },
          {
            path: "profile",
            element: <ProfilePage />,
            handle: { title: "个人设置" } satisfies RouteHandle,
          },
          {
            path: "tenants",
            element: (
              <RequireRoles allow={ROUTE_ROLE_GUARDS["/tenants"]}>
                <TenantsPage />
              </RequireRoles>
            ),
            handle: { title: "租户管理" } satisfies RouteHandle,
          },
          {
            path: "tenants/:tenant_id",
            element: (
              <RequireRoles allow={ROUTE_ROLE_GUARDS["/tenants"]}>
                <TenantDetailPage />
              </RequireRoles>
            ),
            handle: { title: "租户详情" } satisfies RouteHandle,
          },
          {
            path: "cases",
            element: <CasesPage />,
            handle: { title: "闭环案例" } satisfies RouteHandle,
          },
          {
            path: "cases/:case_id",
            element: <CaseDetailPage />,
            handle: { title: "案例详情" } satisfies RouteHandle,
          },
          {
            path: "decisions",
            element: <DecisionsPage />,
            handle: { title: "决策" } satisfies RouteHandle,
          },
          {
            path: "actions",
            element: <ActionsPage />,
            handle: { title: "行动" } satisfies RouteHandle,
          },
          {
            path: "admin/tools",
            element: <ToolsPage />,
            handle: { title: "Agent 工具" } satisfies RouteHandle,
          },
          {
            path: "admin/traces",
            element: <TracesPage />,
            handle: { title: "Trace 检索" } satisfies RouteHandle,
          },
          {
            path: "admin/memory",
            element: <MemoryPage />,
            handle: { title: "候选记忆" } satisfies RouteHandle,
          },
          {
            path: "admin/drills",
            element: (
              <RequireRoles allow={ROUTE_ROLE_GUARDS["/admin/drills"]}>
                <DrillsPage />
              </RequireRoles>
            ),
            handle: { title: "演练回放" } satisfies RouteHandle,
          },
          {
            path: "search",
            element: <SearchPage />,
            handle: { title: "全局搜索" } satisfies RouteHandle,
          },
          {
            path: "403",
            element: <ForbiddenPage />,
            handle: { title: "无权访问" } satisfies RouteHandle,
          },
          {
            path: "404",
            element: <NotFoundPage />,
            handle: { title: "页面未找到" } satisfies RouteHandle,
          },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
];

export const router = createBrowserRouter(routes);
