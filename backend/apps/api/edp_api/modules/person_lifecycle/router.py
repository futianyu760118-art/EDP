"""M01 人员状态事件接收和管理查询接口。"""

import hashlib
import hmac
import json
import os
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import bind_tenant, get_db
from edp_api.core.errors import EdpError, ErrorCode, error_responses
from edp_api.core.security.principal import Principal
from edp_api.modules.events.dependencies import require_read
from edp_api.modules.person_lifecycle import service
from edp_api.modules.person_lifecycle.schemas import PersonLifecycleEventIn, PersonLifecycleEventResponse
from edp_api.modules.tenantmgmt.dependencies import require_tenant_admin

router = APIRouter(prefix="/api/v1/person-lifecycle", tags=["person-lifecycle"])
DbSession = Annotated[AsyncSession, Depends(get_db)]


def _key_config(key_id: str) -> tuple[str | None, str | None]:
    raw = os.getenv("EDP_AEOS_PERSON_LIFECYCLE_KEYS_JSON") or os.getenv("AEOS_PERSON_LIFECYCLE_KEYS_JSON")
    if raw:
        try:
            values = json.loads(raw)
            item = values.get(key_id) if isinstance(values, dict) else None
            if isinstance(item, dict):
                return key_id, str(item.get("secret") or "")
            if isinstance(item, str):
                return key_id, item
        except json.JSONDecodeError:
            return None, None
    configured_id = os.getenv("EDP_AEOS_PERSON_LIFECYCLE_KEY_ID") or os.getenv("AEOS_PERSON_LIFECYCLE_KEY_ID") or "m01-kernel"
    secret = os.getenv("EDP_AEOS_PERSON_LIFECYCLE_SECRET") or os.getenv("AEOS_PERSON_LIFECYCLE_SECRET")
    return (configured_id, secret) if configured_id == key_id else (None, None)


async def _verify_signature(request: Request, key_id: str | None, timestamp: str | None, signature: str | None) -> bytes:
    if not key_id or not timestamp or not signature:
        raise EdpError.unauthenticated("缺少人员同步签名")
    try:
        timestamp_ms = int(timestamp)
    except ValueError as exc:
        raise EdpError.unauthenticated("人员同步时间不正确") from exc
    max_skew = int(os.getenv("EDP_AEOS_PERSON_LIFECYCLE_MAX_SKEW_SECONDS", "300")) * 1000
    if abs(int(time.time() * 1000) - timestamp_ms) > max_skew:
        raise EdpError.unauthenticated("人员同步请求已过期")
    _, secret = _key_config(key_id)
    if not secret:
        raise EdpError.unauthenticated("人员同步密钥无效")
    raw = await request.body()
    expected = hmac.new(secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    supplied = signature.removeprefix("sha256=")
    if not hmac.compare_digest(expected, supplied):
        raise EdpError.unauthenticated("人员同步签名无效")
    return raw


@router.post(
    "/events",
    response_model=PersonLifecycleEventResponse,
    response_model_exclude_none=True,
    responses=error_responses(ErrorCode.UNAUTHENTICATED, ErrorCode.VALIDATION_ERROR),
)
async def intake_event(
    request: Request,
    payload: PersonLifecycleEventIn,
    sess: DbSession,
    key_id: Annotated[str | None, Header(alias="X-AEOS-Key-Id")] = None,
    timestamp: Annotated[str | None, Header(alias="X-AEOS-Timestamp")] = None,
    signature: Annotated[str | None, Header(alias="X-AEOS-Signature")] = None,
) -> JSONResponse:
    await _verify_signature(request, key_id, timestamp, signature)
    try:
        tenant_id = await service.resolve_tenant_id(sess, payload.tenant_id)
    except ValueError as exc:
        raise EdpError.validation_error(str(exc)) from exc
    await bind_tenant(sess, tenant_id)
    response = await service.ingest_event(sess, payload, tenant_id, actor=key_id or "m01")
    status_code = 202 if response.status in {"pending", "scheduled"} and not response.duplicate else 200
    return JSONResponse(status_code=status_code, content=response.model_dump(mode="json"))


@router.get("/events/{event_id}", response_model=PersonLifecycleEventResponse)
async def get_event(
    event_id: str,
    principal: Annotated[Principal, Depends(require_read("event"))],
    sess: DbSession,
) -> PersonLifecycleEventResponse:
    response = await service.get_event(sess, principal.tenant_id, event_id)
    if response is None:
        raise EdpError.not_found("人员同步事件不存在")
    return response


@router.get("/deliveries")
async def get_deliveries(
    event_id: str,
    principal: Annotated[Principal, Depends(require_read("event"))],
    sess: DbSession,
) -> list[dict]:
    rows = await service.list_deliveries(sess, principal.tenant_id, event_id)
    if not rows:
        if await service.get_event(sess, principal.tenant_id, event_id) is None:
            raise EdpError.not_found("人员同步事件不存在")
    return [
        {
            "delivery_id": row.delivery_id,
            "event_id": row.event_id,
            "target_system": row.target_system,
            "status": row.status.lower(),
            "attempts": row.attempt_count,
            "last_error": row.last_error if principal.is_platform_admin or "ADMIN" in principal.roles else (
                "目标系统暂时无法访问" if row.status in {"FAILED", "DLQ"} else None
            ),
            "delivered_at": row.delivered_at,
            "next_attempt_at": row.next_attempt_at,
        }
        for row in rows
    ]


@router.post("/events/{event_id}/retry")
async def retry_event(
    event_id: str,
    principal: Annotated[Principal, Depends(require_tenant_admin)],
    sess: DbSession,
) -> dict:
    response = await service.retry_failed(sess, principal.tenant_id, event_id, actor=principal.id)
    if response is None:
        raise EdpError.not_found("人员同步事件不存在")
    return response.model_dump(mode="json")
