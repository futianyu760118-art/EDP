import { HttpResponse, type DefaultBodyType } from "msw";

/** 附录 B.0 错误结构。extra 用于 409 附 current_revision 等字段。 */
export function errorOf(
  code: string,
  message: string,
  status: number,
  extra?: Record<string, unknown>,
): HttpResponse<DefaultBodyType> {
  return HttpResponse.json(
    { error: { code, message, request_id: "mock-request-id", ...(extra ?? {}) } },
    { status },
  );
}
