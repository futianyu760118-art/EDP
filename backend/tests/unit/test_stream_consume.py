"""V1.3 T44d 单测：stream 消费核心逻辑（注入替身，不碰 Kafka/DB）。

覆盖：
1. 路由配置解析（合法/非法字段、from_env 缺省禁用）；
2. _consume_one：registered / duplicated / 解析失败→DLQ+位点推进 /
   管道失败→位点不推进异常上抛；
3. stream_loop（fake consumer）：好/坏消息混合推进、未知 topic→DLQ、
   管道瞬时失败重试成功、stop 优雅退出。
"""

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from edp_adapters.stream import StreamRoute
from edp_worker.stream_consume import (
    RouteEntry,
    StreamSettings,
    _consume_one,
    _parse_routes,
    stream_loop,
)


def _msg(topic: str, offset: int, payload: dict | Any, partition: int = 0) -> SimpleNamespace:
    value = payload if isinstance(payload, (bytes, bytearray)) else json.dumps(payload).encode()
    return SimpleNamespace(topic=topic, partition=partition, offset=offset, value=bytes(value))


def _envelope(order_no: str = "SO-1", op: str = "c") -> dict:
    return {
        "payload": {
            "before": None,
            "after": {"order_no": order_no, "amount": 1, "owner_domain": "sales"},
            "op": op,
            "ts_ms": 1760000000000,
            "source": {"db": "scm", "schema": "public", "table": "orders"},
        }
    }


class _Recorder:
    def __init__(self, result: bool = True, fail_times: int = 0, exc: Exception | None = None):
        self.result = result
        self.fail_times = fail_times
        self.exc = exc or RuntimeError("db down")
        self.process_calls: list[Any] = []
        self.offsets: list[tuple[str, int, int]] = []
        self.dlq: list[tuple[str, int, int, str]] = []

    async def process(self, record, tenant_id, coords):
        self.process_calls.append((record, coords))
        if self.fail_times > 0:
            self.fail_times -= 1
            raise self.exc
        return self.result

    async def advance(self, group, topic, partition, offset):
        self.offsets.append((topic, partition, offset))

    async def dlq_write(self, topic, partition, offset, error, raw):
        self.dlq.append((topic, partition, offset, error))


class TestRouteParsing:
    def test_valid_routes(self):
        routes = _parse_routes(
            json.dumps([
                {
                    "topic": "edp.default.scm.orders",
                    "source_system": "scm",
                    "pk_columns": ["order_no"],
                    "owner_domain": "sales",
                    "object_type": "ORDER",
                    "tenant": "default",
                }
            ])
        )
        assert len(routes) == 1
        entry = routes[0]
        assert entry.route.source_system == "scm"
        assert entry.route.pk_columns == ("order_no",)
        assert entry.route.object_type == "ORDER"
        assert entry.tenant == "default"

    def test_minimal_route_defaults(self):
        routes = _parse_routes(
            json.dumps([{"topic": "t1", "source_system": "scm", "tenant": "default"}])
        )
        assert routes[0].route.pk_columns == ("id",)
        assert routes[0].route.owner_domain == "master"
        assert routes[0].route.object_type is None

    def test_missing_topic_rejected(self):
        with pytest.raises(ValueError):
            _parse_routes(json.dumps([{"source_system": "scm", "tenant": "default"}]))

    def test_duplicate_topic_rejected(self):
        raw = json.dumps([
            {"topic": "t", "source_system": "scm", "tenant": "default"},
            {"topic": "t", "source_system": "scm2", "tenant": "default"},
        ])
        with pytest.raises(ValueError):
            _parse_routes(raw)

    def test_from_env_disabled_without_bootstrap(self):
        assert StreamSettings.from_env({}) is None
        assert StreamSettings.from_env({"EDP_STREAM_KAFKA_BOOTSTRAP": ""}) is None

    def test_from_env_full(self):
        env = {
            "EDP_STREAM_KAFKA_BOOTSTRAP": "localhost:9092",
            "EDP_STREAM_GROUP": "g1",
            "EDP_STREAM_ROUTES": json.dumps(
                [{"topic": "t", "source_system": "scm", "tenant": "default"}]
            ),
        }
        settings = StreamSettings.from_env(env)
        assert settings is not None
        assert settings.bootstrap == "localhost:9092"
        assert settings.group == "g1"
        assert settings.routes[0].route.topic == "t"


class TestConsumeOne:
    async def test_registered_advances_offset(self):
        rec = _Recorder(result=True)
        status = await _consume_one(
            _msg("t", 3, _envelope()),
            route=StreamRoute("t", "scm", pk_columns=("order_no",)),
            tenant_id="tenant-uuid",
            group="g",
            process=rec.process,
            advance_offset=rec.advance,
            write_dlq=rec.dlq_write,
        )
        assert status == "registered"
        assert rec.offsets == [("t", 0, 3)]
        assert rec.dlq == []

    async def test_duplicated_still_advances(self):
        rec = _Recorder(result=False)
        status = await _consume_one(
            _msg("t", 4, _envelope()),
            route=StreamRoute("t", "scm", pk_columns=("order_no",)),
            tenant_id="tenant-uuid",
            group="g",
            process=rec.process,
            advance_offset=rec.advance,
            write_dlq=rec.dlq_write,
        )
        assert status == "duplicated"
        assert rec.offsets == [("t", 0, 4)]

    async def test_parse_error_goes_dlq_and_advances(self):
        rec = _Recorder()
        # 缺 ts_ms 的信封（after 已置，非 tombstone）——真解析错误 → DLQ
        status = await _consume_one(
            _msg(
                "t",
                5,
                {"payload": {"op": "c", "after": {"order_no": "SO-X"},
                             "source": {"table": "orders"}}},
            ),
            route=StreamRoute("t", "scm", pk_columns=("order_no",)),
            tenant_id="tenant-uuid",
            group="g",
            process=rec.process,
            advance_offset=rec.advance,
            write_dlq=rec.dlq_write,
        )
        assert status == "dlq"
        assert rec.process_calls == []
        assert len(rec.dlq) == 1
        topic, partition, offset, error = rec.dlq[0]
        assert (topic, partition, offset) == ("t", 0, 5)
        assert "ts_ms" in error
        assert rec.offsets == [("t", 0, 5)]

    async def test_tombstone_skips_but_advances(self):
        rec = _Recorder()
        status = await _consume_one(
            _msg("t", 8, {"payload": {"op": "d", "ts_ms": 1, "source": {"table": "orders"}}}),
            route=StreamRoute("t", "scm", pk_columns=("order_no",)),
            tenant_id="tenant-uuid",
            group="g",
            process=rec.process,
            advance_offset=rec.advance,
            write_dlq=rec.dlq_write,
        )
        assert status == "skipped"
        assert rec.process_calls == []
        assert rec.dlq == []
        assert rec.offsets == [("t", 0, 8)]

    async def test_invalid_json_goes_dlq(self):
        rec = _Recorder()
        status = await _consume_one(
            _msg("t", 6, b"not-json{"),
            route=StreamRoute("t", "scm"),
            tenant_id="tenant-uuid",
            group="g",
            process=rec.process,
            advance_offset=rec.advance,
            write_dlq=rec.dlq_write,
        )
        assert status == "dlq"
        assert rec.offsets == [("t", 0, 6)]

    async def test_pipeline_failure_propagates_without_advance(self):
        rec = _Recorder(fail_times=1)
        with pytest.raises(RuntimeError, match="db down"):
            await _consume_one(
                _msg("t", 7, _envelope()),
                route=StreamRoute("t", "scm", pk_columns=("order_no",)),
                tenant_id="tenant-uuid",
                group="g",
                process=rec.process,
                advance_offset=rec.advance,
                write_dlq=rec.dlq_write,
            )
        assert rec.offsets == []


class _FakeConsumer:
    """最小消费替身：预置消息批次（aiokafka 形态 dict）+ 订阅记录。"""

    def __init__(self, batches: list[list[Any]]):
        grouped: dict[Any, list[Any]] = {}
        for batch in batches:
            for m in batch:
                grouped.setdefault((m.topic, m.partition), []).append(m)
        self._batches = [grouped]
        self.started = False
        self.stopped = False

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def getmany(self, timeout_ms=500):
        if self._batches:
            return self._batches.pop(0)
        await asyncio.sleep(timeout_ms / 1000)
        return {}

    def subscribe(self, topics, listener=None):
        self._topics = topics
        self._listener = listener


class TestStreamLoop:
    async def test_mixed_batch_processes_and_dlqs(self, monkeypatch):
        rec = _Recorder(result=True)
        consumer = _FakeConsumer(
            [
                [
                    _msg("t", 1, _envelope("SO-1")),
                    _msg(
                        "t",
                        2,
                        {"payload": {"op": "c", "after": {"order_no": "SO-X"},
                                     "source": {"table": "orders"}}},
                    ),  # 缺 ts_ms → DLQ
                    _msg("t", 3, _envelope("SO-3")),
                ]
            ]
        )
        stop = asyncio.Event()
        entries = [RouteEntry(StreamRoute("t", "scm", pk_columns=("order_no",)), "default")]
        settings = StreamSettings(
            bootstrap="x", group="g", routes=entries, poll_timeout_ms=10
        )

        async def _set_stop_after_first_batch():
            await asyncio.sleep(0.2)
            stop.set()

        guard = asyncio.create_task(_set_stop_after_first_batch())
        # engine 参数不被触碰（DB 依赖全部注入）
        stats = await stream_loop(
            None,
            settings,
            stop=stop,
            consumer_factory=lambda s: consumer,
            resolve_tenant=lambda engine, slug: asyncio.sleep(0, "tid"),
            process=rec.process,
            advance_offset=rec.advance,
            write_dlq=rec.dlq_write,
        )
        await guard
        assert stats["registered"] == 2
        assert stats["dlq"] == 1
        assert sorted(rec.offsets) == [("t", 0, 1), ("t", 0, 2), ("t", 0, 3)]
        assert consumer.stopped is True

    async def test_unknown_topic_dlqs(self):
        rec = _Recorder()
        consumer = _FakeConsumer([[_msg("other", 0, _envelope())]])
        stop = asyncio.Event()
        settings = StreamSettings(
            bootstrap="x", group="g",
            routes=[RouteEntry(StreamRoute("t", "scm"), "default")],
            poll_timeout_ms=10,
        )

        async def _stop_soon():
            await asyncio.sleep(0.2)
            stop.set()

        guard = asyncio.create_task(_stop_soon())
        stats = await stream_loop(
            None, settings, stop=stop,
            consumer_factory=lambda s: consumer,
            resolve_tenant=lambda engine, slug: asyncio.sleep(0, "tid"),
            process=rec.process,
            advance_offset=rec.advance,
            write_dlq=rec.dlq_write,
        )
        await guard
        assert stats["dlq"] == 1
        assert "no route" in rec.dlq[0][3]

    async def test_transient_failure_retries_then_advances(self):
        rec = _Recorder(result=True, fail_times=1)
        consumer = _FakeConsumer([[_msg("t", 9, _envelope("SO-9"))]])
        stop = asyncio.Event()
        settings = StreamSettings(
            bootstrap="x", group="g",
            routes=[RouteEntry(StreamRoute("t", "scm", pk_columns=("order_no",)), "default")],
            poll_timeout_ms=10,
            retry_backoff_s=0.01,
        )

        async def _stop_soon():
            await asyncio.sleep(0.3)
            stop.set()

        guard = asyncio.create_task(_stop_soon())
        stats = await stream_loop(
            None, settings, stop=stop,
            consumer_factory=lambda s: consumer,
            resolve_tenant=lambda engine, slug: asyncio.sleep(0, "tid"),
            process=rec.process,
            advance_offset=rec.advance,
            write_dlq=rec.dlq_write,
        )
        await guard
        assert stats["registered"] == 1
        assert len(rec.process_calls) == 2  # 首次失败 + 重试成功
        assert rec.offsets == [("t", 0, 9)]
