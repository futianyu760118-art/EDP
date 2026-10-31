import { createClient } from "@edp/api-sdk";
import { useSessionStore } from "./session-store";

let notifyTenantSuspended: () => void = () => {};

/** W1 占位：由 App 根（app/main.tsx）挂 message.warning，T22+ 换全局横幅。 */
export function setTenantSuspendedNotifier(notifier: () => void): void {
  notifyTenantSuspended = notifier;
}

/** api-sdk 客户端单例（EDP-105）：token 读写接 session store，会话失效交由路由守卫跳登录。 */
export const apiClient = createClient({
  // VITE_API_BASE=''（web 容器构建）= 同源相对路径，经 nginx /api 反代；未设置（本地 dev）= 直连本地 api
  baseUrl: import.meta.env.VITE_API_BASE ?? "http://localhost:8000",
  getAccessToken: () => useSessionStore.getState().accessToken,
  getRefreshToken: () => useSessionStore.getState().refreshToken,
  setTokens: (tokens) => {
    if (tokens) {
      useSessionStore.getState().updateTokens(tokens);
    } else {
      useSessionStore.getState().clearSession();
    }
  },
  onUnauthorized: () => useSessionStore.getState().clearSession(),
  onTenantSuspended: () => notifyTenantSuspended(),
});
