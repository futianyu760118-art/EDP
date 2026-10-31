"""V1.3 T44 stream 端口单测：Debezium 信封 → SourceRecord 纯转换。

契约依据 contracts/realtime/debezium-event.schema.json：
- occurred_at 唯一来源 = payload.ts_ms（源库提交时刻，禁止消费侧 now()）；
- object_type = source.table 大写（须匹配 OBJECT_TYPE_PATTERN），路由可覆写；
- source_id = pk_columns 值拼接（须匹配 SOURCE_ID_PATTERN）；
- op=d / tombstone（after=null）→ None（upsert-only 管道）；
- 解析失败抛 StreamParseError（消费侧进 DLQ，不阻断分区）。
"""

from datetime import UTC, datetime

import pytest
from edp_adapters.stream import (
    StreamParseError,
    StreamRoute,
    parse_debezium_event,
)


def _envelope(
    *,
    op: str = "c",
    table: str = "orders",
    after: dict | None,
    ts_ms: int = 1760000000000,
    before: dict | None = None,
) -> dict:
    return {
        "schema": None,
        "payload": {
            "before": before,
            "after": after,
            "op": op,
            "ts_ms": ts_ms,
            "source": {"db": "scm", "schema": "public", "table": table},
        },
    }


ROUTE = StreamRoute(
    topic="edp.default.scm.orders",
    source_system="scm",
    pk_columns=("order_no",),
    owner_domain="sales",
)


class TestParseDebeziumEvent:
    def test_create_maps_after_payload_and_ts_ms(self):
        record = parse_debezium_event(
            _envelope(op="c", after={"order_no": "SO-001", "amount": 100}), ROUTE
        )
        assert record is not None
        assert record.source_system == "scm"
        assert record.object_type == "ORDERS"
        assert record.source_id == "SO-001"
        assert record.occurred_at == datetime.fromtimestamp(1760000000000 / 1000, tz=UTC)
        assert record.payload["amount"] == 100
        # owner_domain 注入（管道 process_record 必需字段）
        assert record.payload["owner_domain"] == "sales"

    def test_snapshot_read_and_update_map_too(self):
        for op in ("r", "u"):
            record = parse_debezium_event(
                _envelope(op=op, after={"order_no": "SO-002"}), ROUTE
            )
            assert record is not None, op
            assert record.source_id == "SO-002"

    def test_owner_domain_existing_value_not_overwritten(self):
        record = parse_debezium_event(
            _envelope(after={"order_no": "SO-003", "owner_domain": "delivery"}), ROUTE
        )
        assert record is not None
        assert record.payload["owner_domain"] == "delivery"

    def test_object_type_route_override(self):
        route = StreamRoute(
            topic="edp.default.scm.orders",
            source_system="scm",
            pk_columns=("order_no",),
            owner_domain="sales",
            object_type="ORDER",
        )
        record = parse_debezium_event(
            _envelope(table="orders", after={"order_no": "SO-004"}), route
        )
        assert record is not None
        assert record.object_type == "ORDER"

    def test_composite_pk_joined_with_dash(self):
        route = StreamRoute(
            topic="edp.default.scm.inventory",
            source_system="scm",
            pk_columns=("warehouse_code", "sku_code"),
        )
        record = parse_debezium_event(
            _envelope(
                table="inventory",
                after={"warehouse_code": "WH-01", "sku_code": "SKU-9"},
            ),
            route,
        )
        assert record is not None
        assert record.source_id == "WH-01-SKU-9"

    def test_pk_value_cast_to_str(self):
        route = StreamRoute(topic="t", source_system="scm", pk_columns=("id",))
        record = parse_debezium_event(
            _envelope(table="materials", after={"id": 42, "name": "螺母"}), route
        )
        assert record is not None
        assert record.source_id == "42"

    def test_delete_returns_none(self):
        assert parse_debezium_event(_envelope(op="d", after=None), ROUTE) is None

    def test_tombstone_returns_none(self):
        assert (
            parse_debezium_event(_envelope(op="u", after=None, before={"order_no": "X"}), ROUTE)
            is None
        )

    def test_missing_payload_raises(self):
        with pytest.raises(StreamParseError):
            parse_debezium_event({"schema": None}, ROUTE)

    def test_missing_ts_ms_raises(self):
        envelope = _envelope(after={"order_no": "SO-005"})
        del envelope["payload"]["ts_ms"]
        with pytest.raises(StreamParseError):
            parse_debezium_event(envelope, ROUTE)

    def test_missing_pk_column_raises(self):
        with pytest.raises(StreamParseError):
            parse_debezium_event(_envelope(after={"not_a_pk": 1}), ROUTE)

    def test_invalid_table_name_raises(self):
        with pytest.raises(StreamParseError):
            parse_debezium_event(
                _envelope(table="order-items", after={"order_no": "SO-006"}), ROUTE
            )

    def test_source_id_pattern_violation_raises(self):
        with pytest.raises(StreamParseError):
            parse_debezium_event(
                _envelope(after={"order_no": "空 格 不 合 法"}), ROUTE
            )

    def test_missing_source_raises(self):
        envelope = _envelope(after={"order_no": "SO-007"})
        del envelope["payload"]["source"]
        with pytest.raises(StreamParseError):
            parse_debezium_event(envelope, ROUTE)
