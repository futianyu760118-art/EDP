import { create } from "zustand";
import { persist } from "zustand/middleware";

export const SESSION_STORAGE_KEY = "edp-session";

export interface SessionUser {
  username: string;
  display_name?: string;
  roles: string[];
  is_platform_admin: boolean;
}

export interface SessionTenant {
  slug: string;
  name: string;
  plan?: string;
  status: string;
}

/** 附录 B.1 TokenResponse（display_name/plan 为扩展位，W1 后端可不返回）。 */
export interface AuthTokenResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  tenant: {
    tenant_id: string;
    slug: string;
    name: string;
    status: string;
    plan?: string;
  };
  user: {
    user_id: string;
    username: string;
    display_name?: string;
    roles: string[];
    is_platform_admin: boolean;
  };
}

interface SessionState {
  accessToken: string | null;
  refreshToken: string | null;
  user: SessionUser | null;
  tenant: SessionTenant | null;
  setSession: (resp: AuthTokenResponse) => void;
  setTenant: (tenant: SessionTenant) => void;
  updateTokens: (tokens: { accessToken: string; refreshToken: string }) => void;
  clearSession: () => void;
}

export const useSessionStore = create<SessionState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      tenant: null,
      setSession: (resp) =>
        set({
          accessToken: resp.access_token,
          refreshToken: resp.refresh_token,
          user: {
            username: resp.user.username,
            display_name: resp.user.display_name,
            roles: resp.user.roles,
            is_platform_admin: resp.user.is_platform_admin,
          },
          tenant: {
            slug: resp.tenant.slug,
            name: resp.tenant.name,
            plan: resp.tenant.plan,
            status: resp.tenant.status,
          },
        }),
      setTenant: (tenant) => set({ tenant }),
      updateTokens: (tokens) =>
        set({ accessToken: tokens.accessToken, refreshToken: tokens.refreshToken }),
      clearSession: () =>
        set({ accessToken: null, refreshToken: null, user: null, tenant: null }),
    }),
    {
      name: SESSION_STORAGE_KEY,
      partialize: (state) => ({
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        user: state.user,
        tenant: state.tenant,
      }),
    },
  ),
);

export const useIsLoggedIn = () => useSessionStore((s) => Boolean(s.accessToken));
