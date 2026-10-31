"""实时流消费（V1.3 T44d）：Kafka → Debezium 信封 → SourceRecord → 管道。

- 配置（StreamSettings.from_env）：EDP_STREAM_KAFKA_BOOTSTRAP（空/缺省 =
  不启用——worker 其余职责不受影响）、EDP_STREAM_ROUTES（JSON 数组：
  topic / source_system / pk_columns / owner_domain / object_type / tenant
  slug）、EDP_STREAM_GROUP（缺省 edp-worker）、EDP_STREAM_POLL_TIMEOUT_MS；
- 位点事实来源 = PG realtime.stream_offsets（0018）：Kafka group 仅用于
  分配协调，**不 commit**——on_assign 回调按库内位点 seek（stored+1），
  重放窗口由 PG 决定，与 Kafka group offset 解耦；
- 投递语义：at-least-once（位点在管道事务提交后独立推进；崩溃窗口内的
  重放由管道 UUIDv5 + ON CONFLICT 幂等收敛为 effectively-once，重复计
  duplicated）；解析失败 → DLQ（坐标唯一，重放幂等）+ 位点推进不阻断；
- 头部阻塞裁定（v1）：单条管道失败 → 消息回队首指数退避重试，期间不
  消费后续消息（跨分区也不推进——避免同分区跳位导致已处理位移越过未
  处理位、重启后丢消息）；吞吐让位于不丢不重。

依赖注入缝（测试）：consumer_factory / resolve_tenant / process /
advance_offset / write_dlq 均可替身注入（tests/unit/test_stream_consume.py
不碰 Kafka/DB）。aiokafka 延迟导入——未配置实时链路的环境无需安装。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from os import environ
from typing import Any
from uuid import UUID, uuid4

from edp_adapters.base import SourceRecord
from edp_adapters.stream import StreamParseError, StreamRoute, parse_debezium_event
from edp_api.core.db import bind_tenant
from edp_api.modules.ingest import service as ingest_service
from edp_api.modules.tenantmgmt import service as tenantmgmt_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

logger = logging.getLogger("edp.worker.stream")

DEFAULT_GROUP = "edp-worker"
DEFAULT_POLL_TIMEOUT_MS = 500
DEFAULT_RETRY_BACKOFF_S = 1.0
STARTUP_ATTEMPTS = 5
STARTUP_BACKOFF_BASE_S = 2.0
STARTUP_BACKOFF_MAX_S = 15.0

ProcessFn = Callable[[SourceRecord, str | UUID, tuple[str, int, int]], Any]
AdvanceFn = Callable[[str, str, int, int], Any]
DlqFn = Callable[[str, int, int, str, bytes], Any]


@dataclass(slots=True)
class RouteEntry:
    """topic 路由 + 租户 slug（消费启动期解析为 tenant_id）。"""

    route: StreamRoute
    tenant: str


@dataclass(slots=True)
class StreamSettings:
    bootstrap: str
    group: str = DEFAULT_GROUP
    routes: list[RouteEntry] = field(default_factory=list)
    poll_timeout_ms: int = DEFAULT_POLL_TIMEOUT_MS
    retry_backoff_s: float = DEFAULT_RETRY_BACKOFF_S

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None
    ) -> StreamSettings | None:
        """环境装配；未配置 bootstrap → None（实时链路禁用）。"""
        source = env if env is not None else environ
        bootstrap = (source.get("EDP_STREAM_KAFKA_BOOTSTRAP") or "").strip()
        if not bootstrap:
            return None
        routes_raw = (source.get("EDP_STREAM_ROUTES") or "[]").strip()
        routes = _parse_routes(routes_raw)
        if not routes:
            raise ValueError(
                "EDP_STREAM_KAFKA_BOOTSTRAP 已配置但 EDP_STREAM_ROUTES 为空"
                "（至少一条：topic / source_system / tenant）"
            )
        poll_raw = source.get("EDP_STREAM_POLL_TIMEOUT_MS")
        return cls(
            bootstrap=bootstrap,
            group=(source.get("EDP_STREAM_GROUP") or DEFAULT_GROUP).strip(),
            routes=routes,
            poll_timeout_ms=int(poll_raw) if poll_raw else DEFAULT_POLL_TIMEOUT_MS,
        )


def _parse_routes(raw: str) -> list[RouteEntry]:
    """JSON 数组 → RouteEntry 列表；缺 topic / 重复 topic → ValueError。"""
    entries: list[RouteEntry] = []
    seen: set[str] = set()
    for item in json.loads(raw):
        if not isinstance(item, dict):
            raise ValueError(f"路由项须为对象：{item!r}")
        topic = item.get("topic")
        source_system = item.get("source_system")
        tenant = item.get("tenant")
        if not topic or not source_system or not tenant:
            raise ValueError(
                f"路由缺必需字段（topic/source_system/tenant）：{item!r}"
            )
        if topic in seen:
            raise ValueError(f"topic 重复路由：{topic}")
        seen.add(topic)
        pk = item.get("pk_columns")
        entries.append(
            RouteEntry(
                route=StreamRoute(
                    topic=topic,
                    source_system=source_system,
                    pk_columns=tuple(pk) if pk else ("id",),
                    owner_domain=item.get("owner_domain") or "master",
                    object_type=item.get("object_type"),
                ),
                tenant=tenant,
            )
        )
    return entries


async def _consume_one(
    message: Any,
    *,
    route: StreamRoute,
    tenant_id: str | UUID,
    group: str,
    process: ProcessFn,
    advance_offset: AdvanceFn,
    write_dlq: DlqFn,
) -> str:
    """单消息处理：registered / duplicated / dlq；管道失败异常上抛。

    dlq 路径（解析失败）与成功路径都会推进位点——毒消息不得阻断分区；
    管道失败不推进（调用方回队重试）。
    """
    try:
        event = json.loads(bytes(message.value))
        record = parse_debezium_event(event, route)
    except (ValueError, StreamParseError, UnicodeDecodeError) as exc:
        await write_dlq(
            message.topic,
            message.partition,
            message.offset,
            str(exc),
            bytes(message.value),
        )
        await advance_offset(group, message.topic, message.partition, message.offset)
        return "dlq"

    if record is None:
        # op=d / tombstone：upsert-only 管道不产生记录，位点推进跳过
        await advance_offset(group, message.topic, message.partition, message.offset)
        return "skipped"

    coords = (message.topic, message.partition, message.offset)
    registered = await process(record, tenant_id, coords)
    await advance_offset(group, message.topic, message.partition, message.offset)
    return "registered" if registered else "duplicated"


# ---- 真实依赖实现（注入缝的缺省值） ----

_UPSERT_OFFSET_SQL = text("""
    INSERT INTO realtime.stream_offsets
        (consumer_group, topic, partition_id, partition_offset)
    VALUES (:g, :t, :p, :o)
    ON CONFLICT (consumer_group, topic, partition_id)
    DO UPDATE SET
        partition_offset = GREATEST(
            realtime.stream_offsets.partition_offset, EXCLUDED.partition_offset),
        updated_at = now()
""")

_LOAD_OFFSET_SQL = text("""
    SELECT partition_offset FROM realtime.stream_offsets
    WHERE consumer_group = :g AND topic = :t AND partition_id = :p
""")

_INSERT_DLQ_SQL = text("""
    INSERT INTO realtime.stream_dlq
        (dlq_id, topic, partition_id, partition_offset, error, payload)
    VALUES (:d, :t, :p, :o, :error, CAST(:payload AS jsonb))
    ON CONFLICT (topic, partition_id, partition_offset) DO NOTHING
""")


async def _resolve_tenant(engine: AsyncEngine, slug: str) -> UUID:
    """slug → tenant_id（启动期一次；未知租户即装配失败——fail fast）。"""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as sess:
        tenant = await tenantmgmt_service.get_tenant_by_slug(sess, slug)
    if tenant is None:
        raise LookupError(f"stream route tenant 不存在：{slug}")
    return tenant.tenant_id


async def _process_via_pipeline(
    engine: AsyncEngine, record: SourceRecord, tenant_id: UUID, coords: tuple[str, int, int]
) -> bool:
    """capture 通道入库：bind_tenant → process_record（via/batch_id 标记）。"""
    topic, partition, offset = coords
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory.begin() as sess:
        await bind_tenant(sess, tenant_id)
        return await ingest_service.process_record(
            sess,
            tenant_id,
            record,
            via="capture",
            batch_id=f"capture:{topic}:{partition}:{offset}",
        )


async def _advance_offset(
    engine: AsyncEngine, group: str, topic: str, partition: int, offset: int
) -> None:
    """位点推进（GREATEST 单调；独立短事务）。"""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory.begin() as sess:
        await sess.execute(
            _UPSERT_OFFSET_SQL, {"g": group, "t": topic, "p": partition, "o": offset}
        )


async def _write_dlq(
    engine: AsyncEngine, topic: str, partition: int, offset: int, error: str, raw: bytes
) -> None:
    """死信落库（坐标唯一幂等；payload 包 raw 原文保证 JSONB 合法）。"""
    payload_doc = json.dumps(
        {"raw": raw.decode("utf-8", errors="replace")}, ensure_ascii=False
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory.begin() as sess:
        await sess.execute(
            _INSERT_DLQ_SQL,
            {
                "d": uuid4(),
                "t": topic,
                "p": partition,
                "o": offset,
                "error": error,
                "payload": payload_doc,
            },
        )


async def _load_offset(
    engine: AsyncEngine, group: str, topic: str, partition: int
) -> int | None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as sess:
        return (
            await sess.execute(
                _LOAD_OFFSET_SQL, {"g": group, "t": topic, "p": partition}
            )
        ).scalar_one_or_none()


def _aiokafka_consumer_factory(settings: StreamSettings) -> Any:
    """真实消费者（延迟导入 aiokafka）：不 commit——位点归 PG。"""
    from aiokafka import AIOKafkaConsumer

    return AIOKafkaConsumer(
        *sorted(entry.route.topic for entry in settings.routes),
        bootstrap_servers=settings.bootstrap,
        group_id=settings.group,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )


def _seek_listener(engine: AsyncEngine, group: str, consumer: Any) -> Any:
    """rebalance 监听器（aiokafka ConsumerRebalanceListener）：分区分配时
    按 PG 位点 seek（stored+1；无位点保持 earliest）。"""

    from aiokafka import ConsumerRebalanceListener

    class _SeekListener(ConsumerRebalanceListener):
        async def on_partitions_assigned(self, assigned):
            for tp in assigned:
                stored = await _load_offset(engine, group, tp.topic, tp.partition)
                if stored is not None:
                    consumer.seek(tp, stored + 1)
                    logger.info(
                        "stream seek %s/%d -> %d (pg offsets)",
                        tp.topic,
                        tp.partition,
                        stored + 1,
                    )

        async def on_partitions_revoked(self, revoked):
            return None

    return _SeekListener()


async def stream_loop(
    engine: AsyncEngine,
    settings: StreamSettings,
    *,
    stop: asyncio.Event | None = None,
    consumer_factory: Callable[[StreamSettings], Any] | None = None,
    resolve_tenant: Callable[[AsyncEngine, str], Any] | None = None,
    process: ProcessFn | None = None,
    advance_offset: AdvanceFn | None = None,
    write_dlq: DlqFn | None = None,
) -> dict[str, int]:
    """常驻消费循环（worker gather 并发协程之一）。

    流程：租户解析（一次）→ consumer.start → subscribe(on_assign=PG 位点
    seek) → 循环 getmany 批取 → 逐条路由分发（无路由 → DLQ）→ _consume_one
    （registered/duplicated/dlq）→ 管道失败回队首退避重试（头部阻塞，
    见模块 docstring）。stop 置位后退出并 stop 消费者，返回累计 stats。
    """
    stop = stop or asyncio.Event()
    consumer_factory = consumer_factory or _aiokafka_consumer_factory
    resolve_tenant = resolve_tenant or _resolve_tenant

    # 缺省依赖绑定 engine（闭包注入——测试可整体替身）
    if process is None:

        async def process(record, tenant_id, coords):  # noqa: F811 — 闭包绑定
            return await _process_via_pipeline(engine, record, tenant_id, coords)

    if advance_offset is None:

        async def advance_offset(group, topic, partition, offset):  # noqa: F811
            await _advance_offset(engine, group, topic, partition, offset)

    if write_dlq is None:

        async def write_dlq(topic, partition, offset, error, raw):  # noqa: F811
            await _write_dlq(engine, topic, partition, offset, error, raw)

    tenant_ids: dict[str, UUID] = {}
    routes: dict[str, StreamRoute] = {}
    for entry in settings.routes:
        tenant_ids[entry.route.topic] = await resolve_tenant(engine, entry.tenant)
        routes[entry.route.topic] = entry.route
    logger.info(
        "stream loop started bootstrap=%s group=%s topics=%s",
        settings.bootstrap,
        settings.group,
        sorted(routes),
    )

    stats = {"registered": 0, "duplicated": 0, "dlq": 0, "skipped": 0, "retried": 0}
    consumer = consumer_factory(settings)
    # 订阅先于 start（aiokafka 0.14：start 后订阅会触发 fetcher
    # "assignment is not active" 断言竞态——见 e2e 调试记录）
    consumer.subscribe(
        sorted(routes),
        listener=_seek_listener(engine, settings.group, consumer),
    )
    # 启动重试（broker 短暂不可达窗口——组协调器就绪前的常态）
    for attempt in range(1, STARTUP_ATTEMPTS + 1):
        try:
            await consumer.start()
            break
        except Exception:
            if attempt == STARTUP_ATTEMPTS:
                raise
            backoff = min(
                STARTUP_BACKOFF_BASE_S * (2 ** (attempt - 1)), STARTUP_BACKOFF_MAX_S
            )
            logger.warning(
                "kafka consumer start failed attempt=%d/%d backoff=%.1fs",
                attempt,
                STARTUP_ATTEMPTS,
                backoff,
                exc_info=True,
            )
            await asyncio.sleep(backoff)
    try:
        pending: deque = deque()
        while not stop.is_set():
            if not pending:
                batch = await consumer.getmany(timeout_ms=settings.poll_timeout_ms)
                for records in batch.values():
                    pending.extend(records)
                if not pending:
                    continue
            message = pending.popleft()
            route = routes.get(message.topic)
            if route is None:
                await write_dlq(
                    message.topic,
                    message.partition,
                    message.offset,
                    f"no route for topic: {message.topic}",
                    bytes(message.value),
                )
                await advance_offset(
                    settings.group, message.topic, message.partition, message.offset
                )
                stats["dlq"] += 1
                continue
            try:
                status = await _consume_one(
                    message,
                    route=route,
                    tenant_id=tenant_ids[message.topic],
                    group=settings.group,
                    process=process,
                    advance_offset=advance_offset,
                    write_dlq=write_dlq,
                )
                stats[status] += 1
            except Exception:  # noqa: BLE001 — 管道/DB 失败：回队重试
                stats["retried"] += 1
                logger.warning(
                    "stream 管道失败，回队重试：%s/%d/%d",
                    message.topic,
                    message.partition,
                    message.offset,
                    exc_info=True,
                )
                pending.appendleft(message)
                await asyncio.sleep(settings.retry_backoff_s)
    finally:
        await consumer.stop()
    return stats
