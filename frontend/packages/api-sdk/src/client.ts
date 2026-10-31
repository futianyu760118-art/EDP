import type { components } from "./generated/schema";
import {
  backoffDelay,
  createSingleFlight,
  createTenantSuspendedHandler,
  parseRetryAfter,
  type EdpErrorBody,
} from "./interceptors";

type Schemas = components["schemas"];

export type TokenResponse = Schemas["TokenResponse"];
export type RefreshResponse = Schemas["RefreshResponse"];
export type MeResponse = Schemas["MeResponse"];

/** 附录 B.0 错误码 13 种 + 前端专用 NETWORK_ERROR（第 14 值）。 */
export type EdpErrorCode =
  | "VALIDATION_ERROR"
  | "UNAUTHENTICATED"
  | "FORBIDDEN"
  | "TENANT_FORBIDDEN"
  | "TENANT_SUSPENDED"
  | "GUARD_POLICY_DENIED"
  | "NOT_FOUND"
  | "METHOD_NOT_ALLOWED"
  | "CONFLICT"
  | "INVALID_TRANSITION"
  | "RATE_LIMITED"
  | "UPSTREAM_UNAVAILABLE"
  | "INTERNAL"
  | "NETWORK_ERROR";

export interface EdpApiErrorInit {
  status: number;
  code: EdpErrorCode;
  message: string;
  requestId?: string;
}

export class EdpApiError extends Error {
  readonly status: number;
  readonly code: EdpErrorCode;
  readonly requestId?: string;

  constructor(init: EdpApiErrorInit) {
    super(init.message);
    this.name = "EdpApiError";
    this.status = init.status;
    this.code = init.code;
    this.requestId = init.requestId;
  }
}

export interface ClientTokens {
  accessToken: string;
  refreshToken: string;
}

export interface EdpClientOptions {
  baseUrl: string;
  getAccessToken?: () => string | null | undefined;
  getRefreshToken?: () => string | null | undefined;
  setTokens?: (tokens: ClientTokens | null) => void;
  /** 会话失效（刷新失败/重放仍 401）回调：清 token 并跳登录由宿主决定。 */
  onUnauthorized?: () => void;
  /** 任一响应 error.code === TENANT_SUSPENDED 时回调（全局横幅，13.8）。 */
  onTenantSuspended?: () => void;
  fetchImpl?: typeof fetch;
  /** 退避 sleep 注入点（测试用），默认真实 setTimeout。 */
  sleep?: (ms: number) => Promise<void>;
  /** 429 自动重试上限，默认 3。 */
  maxRetries?: number;
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export interface EdpClient {
  request<T>(path: string, init?: RequestOptions): Promise<T>;
  get<T>(path: string, init?: RequestOptions): Promise<T>;
  post<T>(path: string, body?: unknown, init?: RequestOptions): Promise<T>;
  put<T>(path: string, body?: unknown, init?: RequestOptions): Promise<T>;
  delete<T>(path: string, init?: RequestOptions): Promise<T>;
  login(username: string, password: string, tenantSlug?: string): Promise<TokenResponse>;
  refresh(): Promise<RefreshResponse>;
  me(): Promise<MeResponse>;
  /** W1 无服务端登出端点：本地清 token + onUnauthorized（跳登录由宿主接线）。 */
  logout(): void;
}

const DEFAULT_MAX_RETRIES = 3;

const FALLBACK_CODE: Record<number, EdpErrorCode> = {
  400: "VALIDATION_ERROR",
  401: "UNAUTHENTICATED",
  403: "FORBIDDEN",
  404: "NOT_FOUND",
  405: "METHOD_NOT_ALLOWED",
  409: "CONFLICT",
  422: "INVALID_TRANSITION",
  429: "RATE_LIMITED",
  503: "UPSTREAM_UNAVAILABLE",
};

async function readErrorBody(resp: Response): Promise<unknown> {
  try {
    return await resp.json();
  } catch {
    return null; // 非 JSON 响应体：保留状态码 fallback。
  }
}

function apiErrorFrom(status: number, body: unknown): EdpApiError {
  let code: EdpErrorCode = FALLBACK_CODE[status] ?? "INTERNAL";
  let message = `请求失败（HTTP ${status}）`;
  let requestId: string | undefined;
  const err = (body as EdpErrorBody | null | undefined)?.error;
  if (err) {
    if (err.code) code = err.code as EdpErrorCode;
    if (err.message) message = err.message;
    requestId = err.request_id;
  }
  return new EdpApiError({ status, code, message, requestId });
}

async function parseBody<T>(resp: Response): Promise<T> {
  if (resp.status === 204) return undefined as T;
  const text = await resp.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

export function createClient(options: EdpClientOptions): EdpClient {
  const baseUrl = options.baseUrl.replace(/\/+$/, "");
  // 延迟解析全局 fetch（调用时取值）：宿主测试（MSW）可能在客户端创建后才打补丁。
  const doFetch: typeof fetch =
    options.fetchImpl ?? ((input, init) => fetch(input, init));
  const sleep: (ms: number) => Promise<void> =
    options.sleep ?? ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
  const maxRetries = options.maxRetries ?? DEFAULT_MAX_RETRIES;
  const tenantSuspended = createTenantSuspendedHandler(() =>
    options.onTenantSuspended?.(),
  );

  /** 直接 POST /auth/refresh（不走拦截器链，避免自触发 401 重放）。 */
  async function postRefresh(): Promise<{ tokens: ClientTokens; expiresIn: number }> {
    const current = options.getRefreshToken?.() ?? null;
    if (!current) {
      throw new EdpApiError({
        status: 401,
        code: "UNAUTHENTICATED",
        message: "缺少刷新令牌，请重新登录",
      });
    }
    let resp: Response;
    try {
      resp = await doFetch(`${baseUrl}/api/v1/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ refresh_token: current }),
      });
    } catch {
      throw new EdpApiError({
        status: 0,
        code: "NETWORK_ERROR",
        message: "网络错误，请检查网络连接后重试",
      });
    }
    if (!resp.ok) throw apiErrorFrom(resp.status, await readErrorBody(resp));
    const data = (await resp.json()) as {
      access_token?: string;
      refresh_token?: string;
      expires_in?: number;
    };
    if (!data.access_token) {
      throw new EdpApiError({ status: 500, code: "INTERNAL", message: "刷新响应缺少 access_token" });
    }
    const tokens = { accessToken: data.access_token, refreshToken: data.refresh_token ?? current };
    options.setTokens?.(tokens);
    return { tokens, expiresIn: data.expires_in ?? 0 };
  }

  /** 401 刷新单飞：并发 401 共享一次 refresh（13.9.2）。失败吞为 null 由调用方清理会话。 */
  const runRefresh = createSingleFlight(async (): Promise<ClientTokens | null> => {
    try {
      return (await postRefresh()).tokens;
    } catch {
      return null;
    }
  });

  async function request<T>(path: string, init: RequestOptions = {}): Promise<T> {
    const url = `${baseUrl}${path.startsWith("/") ? path : `/${path}`}`;
    const method = init.method ?? (init.body === undefined ? "GET" : "POST");
    const bodyText =
      init.body === undefined
        ? undefined
        : typeof init.body === "string"
          ? init.body
          : JSON.stringify(init.body);

    let authRetried = false;
    let attempt = 0;
    for (;;) {
      const headers: Record<string, string> = { Accept: "application/json", ...init.headers };
      if (bodyText !== undefined) headers["Content-Type"] = "application/json";
      const accessToken = options.getAccessToken?.() ?? null;
      if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

      let resp: Response;
      try {
        resp = await doFetch(url, { method, headers, body: bodyText, signal: init.signal });
      } catch {
        throw new EdpApiError({
          status: 0,
          code: "NETWORK_ERROR",
          message: "网络错误，请检查网络连接后重试",
        });
      }

      if (resp.status === 401) {
        // 仅受保护请求（携带过访问令牌）走刷新单飞重放；匿名 401（如登录失败）直接抛。
        if (accessToken && !authRetried && options.getRefreshToken) {
          authRetried = true;
          const tokens = await runRefresh();
          if (tokens) {
            options.setTokens?.(tokens);
            continue;
          }
        }
        if (accessToken) {
          options.setTokens?.(null);
          options.onUnauthorized?.();
        }
        throw apiErrorFrom(resp.status, await readErrorBody(resp));
      }

      if (resp.status === 429 && attempt < maxRetries) {
        const retryAfter = parseRetryAfter(resp.headers.get("Retry-After"));
        await sleep(backoffDelay(attempt, retryAfter));
        attempt += 1;
        continue;
      }

      if (resp.ok) {
        return parseBody<T>(resp);
      }

      // TENANT_SUSPENDED 横幅（13.8）：判定逻辑单点在 interceptors（可单测），
      // client 只把 (status, body) 喂给判定器——命中即回调 onTenantSuspended。
      const body = await readErrorBody(resp);
      tenantSuspended(resp.status, body);
      throw apiErrorFrom(resp.status, body);
    }
  }

  return {
    request,
    get: <T>(path: string, init: RequestOptions = {}) => request<T>(path, { ...init, method: "GET" }),
    post: <T>(path: string, body?: unknown, init: RequestOptions = {}) =>
      request<T>(path, { ...init, method: "POST", body }),
    put: <T>(path: string, body?: unknown, init: RequestOptions = {}) =>
      request<T>(path, { ...init, method: "PUT", body }),
    delete: <T>(path: string, init: RequestOptions = {}) =>
      request<T>(path, { ...init, method: "DELETE" }),
    login: (username: string, password: string, tenantSlug?: string) =>
      request<TokenResponse>("/api/v1/auth/login", {
        method: "POST",
        body: { username, password, ...(tenantSlug ? { tenant_slug: tenantSlug } : {}) },
      }),
    refresh: async () => {
      const { tokens, expiresIn } = await postRefresh();
      return { access_token: tokens.accessToken, expires_in: expiresIn };
    },
    me: () => request<MeResponse>("/api/v1/auth/me", { method: "GET" }),
    logout: () => {
      options.setTokens?.(null);
      options.onUnauthorized?.();
    },
  };
}
