export type ErrorPresentation =
  | "inline" // 表单行内
  | "login" // 跳登录
  | "page403"
  | "banner" // TENANT_SUSPENDED 常驻横幅
  | "toast"
  | "rerender"; // allowed_to 重渲染

export interface ErrorSpec {
  message: string;
  presentation: ErrorPresentation;
}

export const ERROR_SPECS: Record<string, ErrorSpec> = {
  VALIDATION_ERROR: { message: "请求参数不正确，请检查后重试", presentation: "inline" },
  UNAUTHENTICATED: { message: "登录已过期，请重新登录", presentation: "login" },
  FORBIDDEN: { message: "无权访问该资源", presentation: "page403" },
  TENANT_FORBIDDEN: { message: "无权访问该租户", presentation: "page403" },
  TENANT_SUSPENDED: { message: "当前租户已暂停，请联系平台管理员", presentation: "banner" },
  GUARD_POLICY_DENIED: { message: "该操作仅限人工执行", presentation: "toast" },
  NOT_FOUND: { message: "资源不存在", presentation: "toast" },
  METHOD_NOT_ALLOWED: { message: "请求方法不支持，请上报问题", presentation: "toast" },
  CONFLICT: { message: "数据已被他人修改，已刷新", presentation: "toast" },
  INVALID_TRANSITION: { message: "状态流转不合法，已刷新可用操作", presentation: "rerender" },
  RATE_LIMITED: { message: "请求过于频繁，请稍后重试", presentation: "toast" },
  UPSTREAM_UNAVAILABLE: { message: "源系统暂不可达，稍后重试", presentation: "toast" },
  INTERNAL: { message: "服务内部错误，请稍后重试", presentation: "toast" },
  NETWORK_ERROR: { message: "网络异常，请检查连接后重试", presentation: "toast" },
};

export function errorSpec(code: string | undefined | null): ErrorSpec {
  return (code && ERROR_SPECS[code]) || ERROR_SPECS.INTERNAL;
}
