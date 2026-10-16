"""V1.3 T48 端到端验收：Kafka（Debezium 信封）→ stream_loop → EDP 管道。

真实链路（唯 Kafka 侧信封按契约手工构造——Debezium Connector 本体属
T43 运维部署件，dev compose override / runbook 覆盖）：
1. 生产 2 条合法信封 + 1 条毒消息（缺 ts_ms）+ 1 条合法 → 消费后
   EDP 落 3 对象/事件/证据，毒消息进 DLQ，PG 位点推进；
2. 幂等重放：同 order_no + 同 ts_ms 重发 → 事件不增（duplicated 收敛）；
3. 断点续传：停消费 → 生产新消息 → 重启消费（PG 位点 seek）→ 新对象
   入库，旧位点前消息不重放（不丢不重）。

容器：模块级 KafkaContainer（testcontainers[kafka]）+ 既有 EDP PG 基座
（conftest：alembic 全量迁移 + edp_app RLS 角色）。痕迹：source_system
'scm-e2e' + realtime.stream_offsets/stream_dlq 按组清场。
"""

import asyncio
import json
import time
from datetime import UTC, datetime

import pytest
from edp_worker.stream_consume import RouteEntry, StreamSettings, stream_loop
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

pytestmark = [pytest.mark.integration]

TOPIC = "edp.default.scm.orders"
GROUP = "e2e-v13-group"
_SRC = "scm-e2e"
_WAIT_S = 30.0


def _envelope(order_no: str, ts_ms: int) -> bytes:
    return json.dumps(
        {
            "payload": {
                "before": None,
                "after": {
                    "order_no": order_no,
                    "amount": 10,
                    "owner_domain": "sales",
                },
                "op": "c",
                "ts_ms": ts_ms,
                "source": {"db": "scm", "schema": "public", "table": "orders"},
            }
        }
    ).encode()


def _poison() -> bytes:
    return json.dumps(
        {"payload": {"op": "c", "after": {"order_no": "SO-POISON"}}}
    ).encode()


@pytest.fixture(scope="module")
def kafka_bootstrap():
    from testcontainers.community.kafka import KafkaContainer

    with KafkaContainer() as container:
        bootstrap = container.get_bootstrap_server()
        asyncio.run(_wait_broker_ready(bootstrap))
        yield bootstrap


async def _wait_broker_ready(bootstrap: str, timeout_s: float = 120.0) -> None:
    """broker 就绪探测：produce→consume 冒烟往返（组协调器 + fetch 全通）。

    AdminClient 可列 topic 不保证 __consumer_offsets 协调器可用——
    GroupCoordinatorNotAvailableError 窗口期以真实往返收殓。
    """
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

    smoke_topic = "e2e-smoke"
    deadline = time.monotonic() + timeout_s
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        producer = AIOKafkaProducer(bootstrap_servers=bootstrap)
        consumer = AIOKafkaConsumer(
            smoke_topic,
            bootstrap_servers=bootstrap,
            group_id="e2e-smoke-group",
            auto_offset_reset="earliest",
        )
        try:
            await producer.start()
            await consumer.start()
            await producer.send_and_wait(smoke_topic, b"ping")
            deadline_inner = time.monotonic() + 30.0
            while time.monotonic() < deadline_inner:
                batch = await consumer.getmany(timeout_ms=500)
                for records in batch.values():
                    if records:
                        return
            last_exc = AssertionError("smoke 消息 30s 未达")
        except Exception as exc:  # noqa: BLE001 — 启动窗口期重试
            last_exc = exc
            await asyncio.sleep(2.0)
        finally:
            for client in (consumer, producer):
                try:
                    await client.stop()
                except Exception:  # noqa: BLE001
                    pass
    raise AssertionError(f"kafka broker 未就绪（{timeout_s}s）：{last_exc}")


async def _produce(bootstrap: str, messages: list[bytes]) -> None:
    from aiokafka import AIOKafkaProducer

    producer = AIOKafkaProducer(bootstrap_servers=bootstrap)
    await producer.start()
    try:
        for payload in messages:
            await producer.send_and_wait(TOPIC, payload)
    finally:
        await producer.stop()


def _settings() -> StreamSettings:
    from edp_adapters.stream import StreamRoute

    return StreamSettings(
        bootstrap="unused",  # consumer_factory 注入，不用缺省工厂
        group=GROUP,
        routes=[
            RouteEntry(
                StreamRoute(
                    topic=TOPIC,
                    source_system=_SRC,
                    pk_columns=("order_no",),
                    owner_domain="sales",
                    object_type="ORDER",
                ),
                "default",
            )
        ],
        poll_timeout_ms=200,
        retry_backoff_s=0.2,
    )


class _LoopRunner:
    """stream_loop 生命周期封装：起任务、等退出（stop 置位后 ≤2s）。"""

    def __init__(self, engine: AsyncEngine, bootstrap: str):
        self.engine = engine
        self.bootstrap = bootstrap
        self.stop = asyncio.Event()
        self.task: asyncio.Task | None = None

    async def start(self):
        from aiokafka import AIOKafkaConsumer

        def factory(settings):
            return AIOKafkaConsumer(
                *sorted(entry.route.topic for entry in settings.routes),
                bootstrap_servers=self.bootstrap,
                group_id=settings.group,
                enable_auto_commit=False,
                auto_offset_reset="earliest",
            )

        self.task = asyncio.create_task(
            stream_loop(self.engine, _settings(), stop=self.stop, consumer_factory=factory)
        )

    async def stop_and_join(self):
        self.stop.set()
        stats = await asyncio.wait_for(self.task, timeout=10.0)
        return stats


async def _wait_for(predicate, timeout_s: float = _WAIT_S) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if await predicate():
            return
        await asyncio.sleep(0.2)
    raise AssertionError(f"等待条件超时（{timeout_s}s）")


@pytest.fixture(autouse=True)
async def _clean_e2e_rows(db_session: AsyncSession) -> None:
    yield
    await db_session.execute(
        text("""
            DELETE FROM sales.order_lines WHERE order_id IN (
                SELECT object_id FROM master.business_objects WHERE source_system = :s)
        """),
        {"s": _SRC},
    )
    await db_session.execute(
        text("""
            DELETE FROM sales.orders WHERE order_id IN (
                SELECT object_id FROM master.business_objects WHERE source_system = :s)
        """),
        {"s": _SRC},
    )
    for table in (
        "governance.review_records",
        "governance.admission_records",
        "governance.object_classifications",
        "governance.clean_records",
    ):
        await db_session.execute(
            text(f"""
                DELETE FROM {table} WHERE tenant_id IN (
                    SELECT tenant_id FROM master.business_objects
                    WHERE source_system = :s)
            """),
            {"s": _SRC},
        )
    await db_session.execute(
        text("DELETE FROM governance.raw_records WHERE source_system = :s"), {"s": _SRC}
    )
    await db_session.execute(
        text("""
            DELETE FROM platform.audit_logs WHERE
                detail->'after'->>'source_id' LIKE 'SO-K%'
                OR resource_id IN (SELECT event_id::text FROM event.events
                                   WHERE source_system = :s)
        """),
        {"s": _SRC},
    )
    await db_session.execute(
        text("""
            DELETE FROM event.outbox WHERE aggregate_id IN (
                SELECT event_id FROM event.events WHERE source_system = :s)
            OR aggregate_id IN (SELECT object_id FROM master.business_objects
                                WHERE source_system = :s)
        """),
        {"s": _SRC},
    )
    await db_session.execute(
        text("DELETE FROM evidence.records WHERE source_system = :s"), {"s": _SRC}
    )
    await db_session.execute(
        text("DELETE FROM event.events WHERE source_system = :s"), {"s": _SRC}
    )
    await db_session.execute(
        text("DELETE FROM master.business_objects WHERE source_system = :s"), {"s": _SRC}
    )
    await db_session.execute(
        text("DELETE FROM realtime.stream_offsets WHERE consumer_group = :g"), {"g": GROUP}
    )
    await db_session.execute(
        text("DELETE FROM realtime.stream_dlq WHERE topic = :t"), {"t": TOPIC}
    )
    await db_session.commit()


async def _count_events(db_session: AsyncSession, order_no: str) -> int:
    return (
        await db_session.execute(
            text("""
                SELECT count(*) FROM event.events e
                JOIN master.business_objects bo
                  ON bo.object_id = e.object_id AND bo.tenant_id = e.tenant_id
                WHERE e.source_system = :s AND bo.source_id = :sid
                  AND e.data->>'via' = 'capture'
            """),
            {"s": _SRC, "sid": order_no},
        )
    ).scalar_one()


async def test_full_chain_consume_replay_resume(
    kafka_bootstrap: str,
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
) -> None:
    base_ts = int(datetime(2026, 10, 14, 10, 0, tzinfo=UTC).timestamp() * 1000)

    # ---- 阶段一：合法×2 + 毒消息 + 合法×1 → 3 注册 / 1 DLQ ----
    await _produce(
        kafka_bootstrap,
        [
            _envelope("SO-K1", base_ts),
            _envelope("SO-K2", base_ts + 1000),
            _poison(),
            _envelope("SO-K3", base_ts + 2000),
        ],
    )
    runner = _LoopRunner(app_role_engine, kafka_bootstrap)
    await runner.start()

    async def _events_ready():
        return await _at_least_events(db_session, {"SO-K1", "SO-K2", "SO-K3"})

    async def _dlq_ready():
        return await _dlq_count(db_session, TOPIC) >= 1

    async def _offset_is(offset: int):
        return await _stored_offset(db_session, GROUP, TOPIC) == offset

    await _wait_for(_events_ready)
    await _wait_for(_dlq_ready)
    await _wait_for(lambda: _offset_is(3))
    assert await _count_events(db_session, "SO-K1") == 1
    assert await _count_events(db_session, "SO-K2") == 1
    assert await _count_events(db_session, "SO-K3") == 1

    # RAW 留存带 capture 坐标（T45 批次标记）
    raw_batch = (
        await db_session.execute(
            text("""
                SELECT batch_id FROM governance.raw_records
                WHERE source_system = :s AND source_record_id = 'SO-K1'
            """),
            {"s": _SRC},
        )
    ).scalar_one()
    assert raw_batch is not None and raw_batch.startswith(f"capture:{TOPIC}:")

    # ---- 阶段二：幂等重放（同 order_no + 同 ts_ms）→ 事件不增 ----
    await _produce(kafka_bootstrap, [_envelope("SO-K1", base_ts)])
    await _wait_for(lambda: _offset_is(4))
    assert await _count_events(db_session, "SO-K1") == 1  # duplicated 收敛

    # ---- 阶段三：断点续传（停 → 产 → 重启 → 不丢不重） ----
    stats = await runner.stop_and_join()
    assert stats["registered"] == 3
    assert stats["duplicated"] == 1
    assert stats["dlq"] == 1

    await _produce(kafka_bootstrap, [_envelope("SO-K4", base_ts + 3000)])

    runner2 = _LoopRunner(app_role_engine, kafka_bootstrap)
    await runner2.start()
    try:
        await _wait_for(lambda: _at_least_events(db_session, {"SO-K4"}))
        assert await _count_events(db_session, "SO-K4") == 1
        # 旧消息不重放：K1 仍 1 条（seek 到 PG 位点，不从 earliest 重来）
        assert await _count_events(db_session, "SO-K1") == 1
    finally:
        stats2 = await runner2.stop_and_join()
    assert stats2["registered"] == 1
    assert stats2["dlq"] == 0


async def _at_least_events(db_session: AsyncSession, order_nos: set[str]) -> bool:
    for order_no in order_nos:
        if await _count_events(db_session, order_no) < 1:
            return False
    return True


async def _dlq_count(db_session: AsyncSession, topic: str) -> int:
    return (
        await db_session.execute(
            text("SELECT count(*) FROM realtime.stream_dlq WHERE topic = :t"), {"t": topic}
        )
    ).scalar_one()


async def _stored_offset(db_session: AsyncSession, group: str, topic: str) -> int | None:
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    assert factory is not None
    return (
        await db_session.execute(
            text("""
                SELECT partition_offset FROM realtime.stream_offsets
                WHERE consumer_group = :g AND topic = :t AND partition_id = 0
            """),
            {"g": group, "t": topic},
        )
    ).scalar_one_or_none()
