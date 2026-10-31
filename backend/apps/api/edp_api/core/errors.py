"""统一错误体系：13 错误码 → HTTP 映射、EdpError 与全局异常处理器。

错误响应结构（附录 B.0）：
    {"error": {"code", "message", "request_id", **extra}}

路由层 StarletteHTTPException（框架 404/405 等）同样收敛为统一 envelope：
405 全路由通用文案「方法不允许」（T8 评审认可的**全路由行为变更**——此前
405 由框架默认返回 {"detail": ...}；契约偏差由 T14 导出时记录），其余状态码
保留 detail 文案。
"""

import logging
import uuid
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from edp_api.core.contextvars import current_request_id

logger = logging.getLogger(__name__)


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    TENANT_FORBIDDEN = "TENANT_FORBIDDEN"
    TENANT_SUSPENDED = "TENANT_SUSPENDED"
    GUARD_POLICY_DENIED = "GUARD_POLICY_DENIED"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    CONFLICT = "CONFLICT"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    RATE_LIMITED = "RATE_LIMITED"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    INTERNAL = "INTERNAL"


HTTP_FOR_CODE: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: 400,
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.TENANT_FORBIDDEN: 403,
    ErrorCode.TENANT_SUSPENDED: 403,
    ErrorCode.GUARD_POLICY_DENIED: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.METHOD_NOT_ALLOWED: 405,
    ErrorCode.CONFLICT: 409,
    ErrorCode.INVALID_TRANSITION: 422,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.UPSTREAM_UNAVAILABLE: 503,
    ErrorCode.INTERNAL: 500,
}


class EdpError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.code = ErrorCode(code)
        self.message = message
        self.extra: dict[str, Any] = dict(extra or {})
        super().__init__(self.code, message)

    @property
    def http_status(self) -> int:
        return HTTP_FOR_CODE[self.code]

    @classmethod
    def validation_error(cls, message: str = "参数缺失或格式错误", *, extra=None) -> "EdpError":
        return cls(ErrorCode.VALIDATION_ERROR, message, extra=extra)

    @classmethod
    def unauthenticated(cls, message: str = "未认证或凭据无效", *, extra=None) -> "EdpError":
        return cls(ErrorCode.UNAUTHENTICATED, message, extra=extra)

    @classmethod
    def forbidden(cls, message: str = "权限不足", *, extra=None) -> "EdpError":
        return cls(ErrorCode.FORBIDDEN, message, extra=extra)

    @classmethod
    def tenant_forbidden(cls, message: str = "跨租户访问被拒绝", *, extra=None) -> "EdpError":
        return cls(ErrorCode.TENANT_FORBIDDEN, message, extra=extra)

    @classmethod
    def tenant_suspended(cls, message: str = "租户已暂停", *, extra=None) -> "EdpError":
        return cls(ErrorCode.TENANT_SUSPENDED, message, extra=extra)

    @classmethod
    def guard_policy_denied(cls, message: str = "策略拒绝该操作", *, extra=None) -> "EdpError":
        return cls(ErrorCode.GUARD_POLICY_DENIED, message, extra=extra)

    @classmethod
    def not_found(cls, message: str = "资源不存在", *, extra=None) -> "EdpError":
        return cls(ErrorCode.NOT_FOUND, message, extra=extra)

    @classmethod
    def method_not_allowed(
        cls, message: str = "只读路由收到非 GET 请求", *, extra=None
    ) -> "EdpError":
        return cls(ErrorCode.METHOD_NOT_ALLOWED, message, extra=extra)

    @classmethod
    def conflict(cls, message: str = "版本冲突或唯一键冲突", *, extra=None) -> "EdpError":
        return cls(ErrorCode.CONFLICT, message, extra=extra)

    @classmethod
    def invalid_transition(cls, message: str = "状态机非法转移", *, extra=None) -> "EdpError":
        return cls(ErrorCode.INVALID_TRANSITION, message, extra=extra)

    @classmethod
    def rate_limited(cls, message: str = "请求超出租户限流", *, extra=None) -> "EdpError":
        return cls(ErrorCode.RATE_LIMITED, message, extra=extra)

    @classmethod
    def upstream_unavailable(cls, message: str = "源系统不可达", *, extra=None) -> "EdpError":
        return cls(ErrorCode.UPSTREAM_UNAVAILABLE, message, extra=extra)

    @classmethod
    def internal(cls, message: str = "内部错误", *, extra=None) -> "EdpError":
        return cls(ErrorCode.INTERNAL, message, extra=extra)


class ErrorBody(BaseModel):
    """错误体（附录 B.0）；运行时 extra 字段按需并入。"""

    code: str
    message: str
    request_id: str


class ErrorEnvelope(BaseModel):
    """统一错误响应包裹：{"error": {code, message, request_id}}。"""

    error: ErrorBody


_RESPONSE_DESCRIPTIONS: dict[ErrorCode, str] = {
    ErrorCode.VALIDATION_ERROR: "参数缺失或格式错误",
    ErrorCode.UNAUTHENTICATED: "未认证或凭据无效",
    ErrorCode.FORBIDDEN: "权限不足（scope/权限不满足）",
    ErrorCode.TENANT_FORBIDDEN: "跨租户访问被拒绝",
    ErrorCode.TENANT_SUSPENDED: "租户已暂停或状态异常",
    ErrorCode.GUARD_POLICY_DENIED: "策略拒绝该操作",
    ErrorCode.NOT_FOUND: "资源不存在（跨租户统一 404，不泄露存在性）",
    ErrorCode.METHOD_NOT_ALLOWED: "方法不允许",
    ErrorCode.CONFLICT: "版本冲突（响应附 current_revision）",
    ErrorCode.INVALID_TRANSITION: "状态机非法转移",
    ErrorCode.RATE_LIMITED: "请求超出租户限流",
    ErrorCode.UPSTREAM_UNAVAILABLE: "源系统不可达",
    ErrorCode.INTERNAL: "内部错误",
}


def error_responses(
    *codes: ErrorCode, descriptions: dict[ErrorCode, str] | None = None
) -> dict[str, Any]:
    """按 HTTP 状态聚合错误码，生成路由 responses={...} OpenAPI 声明。

    仅影响 OpenAPI 文档，不改变运行时行为（运行时统一走 EdpError handler）。
    descriptions：个别码的描述覆盖（如 CONFLICT 在任务互斥场景语义为
    TASK_CONFLICT——同状态码不同语义时用，默认走 _RESPONSE_DESCRIPTIONS）。
    """
    overrides = descriptions or {}
    by_status: dict[int, list[ErrorCode]] = {}
    for code in codes:
        by_status.setdefault(HTTP_FOR_CODE[code], []).append(code)
    return {
        str(status_code): {
            "description": "；".join(
                f"{c.value}：{overrides.get(c, _RESPONSE_DESCRIPTIONS[c])}"
                for c in code_list
            ),
            "model": ErrorEnvelope,
        }
        for status_code, code_list in sorted(by_status.items())
    }


def _error_payload(code: ErrorCode, message: str, extra: dict[str, Any] | None = None) -> dict:
    body: dict[str, Any] = {
        "code": code.value,
        "message": message,
        "request_id": current_request_id.get() or str(uuid.uuid4()),
    }
    if extra:
        body.update(extra)
    return {"error": body}


def _summarize_validation_error(exc: RequestValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "请求参数校验失败"
    first = errors[0]
    loc = ".".join(str(part) for part in first.get("loc", ()))
    msg = first.get("msg", "invalid")
    return f"{loc}: {msg}" if loc else msg


# 路由层 StarletteHTTPException（框架抛出，非 EdpError）→ 统一 envelope 的错误码
# 映射；405 文案为全路由通用「方法不允许」（T8 评审认可的全路由行为变更，
# 不再写死只读路由语义——Read-Only 仅注册 GET 使非 GET 落到此处）；其余状态码
# 保留 detail 文案；未映射状态码 code 回退 INTERNAL（HTTP 状态码仍原样保留）。
_STATUS_TO_ERROR_CODE: dict[int, ErrorCode] = {
    400: ErrorCode.VALIDATION_ERROR,
    401: ErrorCode.UNAUTHENTICATED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    409: ErrorCode.CONFLICT,
    429: ErrorCode.RATE_LIMITED,
    503: ErrorCode.UPSTREAM_UNAVAILABLE,
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(EdpError)
    async def _handle_edp_error(_: Request, exc: EdpError) -> JSONResponse:
        # extra.retry_after（RATE_LIMITED）转为响应头，body 保持 B.0 结构
        extra = dict(exc.extra)
        retry_after = extra.pop("retry_after", None)
        headers = (
            {"Retry-After": str(retry_after)} if retry_after is not None else None
        )
        return JSONResponse(
            status_code=exc.http_status,
            content=_error_payload(exc.code, exc.message, extra),
            headers=headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 405:
            return JSONResponse(
                status_code=exc.status_code,
                content=_error_payload(ErrorCode.METHOD_NOT_ALLOWED, "方法不允许"),
                headers=exc.headers,
            )
        code = _STATUS_TO_ERROR_CODE.get(exc.status_code, ErrorCode.INTERNAL)
        message = str(exc.detail) if exc.detail is not None else _RESPONSE_DESCRIPTIONS[code]
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(code, message),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=HTTP_FOR_CODE[ErrorCode.VALIDATION_ERROR],
            content=_error_payload(ErrorCode.VALIDATION_ERROR, _summarize_validation_error(exc)),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled exception", exc_info=exc)
        return JSONResponse(
            status_code=HTTP_FOR_CODE[ErrorCode.INTERNAL],
            content=_error_payload(ErrorCode.INTERNAL, "内部错误"),
        )
