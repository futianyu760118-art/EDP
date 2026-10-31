import { http, HttpResponse } from "msw";
import { scenarioResponse } from "../lib/scenario";
import { health, outboxStatus } from "../data/health";

export const healthHandlers = [
  // B.13 GET /api/v1/health（deep 字段始终返回；?deep=true 的 ADMIN 鉴权由后端实现，mock 不校验）
  http.get("*/api/v1/health", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    return HttpResponse.json(health);
  }),

  // B.13 GET /admin/outbox/status
  http.get("*/api/v1/admin/outbox/status", ({ request }) => {
    const scenario = scenarioResponse(request);
    if (scenario) return scenario;
    return HttpResponse.json(outboxStatus);
  }),
];
