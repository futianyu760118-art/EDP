"""T3 projections 纯映射助手单测：_rest / _parse_dt / _line_amount / _decimal
边界（None/缺键/ISO 串/金额计算）+ 投影器分派表覆盖 + 未知类型静默跳过。

不触达数据库：分派表断言以模块常量比对，未知类型用"爆炸会话"证明零访问。
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest
from edp_adapters.base import SourceRecord
from edp_api.modules.projections import service as projections_service

MAPPED_TYPES = {
    "CUSTOMER",
    "MATERIAL",
    "PRODUCT",
    "SUPPLIER",
    "ORDER",
    "PURCHASE_ORDER",
    "INVENTORY",
    "BOM",
    "SUPPLIER_LEAD_TIME",
    "PROJECT",
    "CAPACITY",
}


# ---- 分派表与常量 ----


def test_projectors_cover_all_mapped_types() -> None:
    assert set(projections_service._PROJECTORS) == MAPPED_TYPES


def test_resolvable_types_are_master_data() -> None:
    assert projections_service.RESOLVABLE_TYPES == {
        "CUSTOMER",
        "MATERIAL",
        "PRODUCT",
        "SUPPLIER",
    }


class _ExplodingSession:
    """任何属性访问即失败：证明未知类型不触达会话。"""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"未知类型不应触达会话：{name}")


async def test_project_record_unknown_type_skips_silently() -> None:
    record = SourceRecord(
        source_system="erp",
        object_type="TICKET",
        source_id="T-1",
        occurred_at=datetime(2026, 9, 28, tzinfo=UTC),
        payload={},
    )
    await projections_service.project_record(
        cast(Any, _ExplodingSession()), uuid4(), record, uuid4()
    )


# ---- _rest ----


def test_rest_strips_known_keys_and_owner_domain() -> None:
    payload = {"name": "n", "level": "VIP", "owner_domain": "master", "extra": 1}
    assert projections_service._rest(payload, frozenset({"name", "level"})) == {"extra": 1}


def test_rest_keeps_none_values_of_unknown_keys() -> None:
    payload = {"known": 1, "missing": None}
    assert projections_service._rest(payload, frozenset({"known"})) == {"missing": None}


def test_rest_empty_payload() -> None:
    assert projections_service._rest({}, frozenset({"name"})) == {}


def test_rest_does_not_mutate_payload() -> None:
    payload = {"owner_domain": "master", "extra": 1}
    projections_service._rest(payload, frozenset())
    assert payload == {"owner_domain": "master", "extra": 1}


# ---- _parse_dt ----


@pytest.mark.parametrize("value", [None, "", "not-a-date", "2026-13-01", 123, {"d": 1}, [1]])
def test_parse_dt_invalid_returns_none(value: Any) -> None:
    assert projections_service._parse_dt(value) is None


def test_parse_dt_aware_passthrough() -> None:
    value = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
    assert projections_service._parse_dt(value) is value


def test_parse_dt_naive_datetime_assumes_utc() -> None:
    assert projections_service._parse_dt(datetime(2026, 10, 20, 8, 0)) == datetime(
        2026, 10, 20, 8, 0, tzinfo=UTC
    )


def test_parse_dt_date_to_midnight_utc() -> None:
    assert projections_service._parse_dt(date(2026, 10, 20)) == datetime(
        2026, 10, 20, tzinfo=UTC
    )


def test_parse_dt_iso_with_z_suffix() -> None:
    assert projections_service._parse_dt("2026-10-20T08:30:00Z") == datetime(
        2026, 10, 20, 8, 30, tzinfo=UTC
    )


def test_parse_dt_iso_with_offset() -> None:
    assert projections_service._parse_dt("2026-10-20T16:30:00+08:00") == datetime(
        2026, 10, 20, 8, 30, tzinfo=UTC
    )


def test_parse_dt_iso_naive_assumes_utc() -> None:
    assert projections_service._parse_dt("2026-10-20T08:30:00") == datetime(
        2026, 10, 20, 8, 30, tzinfo=UTC
    )


def test_parse_dt_date_only_string() -> None:
    assert projections_service._parse_dt("2026-10-20") == datetime(2026, 10, 20, tzinfo=UTC)


# ---- _line_amount ----


def test_line_amount_explicit_value_wins() -> None:
    assert projections_service._line_amount(
        {"amount": "12.5", "quantity": 2, "unit_price": 100}
    ) == Decimal("12.5")


def test_line_amount_computes_quantity_times_price() -> None:
    assert projections_service._line_amount(
        {"quantity": 500, "unit_price": 240.0}
    ) == Decimal("120000")


def test_line_amount_zero_quantity_is_not_missing() -> None:
    assert projections_service._line_amount(
        {"quantity": 0, "unit_price": 240}
    ) == Decimal("0")


def test_line_amount_missing_unit_price_returns_none() -> None:
    assert projections_service._line_amount({"quantity": 500}) is None


def test_line_amount_missing_quantity_returns_none() -> None:
    assert projections_service._line_amount({"unit_price": 240}) is None


def test_line_amount_empty_line_returns_none() -> None:
    assert projections_service._line_amount({}) is None


def test_line_amount_invalid_numbers_return_none() -> None:
    assert projections_service._line_amount(
        {"quantity": "many", "unit_price": 240}
    ) is None


# ---- _decimal ----


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (1, Decimal("1")),
        (2.5, Decimal("2.5")),
        ("3.25", Decimal("3.25")),
        (Decimal("4.5"), Decimal("4.5")),
        ("abc", None),
        ({}, None),
    ],
)
def test_decimal_normalization(value: Any, expected: Decimal | None) -> None:
    assert projections_service._decimal(value) == expected
