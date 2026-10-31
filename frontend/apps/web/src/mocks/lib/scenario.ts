import { HttpResponse, type DefaultBodyType } from "msw";
import { errorOf } from "./http";

/** X-Mock-Scenario 注入（spec §5.2）：仅显式携带请求头时生效，驱动 EDP-201 拦截器链联调。 */
export function scenarioResponse(request: Request): HttpResponse<DefaultBodyType> | null {
  const s = request.headers.get("X-Mock-Scenario");
  if (!s) return null;
  if (s === "429") {
    return HttpResponse.json(
      { error: { code: "RATE_LIMITED", message: "请求过于频繁，请稍后重试", request_id: "mock-scenario" } },
      { status: 429, headers: { "Retry-After": "1" } },
    );
  }
  if (s === "503") {
    return errorOf("UPSTREAM_UNAVAILABLE", "源系统暂不可达，稍后重试", 503);
  }
  if (s === "suspended") {
    return errorOf("TENANT_SUSPENDED", "当前租户已暂停，请联系平台管理员", 403);
  }
  return null;
}
