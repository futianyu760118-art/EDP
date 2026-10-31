import { isRouteErrorResponse, useRouteError } from "react-router-dom";
import { ForbiddenPage, NotFoundPage, ServerErrorPage } from "./PlaceholderPage";

/** useRouteError 归一为 HTTP 状态码：数字 / RR ErrorResponse / Response / 带 status 的 Error。 */
function statusOf(error: unknown): number | null {
  if (typeof error === "number") return error;
  if (isRouteErrorResponse(error)) return error.status;
  if (error instanceof Response) return error.status;
  if (
    error instanceof Error &&
    "status" in error &&
    typeof (error as { status?: unknown }).status === "number"
  ) {
    return (error as { status: number }).status;
  }
  return null;
}

/**
 * 路由级错误边界（EDP-601，挂 router 根 errorElement）：404 → NotFoundPage、
 * 403 → ForbiddenPage，其余（含渲染异常/500）默认 ServerErrorPage。
 */
export function RouteErrorBoundary() {
  const status = statusOf(useRouteError());
  if (status === 404) return <NotFoundPage />;
  if (status === 403) return <ForbiddenPage />;
  return <ServerErrorPage />;
}
