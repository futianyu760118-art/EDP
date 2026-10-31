import type { ReactElement } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useIsLoggedIn, useSessionStore } from "../features/auth/session-store";

/** 无 session → /login?redirect=（回跳目标含查询串）。 */
export function RequireAuth({ children }: { children: ReactElement }) {
  const isLoggedIn = useIsLoggedIn();
  const location = useLocation();
  if (!isLoggedIn) {
    const redirect = encodeURIComponent(`${location.pathname}${location.search}`);
    return <Navigate to={`/login?redirect=${redirect}`} replace />;
  }
  return children;
}

/** 已登录访问 /login → 直达总览。 */
export function RedirectIfAuthed({ children }: { children: ReactElement }) {
  const isLoggedIn = useIsLoggedIn();
  if (isLoggedIn) return <Navigate to="/admin/overview" replace />;
  return children;
}

/**
 * 路由角色守卫表（EDP-601，对齐后端权限矩阵 + T3 收紧后的 GET /admin/drills）：
 * 租户管理平台面（列表/详情）仅 PLATFORM_ADMIN；演练回放 quality:run = ADMIN+
 * （MANAGER/ANALYST 跳 /403）；其余业务页维持「登录即可」（13.8 后端 RBAC 兜底）。
 */
export const ROUTE_ROLE_GUARDS = {
  "/tenants": ["PLATFORM_ADMIN"],
  "/admin/drills": ["PLATFORM_ADMIN", "ADMIN"],
} as const satisfies Record<string, readonly string[]>;

/**
 * 角色守卫（无权限 → /403）。角色来源：session store 登录即持久化的
 * user.roles + user.is_platform_admin（B.1 TokenResponse，无需另拉 /auth/me）；
 * 平台管理员通行（对齐 13.8 canSeeGroup 语义）。
 */
export function RequireRoles({
  allow,
  children,
}: {
  allow: readonly string[];
  children: ReactElement;
}) {
  const user = useSessionStore((s) => s.user);
  const allowed =
    user != null && (user.is_platform_admin || allow.some((role) => user.roles.includes(role)));
  if (!allowed) return <Navigate to="/403" replace />;
  return children;
}
