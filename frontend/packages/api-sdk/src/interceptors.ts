/**
 * 13.9.2 拦截器语义的纯函数构件（可单测）：
 * - backoffDelay：429 退避延迟计算（Retry-After 秒优先，无头按 1s * 2^attempt）；
 * - parseRetryAfter：Retry-After 头解析（秒数或 HTTP 日期）；
 * - createSingleFlight：401 刷新单飞（并发调用共享同一 inflight promise）；
 * - createTenantSuspendedHandler：TENANT_SUSPENDED 横幅判定器（13.8，client 接线）。
 */

/** 错误响应体（附录 B.0）：{error: {code, message, request_id}}。 */
export interface EdpErrorBody {
  error?: { code?: string; message?: string; request_id?: string };
}

/** 429 退避延迟（毫秒）：有 Retry-After（秒）按头值，无头按 1s * 2^attempt。 */
export function backoffDelay(attempt: number, retryAfterSeconds?: number | null): number {
  if (retryAfterSeconds != null) {
    return Math.max(0, retryAfterSeconds) * 1000;
  }
  const exp = Math.min(Math.max(Math.trunc(attempt), 0), 16);
  return 1000 * 2 ** exp;
}

/** 解析 Retry-After 头为秒数；支持秒数与 HTTP 日期两种格式，非法/缺失返回 null。 */
export function parseRetryAfter(header: string | null): number | null {
  if (!header) return null;
  const trimmed = header.trim();
  if (trimmed === "") return null;
  const seconds = Number(trimmed);
  if (Number.isFinite(seconds)) return Math.max(0, seconds);
  const at = Date.parse(trimmed);
  if (Number.isNaN(at)) return null;
  return Math.max(0, (at - Date.now()) / 1000);
}

/** 刷新单飞：并发调用共享同一 inflight promise（同一结果），落定后复位允许再次触发。 */
export function createSingleFlight<A extends unknown[], R>(
  fn: (...args: A) => Promise<R>,
): (...args: A) => Promise<R> {
  let inflight: Promise<R> | null = null;
  return (...args: A) => {
    if (!inflight) {
      inflight = fn(...args).finally(() => {
        inflight = null;
      });
    }
    return inflight;
  };
}

/**
 * TENANT_SUSPENDED 全局横幅判定器（13.8）：HTTP 403 且 error.code ===
 * TENANT_SUSPENDED 时调用 onSuspended（每次命中恰一次）并返回 true；
 * 其他 403（FORBIDDEN/TENANT_FORBIDDEN/GUARD_POLICY_DENIED）与非 403 响应
 * 不触发。client 的 onTenantSuspended 接线经此判定——横幅判定逻辑单点在
 * interceptors，client 只负责把 (status, body) 喂进来。
 */
export function createTenantSuspendedHandler(
  onSuspended: () => void,
): (status: number, body: unknown) => boolean {
  return (status, body) => {
    if (status !== 403) return false;
    const code = (body as EdpErrorBody | null | undefined)?.error?.code;
    if (code !== "TENANT_SUSPENDED") return false;
    onSuspended();
    return true;
  };
}
