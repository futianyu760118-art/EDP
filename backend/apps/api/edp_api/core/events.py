"""进程内事件总线（设计文档 7.2）：Outbox 订阅者注册与消息结构。

契约：订阅者接口 ``on_event(event) -> ack/nack``——正常返回即 ack；抛出
任何异常即 nack（worker 侧按指数退避重投，超阈值置 FAILED）。W1-W4 分发
形态为进程内事件总线，保留升级 Kafka/Webhook 的分发接缝（订阅者实现从
本注册表替换即可，outbox 语义不变）。

边界：core 不依赖 modules——``OutboxMessage`` 是纯数据结构，由 worker 侧
（apps/worker/edp_worker/outbox_dispatch.py）从 event.outbox 行构造。
"""

import json
import logging
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


# ---- 模块级注册表（组合根装配：main.py / worker main.py 调用 register） ----

subscribers: list[Subscriber] = []


def register_subscriber(subscriber: Subscriber) -> None:
    """登记订阅者（幂等：同一实例不重复登记）。"""
    if subscriber not in subscribers:
        subscribers.append(subscriber)


def clear_subscribers() -> None:
    """清空注册表（测试隔离用）。"""
    subscribers.clear()
