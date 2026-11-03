"""进程内事件总线（设计文档 7.2）：Outbox 订阅者注册与消息结构。

契约：订阅者接口 ``on_event(event) -> ack/nack``——正常返回即 ack；抛出
任何异常即 nack（worker 侧按指数退避重投，超阈值置 FAILED）。W1-W4 分发
形态为进程内事件总线，保留升级 Kafka/Webhook 的分发接缝（订阅者实现从
本注册表替换即可，outbox 语义不变）。

边界：core 不依赖 modules——``OutboxMessage`` 是纯数据结构，由 worker 侧
（apps/worker/edp_worker/outbox_dispatch.py）从 event.outbox 行构造。
"""

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

logger = logging.getLogger("edp.outbox")


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    """分发消息（event.outbox 一行的投影；payload 为 JSONB 反序列化 dict）。"""

    outbox_id: int
    tenant_id: UUID
    aggregate_type: str
    aggregate_id: UUID
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)


class Subscriber(Protocol):
    """订阅者协议：正常返回 = ack；抛异常 = nack（触发退避重投）。"""

    async def on_event(self, msg: OutboxMessage) -> None: ...


class LoggingSubscriber:
    """结构化日志订阅者：json 一行（outbox_id/tenant_id/event_type）。"""

    consumer_name = "edp.logging"

    async def on_event(self, msg: OutboxMessage) -> None:
        logger.info(
            json.dumps(
                {
                    "outbox_id": msg.outbox_id,
                    "tenant_id": str(msg.tenant_id),
                    "event_type": msg.event_type,
                },
                ensure_ascii=False,
            )
        )


class EBMSNotifyStubSubscriber:
    """EBMS 通知桩订阅者（W1 log-only）。

    W2 将替换为 HTTP 通知 EBMS（异常/缓存失效投递）；接口签名不变，
    worker 仅依赖 ``Subscriber`` 协议。
    """

    consumer_name = "m03-ebms-notify"

    def __init__(self) -> None:
        self._logger = logging.getLogger("edp.ebms_notify")

    async def on_event(self, msg: OutboxMessage) -> None:
        self._logger.info(
            json.dumps(
                {
                    "notify": "ebms",
                    "outbox_id": msg.outbox_id,
                    "tenant_id": str(msg.tenant_id),
                    "event_type": msg.event_type,
                },
                ensure_ascii=False,
            )
        )


class CRMLeadSubscriber:
    """Deliver LeadIntakeV1 to CRM through its service-authenticated endpoint."""

    consumer_name = "m05-crm-lead"

    def __init__(
        self,
        target_url: str,
        token: str,
        *,
        timeout_s: float = 5.0,
        sender: Callable[[str, dict[str, str], bytes, float], Awaitable[None]] | None = None,
    ) -> None:
        if not target_url or not token:
            raise ValueError("CRM Lead subscriber requires target_url and token")
        self.target_url = target_url
        self.token = token
        self.timeout_s = timeout_s
        self._sender = sender

    @classmethod
    def from_env(cls) -> "CRMLeadSubscriber | None":
        target_url = os.getenv("EDP_CRM_LEAD_TARGET_URL", "").strip()
        if not target_url:
            return None
        token = os.getenv("EDP_CRM_LEAD_TARGET_TOKEN", "").strip()
        if not token:
            raise RuntimeError(
                "EDP_CRM_LEAD_TARGET_URL is set but EDP_CRM_LEAD_TARGET_TOKEN is missing"
            )
        return cls(
            target_url,
            token,
            timeout_s=float(os.getenv("EDP_CRM_LEAD_TARGET_TIMEOUT_S", "5")),
        )

    async def on_event(self, msg: OutboxMessage) -> None:
        if msg.event_type != "lead.intake.received":
            return
        body = json.dumps(msg.payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
            "X-Contract-Version": "LeadIntakeV1",
            "X-Idempotency-Key": str(msg.payload.get("idempotency_key", "")),
        }
        if self._sender is not None:
            await self._sender(self.target_url, headers, body, self.timeout_s)
            return
        await asyncio.to_thread(self._send_http, headers, body)

    def _send_http(self, headers: dict[str, str], body: bytes) -> None:
        request = urllib.request.Request(
            self.target_url, data=body, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                if response.status < 200 or response.status >= 300:
                    raise RuntimeError(f"CRM Lead target returned HTTP {response.status}")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"CRM Lead target returned HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError("CRM Lead target unavailable") from exc


# ---- 模块级注册表（组合根装配：main.py / worker main.py 调用 register） ----

subscribers: list[Subscriber] = []


def register_subscriber(subscriber: Subscriber) -> None:
    """登记订阅者（幂等：同一实例不重复登记）。"""
    if subscriber not in subscribers:
        subscribers.append(subscriber)


def clear_subscribers() -> None:
    """清空注册表（测试隔离用）。"""
    subscribers.clear()
