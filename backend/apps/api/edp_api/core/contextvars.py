"""请求级上下文：request_id / principal / tenant_id ContextVar 与 X-Request-ID 中间件。"""

import uuid
from contextvars import ContextVar
from typing import TYPE_CHECKING

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

if TYPE_CHECKING:
    # T8（core/security/principal.py）交付前的前向引用，避免运行时导入
    from edp_api.core.security.principal import Principal

current_request_id: ContextVar[str | None] = ContextVar("current_request_id", default=None)

# 认证完成后由 T10 租户上下文依赖写入；Principal 类型在 T8 落地
current_principal: ContextVar["Principal | None"] = ContextVar(
    "current_principal", default=None
)
current_tenant_id: ContextVar[uuid.UUID | None] = ContextVar(
    "current_tenant_id", default=None
)


class RequestIDMiddleware:
    """生成或透传 X-Request-ID，并写入 current_request_id 上下文与响应头。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id: str | None = None
        for key, value in scope.get("headers") or []:
            if key == b"x-request-id":
                request_id = value.decode("latin-1").strip() or None
                break
        if request_id is None:
            request_id = str(uuid.uuid4())

        token = current_request_id.set(request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).append("X-Request-ID", request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            current_request_id.reset(token)
