import { QueryClientProvider } from "@tanstack/react-query";
import { message } from "antd";
import { EdpApiError } from "@edp/api-sdk";
import { errorSpec } from "@edp/shared";
import { RouterProvider } from "react-router-dom";
import { setTenantSuspendedNotifier } from "../features/auth/api";
import { queryClient } from "../lib/queryClient";
import { notifyTenantSuspended } from "../shell/TenantSuspendedBanner";
import { ThemeProvider } from "./providers/ThemeProvider";
import { router } from "./router";

// TENANT_SUSPENDED（13.8）：api-sdk 拦截器命中即点亮 AppLayout 内的常驻横幅。
setTenantSuspendedNotifier(() => notifyTenantSuspended());

function toastCacheError(error: unknown): void {
  // 仅兜底 API 错误；组件内异常等非 EdpApiError 不归全局 toast 管。
  if (!(error instanceof EdpApiError)) return;
  const spec = errorSpec(error.code);
  // banner=常驻横幅 / login=路由守卫跳登录 / page403=专属页面，各有专属机制，不弹 toast。
  if (spec.presentation === "banner" || spec.presentation === "login" || spec.presentation === "page403") {
    return;
  }
  void message.warning(spec.message);
}

// 全局兜底 toast：未被页面捕获的查询错误（页面级处理优先生效）。
queryClient.getQueryCache().subscribe((event) => {
  if (event.type === "updated" && event.action.type === "error") {
    toastCacheError(event.action.error);
  }
});

// mutation 错误同逻辑兜底：与 QueryCache 共用同一判定函数，零额外复杂度。
queryClient.getMutationCache().subscribe((event) => {
  if (event.type === "updated" && event.action.type === "error") {
    toastCacheError(event.action.error);
  }
});

export function AppMain() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>
  );
}
