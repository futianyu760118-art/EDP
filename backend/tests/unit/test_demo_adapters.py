"""T6 演示适配器单测：同锚确定性 / 锚平移仅 occurred_at 变 / 来源过滤 /
DEMO_ANCHOR 兜底 / 跨适配器合并自然键唯一 / fetch_* 语义（类型过滤与
严格 >since、升序）。

纯内存适配器（无数据库、无 IO）；断言口径：erp-demo + plm-demo 两段合并
恰为 SNAPSHOT_RECORDS 全量（不丢、不重）。
"""

from datetime import UTC, datetime, timedelta

from edp_adapters.demo_dataset import DEMO_ANCHOR, SNAPSHOT_RECORDS
from edp_adapters.demo_erp import DemoErpAdapter
from edp_adapters.demo_erp import build_records as build_erp_records
from edp_adapters.demo_plm import DemoPlmAdapter
from edp_adapters.demo_plm import build_records as build_plm_records
from edp_adapters.mes_mock import DemoMesAdapter
from edp_adapters.mes_mock import build_records as build_mes_records

ANCHOR = datetime(2026, 9, 28, 8, 30, 0, tzinfo=UTC)
SHIFT = timedelta(hours=5)
EPOCH = datetime.min.replace(tzinfo=UTC)

_BUILDERS = (build_erp_records, build_plm_records, build_mes_records)
_ADAPTER_BUILDERS = (
    (DemoErpAdapter(), build_erp_records),
    (DemoPlmAdapter(), build_plm_records),
    (DemoMesAdapter(), build_mes_records),
)


def _spec_counts(source_system: str) -> int:
    return sum(1 for spec in SNAPSHOT_RECORDS if spec.source_system == source_system)


# ---- 适配器基本信息 ----


def test_adapter_names_and_health() -> None:
    assert DemoErpAdapter.name == "erp-demo"
    assert DemoPlmAdapter.name == "plm-demo"
    assert DemoMesAdapter.name == "mes-demo"
    assert DemoErpAdapter().health_check().ok is True
    assert DemoPlmAdapter().health_check().ok is True
    assert DemoMesAdapter().health_check().ok is True


# ---- 确定性：同锚两次构建完全一致 ----


def test_same_anchor_builds_identical_records() -> None:
    for build in _BUILDERS:
        assert build(ANCHOR) == build(ANCHOR)


def test_same_anchor_fetch_full_identical() -> None:
    for adapter in (DemoErpAdapter(), DemoPlmAdapter(), DemoMesAdapter()):
        assert adapter.fetch_full([], anchor=ANCHOR) == adapter.fetch_full([], anchor=ANCHOR)


# ---- 锚平移：occurred_at 整体平移，payload 与自然键不变 ----


def test_anchor_shift_moves_occurred_at_only() -> None:
    shifted_anchor = ANCHOR + SHIFT
    for build in _BUILDERS:
        base = build(ANCHOR)
        shifted = build(shifted_anchor)
        assert len(base) == len(shifted)
        for before, after in zip(base, shifted, strict=True):
            assert (
                before.source_system,
                before.object_type,
                before.source_id,
                before.payload,
            ) == (
                after.source_system,
                after.object_type,
                after.source_id,
                after.payload,
            )
            assert after.occurred_at - before.occurred_at == SHIFT


def test_occurred_at_equals_anchor_plus_offset() -> None:
    builders = {
        "erp": build_erp_records,
        "plm": build_plm_records,
        "mes": build_mes_records,
    }
    for spec in SNAPSHOT_RECORDS:
        build = builders[spec.source_system]
        record = next(
            item
            for item in build(ANCHOR)
            if (item.object_type, item.source_id) == (spec.object_type, spec.source_id)
        )
        assert record.occurred_at == ANCHOR + timedelta(minutes=spec.offset_minutes)


# ---- 来源过滤：erp-demo 全 erp / plm-demo 全 plm ----


def test_erp_demo_records_are_all_erp() -> None:
    records = build_erp_records(ANCHOR)
    assert records
    assert {record.source_system for record in records} == {"erp"}
    assert len(records) == _spec_counts("erp")


def test_plm_demo_records_are_all_plm() -> None:
    records = build_plm_records(ANCHOR)
    assert records
    assert {record.source_system for record in records} == {"plm"}
    assert len(records) == _spec_counts("plm")


def test_mes_demo_records_are_all_mes() -> None:
    records = build_mes_records(ANCHOR)
    assert records
    assert {record.source_system for record in records} == {"mes"}
    assert {record.object_type for record in records} == {"CAPACITY"}
    assert len(records) == _spec_counts("mes")


# ---- 兜底：无 anchor → DEMO_ANCHOR ----


def test_build_records_without_anchor_falls_back_to_demo_anchor() -> None:
    for build in _BUILDERS:
        assert build(None) == build(DEMO_ANCHOR)


def test_fetch_without_anchor_falls_back_to_demo_anchor() -> None:
    assert DemoErpAdapter().fetch_full([]) == build_erp_records(DEMO_ANCHOR)
    assert DemoPlmAdapter().fetch_full([]) == build_plm_records(DEMO_ANCHOR)
    assert DemoMesAdapter().fetch_full([]) == build_mes_records(DEMO_ANCHOR)


# ---- 合并：自然键唯一、恰为数据集全量 ----


def test_merged_natural_keys_unique() -> None:
    merged = (
        build_erp_records(ANCHOR)
        + build_plm_records(ANCHOR)
        + build_mes_records(ANCHOR)
    )
    natural_keys = [(record.object_type, record.source_id) for record in merged]
    assert len(natural_keys) == len(set(natural_keys))
    assert len(merged) == len(SNAPSHOT_RECORDS)


def test_merged_records_cover_all_snapshot_specs() -> None:
    merged = (
        build_erp_records(ANCHOR)
        + build_plm_records(ANCHOR)
        + build_mes_records(ANCHOR)
    )
    keys = {(record.object_type, record.source_id) for record in merged}
    expected = {(spec.object_type, spec.source_id) for spec in SNAPSHOT_RECORDS}
    assert keys == expected


# ---- fetch_* 语义（与 ErpMockAdapter 一致） ----


def test_fetch_full_type_filter() -> None:
    erp = DemoErpAdapter()
    all_erp = build_erp_records(ANCHOR)
    assert erp.fetch_full(["ORDER"], anchor=ANCHOR) == [
        record for record in all_erp if record.object_type == "ORDER"
    ]
    assert erp.fetch_full(["ORDER", "CUSTOMER"], anchor=ANCHOR) == [
        record for record in all_erp if record.object_type in {"ORDER", "CUSTOMER"}
    ]

    plm = DemoPlmAdapter()
    all_plm = build_plm_records(ANCHOR)
    assert plm.fetch_full(["PRODUCT"], anchor=ANCHOR) == [
        record for record in all_plm if record.object_type == "PRODUCT"
    ]


def test_fetch_incremental_since_filter_and_order() -> None:
    since = ANCHOR - timedelta(hours=6)
    for adapter, build in _ADAPTER_BUILDERS:
        expected = sorted(
            (record for record in build(ANCHOR) if record.occurred_at > since),
            key=lambda record: record.occurred_at,
        )
        assert adapter.fetch_incremental(since, anchor=ANCHOR) == expected


def test_fetch_incremental_far_future_is_empty() -> None:
    for adapter, _ in _ADAPTER_BUILDERS:
        assert adapter.fetch_incremental(ANCHOR + timedelta(days=365), anchor=ANCHOR) == []


def test_fetch_incremental_epoch_returns_all() -> None:
    for adapter, build in _ADAPTER_BUILDERS:
        expected = sorted(build(ANCHOR), key=lambda record: record.occurred_at)
        assert adapter.fetch_incremental(EPOCH, anchor=ANCHOR) == expected
