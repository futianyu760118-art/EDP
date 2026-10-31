"""Outbox 事务性分发（设计文档 7.2）：SKIP LOCKED 批取 + 指数退避 + 单条隔离。

流程（每租户一批，单事务）：
1. bind_tenant——worker 以 edp_app 角色连接，同样受 FORCE RLS 约束，
   分发前必须绑定 app.tenant_id（事务级）；
2. events.service.claim_pending_outbox（FOR UPDATE SKIP LOCKED SELECT 的
   service 封装）——多 worker 副本并发同租户天然不双发（行锁互斥，锁内
   行被跳过）；
3. 逐条构造 OutboxMessage 分发给全部订阅者：全部成功 → PUBLISHED +
   published_at；任一订阅者抛异常（nack）→ events.service.
   record_outbox_result 记 retry_count+1 与指数退避（2^retry * base_s），
   retry_count 达 outbox_max_retries → FAILED（停止重投）；单条失败不
   中断本批后续条目；
4. 批末一次 commit（任一条的订阅者异常都被本层消化，不回滚同批其他
   条目的状态流转）。

表访问收敛（设计文档 2.3.2：worker 只经模块 service）：出/入队归
events.service，活跃租户清单归 tenantmgmt.service（见 scheduler.py）。
订阅者经参数注入（测试接缝：传入错误订阅者即可驱动重投路径）。
"""

import asyncio
import logging
from uuid import UUID

from edp_api.core.config import get_settings
from edp_api.core.db import bind_tenant
from edp_api.core.events import OutboxMessage, Subscriber
from edp_api.modules.events import service as events_service
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from edp_worker.scheduler import active_tenant_ids

logger = logging.getLogger("edp.worker.outbox")

DEFAULT_BATCH_SIZE = 100


def _empty_stats() -> dict[str, int]:
    return {"published": 0, "retried": 0, "failed": 0}


async def dispatch_batch(
    engine: AsyncEngine,
    tenant_id: UUID,
    subscribers: list[Subscriber],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, int]:
    """单租户一批分发（见模块 docstring）；返回 {published, retried, failed}。"""
    settings = get_settings()
    stats = _empty_stats()
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as sess:
        await bind_tenant(sess, tenant_id)
        rows = await events_service.claim_pending_outbox(sess, tenant_id, batch_size)

        for row in rows:
            msg = OutboxMessage(
                outbox_id=row.outbox_id,
                tenant_id=row.tenant_id,
                aggregate_type=row.aggregate_type,
                aggregate_id=row.aggregate_id,
                event_type=row.event_type,
                payload=dict(row.payload),
            )
            try:
                for subscriber in subscribers:
                    await subscriber.on_event(msg)
            except Exception as exc:  # noqa: BLE001 — nack 即退避，单条隔离
                outcome = await events_service.record_outbox_result(
                    sess,
                    row.outbox_id,
                    "retry",
                    settings.outbox_backoff_base_seconds,
                    settings.outbox_max_retries,
                )
                stats["failed" if outcome == "failed" else "retried"] += 1
                retry_count = row.retry_count + 1
                delay = (2**retry_count) * settings.outbox_backoff_base_seconds
                logger.warning(
                    "outbox nack outbox_id=%s retry=%d delay=%.0fs error=%r",
                    msg.outbox_id,
                    retry_count,
                    delay,
                    exc,
                )
                continue

            await events_service.record_outbox_result(
                sess,
                row.outbox_id,
                "published",
                settings.outbox_backoff_base_seconds,
                settings.outbox_max_retries,
            )
            stats["published"] += 1

        await sess.commit()
    return stats


async def run_forever(
    engine: AsyncEngine,
    subscribers: list[Subscriber],
    *,
    interval: float = 1.0,
    idle_interval: float = 5.0,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> None:
    """常驻循环：活跃租户清单（30s 缓存）→ 逐租户分发。

    单租户异常隔离（try/except 继续）；全部租户空转 sleep idle_interval，
    有活干 sleep interval。
    """
    factory = async_sessionmaker(engine, expire_on_commit=False)
    while True:
        had_work = False
        try:
            async with factory() as sess:
                tenant_ids = await active_tenant_ids(sess)
        except Exception:  # noqa: BLE001 — 清单查询失败不致死循环退出
            logger.exception("active tenant list query failed")
            tenant_ids = []

        for tenant_id in tenant_ids:
            try:
                stats = await dispatch_batch(
                    engine, tenant_id, subscribers, batch_size=batch_size
                )
            except Exception:  # noqa: BLE001 — 单租户异常隔离
                logger.exception("dispatch failed tenant=%s", tenant_id)
                continue
            if any(stats.values()):
                had_work = True
                logger.info(
                    "dispatch stats tenant=%s published=%d retried=%d failed=%d",
                    tenant_id,
                    stats["published"],
                    stats["retried"],
                    stats["failed"],
                )

        await asyncio.sleep(interval if had_work else idle_interval)
