"""M02 到各业务系统的人员状态 HTTP 投递器。"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from uuid import UUID

from edp_api.core.config import get_settings
from edp_api.core.db import bind_tenant
from edp_api.modules.person_lifecycle import service
from edp_worker.scheduler import active_tenant_ids
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

logger = logging.getLogger("edp.worker.person_lifecycle")

ALLOWED_TARGET_STATUSES = {"synced", "skipped", "pending_confirmation", "retrying", "failed"}


def _post_json(url: str, headers: dict[str, str], body: bytes, timeout: float) -> tuple[int, dict | None]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            try:
                data = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                data = {"raw": raw[:1000]}
            return response.status, data
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            data = {"raw": raw[:1000]}
        return exc.code, data


async def deliver_once(engine: AsyncEngine, tenant_id: UUID, *, batch_size: int = 50) -> dict[str, int]:
    settings = get_settings()
    stats = {"synced": 0, "retried": 0, "dlq": 0}
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as sess:
        await bind_tenant(sess, tenant_id)
        rows = await service.claim_pending_deliveries(sess, tenant_id, batch_size)
        for row in rows:
            target = service.target_config(row.target_system)
            payload = await service.event_payload(sess, tenant_id, row.event_id)
            if not target or not payload or not target.get("secret"):
                await service.mark_delivery_failure(sess, row, "目标系统未配置", settings.outbox_max_retries, settings.outbox_backoff_base_seconds)
                continue
            body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            timestamp = str(int(datetime.now(timezone.utc).timestamp() * 1000))
            signature = hmac.new(target["secret"].encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
            headers = {
                "Content-Type": "application/json",
                "X-AEOS-Key-Id": target["key_id"],
                "X-AEOS-Timestamp": timestamp,
                "X-AEOS-Signature": f"sha256={signature}",
            }
            try:
                status_code, response = await asyncio.to_thread(
                    _post_json, row.target_url, headers, body, 5.0
                )
                if 200 <= status_code < 300:
                    result_status = str((response or {}).get("status") or "synced").lower()
                    if result_status not in ALLOWED_TARGET_STATUSES:
                        await service.mark_delivery_failure(
                            sess, row, f"目标系统返回了无法识别的处理状态：{result_status or '空状态'}",
                            settings.outbox_max_retries, settings.outbox_backoff_base_seconds,
                        )
                        stats["dlq" if row.status == "DLQ" else "retried"] += 1
                    elif result_status in {"failed", "retrying"}:
                        reason = str((response or {}).get("reason") or "目标系统未完成办理")
                        await service.mark_delivery_failure(
                            sess, row, reason,
                            settings.outbox_max_retries, settings.outbox_backoff_base_seconds,
                        )
                        stats["dlq" if row.status == "DLQ" else "retried"] += 1
                    else:
                        await service.mark_delivery_success(sess, row, result_status, response)
                        stats["synced"] += 1
                else:
                    await service.mark_delivery_failure(sess, row, f"目标系统返回 HTTP {status_code}", settings.outbox_max_retries, settings.outbox_backoff_base_seconds)
                    stats["dlq" if row.status == "DLQ" else "retried"] += 1
            except Exception as exc:  # noqa: BLE001 — 单目标失败进入退避/DLQ
                await service.mark_delivery_failure(sess, row, "目标系统暂时无法访问", settings.outbox_max_retries, settings.outbox_backoff_base_seconds)
                stats["dlq" if row.status == "DLQ" else "retried"] += 1
                logger.warning("person lifecycle target failed target=%s event=%s error=%s", row.target_system, row.event_id, exc)
        await sess.commit()
    return stats


async def person_lifecycle_loop(engine: AsyncEngine, *, interval: float = 2.0) -> None:
    """常驻处理到期目标；表尚未迁移或临时数据库故障时不让 worker 退出。"""
    while True:
        try:
            tenants = await _active_tenants(engine)
            for tenant_id in tenants:
                await deliver_once(engine, tenant_id)
        except Exception:  # noqa: BLE001 — worker 继续处理其他任务
            logger.exception("person lifecycle delivery loop failed")
        await asyncio.sleep(interval)


async def _active_tenants(engine: AsyncEngine) -> list[UUID]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as sess:
        return await active_tenant_ids(sess)
