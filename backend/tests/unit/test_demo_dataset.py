"""T5 演示数据集单测：快照段自然键唯一/依赖顺序/偏移窗口；回流段十场景覆盖
与 risk 分布；payload 键与 projections 投影读取键一致（防改名/漏键）。

断言口径：值对齐 frontend MSW fixtures（objects/events/ebms）与设计 B.8 示例；
不触达数据库（纯常量结构断言）。
"""

from collections import Counter
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest
from edp_adapters.demo_dataset import DEMO_ANCHOR, SNAPSHOT_RECORDS, SnapshotSpec
from edp_api.modules.demo.dataset import DEMO_CASE, RESULT_EVENTS
from edp_api.modules.projections import service as projections_service

WINDOW_MINUTES = 14 * 24 * 60

# 投影器读取键：CUSTOMER~PROJECT 直接引用 service 的 _KNOWN_*（同一事实来源），
# BOM / SUPPLIER_LEAD_TIME 投影器未走 _rest（逐键直读），显式列出。
MAPPED_KEYS = {
    "CUSTOMER": projections_service._KNOWN_CUSTOMER_KEYS,
    "MATERIAL": projections_service._KNOWN_MATERIAL_KEYS,
    "PRODUCT": projections_service._KNOWN_PRODUCT_KEYS,
    "SUPPLIER": projections_service._KNOWN_SUPPLIER_KEYS,
    "ORDER": projections_service._KNOWN_ORDER_KEYS,
    "PURCHASE_ORDER": projections_service._KNOWN_PURCHASE_ORDER_KEYS,
    "INVENTORY": projections_service._KNOWN_INVENTORY_KEYS,
    "PROJECT": projections_service._KNOWN_PROJECT_KEYS,
    "BOM": frozenset({"product_code", "bom_version", "status", "items"}),
    "SUPPLIER_LEAD_TIME": frozenset(
        {"supplier_code", "material_code", "lead_time_days"}
    ),
    "CAPACITY": frozenset({"product_line", "period", "capacity_qty"}),
}

# 未映射键的白名单（进 attributes 的业务补充字段；白名单外即改名/笔误）
ALLOWED_EXTRA_KEYS = {
    "CUSTOMER": frozenset({"note"}),
    "MATERIAL": frozenset({"total_available", "reserved"}),
    "PRODUCT": frozenset(),
    "SUPPLIER": frozenset({"lead_time_days", "note", "status", "effective_date"}),
    "ORDER": frozenset({"risk_note", "product", "suppliers", "condition"}),
    "PURCHASE_ORDER": frozenset(),
    "INVENTORY": frozenset(),
    "BOM": frozenset(),
    "SUPPLIER_LEAD_TIME": frozenset(),
    "PROJECT": frozenset(),
    "CAPACITY": frozenset(),
}

ORDER_LINE_KEYS = frozenset(
    {"product_code", "material_code", "quantity", "unit_price", "amount"}
)
BOM_ITEM_KEYS = frozenset({"material_code", "quantity"})
MILESTONE_KEYS = frozenset({"name", "due_date", "actual_date", "status"})

# 依赖分组（列表顺序：master 主数据 → 业务快照 → 项目/产能）
TYPE_RANK = {
    "CUSTOMER": 0,
    "MATERIAL": 0,
    "PRODUCT": 0,
    "SUPPLIER": 0,
    "ORDER": 1,
    "PURCHASE_ORDER": 1,
    "BOM": 1,
    "SUPPLIER_LEAD_TIME": 1,
    "INVENTORY": 1,
    "PROJECT": 2,
    "CAPACITY": 2,
}

ORDER_IDS = {
    "SO-2026-00122",
    "SO-2026-00123",
    "SO-2026-00124",
    "SO-2026-00125",
    "SO-2026-00126",
    "SO-2026-00127",
    "SO-2026-00128",
    "SO-2026-00129",
    "SO-2026-00130",
    "SO-2026-00131",
}


def _key(record: SnapshotSpec) -> tuple[str, str]:
    return (record.object_type, record.source_id)


# ---- 快照段：结构 / 自然键 / 依赖顺序 / 偏移 ----

def test_demo_anchor_matches_msw_demo_now() -> None:
    assert DEMO_ANCHOR == datetime(2026, 9, 28, 8, 30, 0, tzinfo=UTC)


def test_snapshot_records_is_immutable_tuple() -> None:
    assert isinstance(SNAPSHOT_RECORDS, tuple)
    assert len(SNAPSHOT_RECORDS) >= 40  # 十场景故事线规模（约 45 条）


def test_snapshot_natural_keys_unique() -> None:
    keys = [_key(record) for record in SNAPSHOT_RECORDS]
    assert len(keys) == len(set(keys))


def test_snapshot_records_grouped_in_dependency_order() -> None:
    ranks = [TYPE_RANK[record.object_type] for record in SNAPSHOT_RECORDS]
    assert ranks == sorted(ranks)


def test_snapshot_dependency_order_resolvable() -> None:
    seen: set[tuple[str, str]] = set()
    for record in SNAPSHOT_RECORDS:
        payload = record.payload
        if record.object_type == "ORDER":
            assert ("CUSTOMER", payload["customer_code"]) in seen
            for line in payload["lines"]:
                for field in ("product_code", "material_code"):
                    if field in line:
                        ref_type = "PRODUCT" if field == "product_code" else "MATERIAL"
                        assert (ref_type, line[field]) in seen
        elif record.object_type == "PURCHASE_ORDER":
            assert ("SUPPLIER", payload["supplier_code"]) in seen
            assert ("MATERIAL", payload["material_code"]) in seen
        elif record.object_type == "BOM":
            assert ("PRODUCT", payload["product_code"]) in seen
            for item in payload["items"]:
                assert ("MATERIAL", item["material_code"]) in seen
        elif record.object_type == "SUPPLIER_LEAD_TIME":
            assert ("SUPPLIER", payload["supplier_code"]) in seen
            assert ("MATERIAL", payload["material_code"]) in seen
        elif record.object_type == "INVENTORY":
            assert ("MATERIAL", payload["material_code"]) in seen
        elif record.object_type == "PROJECT":
            assert ("PRODUCT", payload["product_code"]) in seen
        seen.add(_key(record))


def test_snapshot_offsets_are_negative_ints_within_window() -> None:
    for record in SNAPSHOT_RECORDS:
        assert isinstance(record.offset_minutes, int)
        assert -WINDOW_MINUTES <= record.offset_minutes < 0


def test_snapshot_spec_is_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        SNAPSHOT_RECORDS[0].source_id = "X"


def test_snapshot_source_systems_match_demo_adapters() -> None:
    assert {record.source_system for record in SNAPSHOT_RECORDS} == {
        "erp",
        "mes",
        "plm",
    }
    plm_types = {
        record.object_type
        for record in SNAPSHOT_RECORDS
        if record.source_system == "plm"
    }
    assert plm_types == {"PRODUCT", "BOM", "PROJECT"}
    mes_types = {
        record.object_type
        for record in SNAPSHOT_RECORDS
        if record.source_system == "mes"
    }
    assert mes_types == {"CAPACITY"}


def test_snapshot_covers_ten_orders() -> None:
    order_ids = {
        record.source_id
        for record in SNAPSHOT_RECORDS
        if record.object_type == "ORDER"
    }
    assert order_ids == ORDER_IDS


# ---- 快照段：payload 键与投影器一致 ----

def test_payload_has_all_projector_read_keys() -> None:
    for record in SNAPSHOT_RECORDS:
        missing = MAPPED_KEYS[record.object_type] - set(record.payload)
        assert not missing, f"{record.object_type}/{record.source_id} 缺键：{missing}"


def test_payload_has_no_unexpected_keys() -> None:
    for record in SNAPSHOT_RECORDS:
        extras = (
            set(record.payload)
            - MAPPED_KEYS[record.object_type]
            - {"owner_domain"}
        )
        unexpected = extras - ALLOWED_EXTRA_KEYS[record.object_type]
        assert not unexpected, (
            f"{record.object_type}/{record.source_id} 未映射键：{unexpected}"
        )


def test_payload_owner_domain_present_and_valid() -> None:
    allowed = {"master", "sales", "procurement", "delivery", "rd"}
    for record in SNAPSHOT_RECORDS:
        assert record.payload["owner_domain"] in allowed


def test_nested_payload_keys_align_with_projector() -> None:
    for record in SNAPSHOT_RECORDS:
        if record.object_type == "ORDER":
            assert record.payload["lines"]
            for line in record.payload["lines"]:
                assert set(line) <= ORDER_LINE_KEYS
                assert {"product_code", "material_code"} & set(line)
                assert {"quantity", "unit_price"} <= set(line)
        elif record.object_type == "BOM":
            assert record.payload["items"]
            for item in record.payload["items"]:
                assert set(item) <= BOM_ITEM_KEYS
                assert {"material_code", "quantity"} <= set(item)
        elif record.object_type == "PROJECT":
            assert record.payload["milestones"]
            for milestone in record.payload["milestones"]:
                assert set(milestone) <= MILESTONE_KEYS
                assert {"name", "status"} <= set(milestone)


# ---- 回流段：十场景覆盖 / risk 分布 / 逐字文案 ----

def test_result_events_cover_ten_scenarios() -> None:
    assert len(RESULT_EVENTS) >= 9
    assert Counter(event.risk_level for event in RESULT_EVENTS) == {
        "P0": 1,
        "P1": 3,
        "P2": 4,
        "P3": 2,
    }
    assert {event.result_type for event in RESULT_EVENTS} == {
        "ORDER_RISK",
        "ORDER_QUALITY",
        "PRODUCT_READINESS",
        "DATA_QUALITY",
        "ADAPTER",
    }
    for event in RESULT_EVENTS:
        assert -WINDOW_MINUTES <= event.offset_minutes < 0
        assert {"summary", "order_no"} <= set(event.data)


def test_result_event_object_refs_resolve_in_snapshot() -> None:
    keys = {_key(record) for record in SNAPSHOT_RECORDS}
    for event in RESULT_EVENTS:
        assert event.object_ref in keys


def test_result_event_summaries_match_ebms_fixtures() -> None:
    data = {(event.event_type, event.object_ref): event.data for event in RESULT_EVENTS}
    assert data[("capability.result.order_risk", ("ORDER", "SO-2026-00129"))][
        "summary"
    ] == "部分物料短缺+产能紧张，综合高风险"
    assert data[("capability.result.order_risk", ("ORDER", "SO-2026-00123"))][
        "summary"
    ] == "物料X缺口1000，预计延误5天"
    assert data[("capability.result.order_quality", ("ORDER", "SO-2026-00126"))][
        "summary"
    ] == "产品F库存不足（仅剩38），大额订单交付风险"
    assert data[("capability.result.order_risk", ("ORDER", "SO-2026-00131"))][
        "summary"
    ] == "供应商S-030即将停产，多源依赖需替代方案"
    assert data[("capability.result.order_risk", ("ORDER", "SO-2026-00124"))][
        "summary"
    ] == "PO-2026-00785 预计到货推迟 2 周"
    assert data[("capability.result.product_readiness", ("PROJECT", "PRJ-D"))][
        "summary"
    ] == "新品D项目验证中，未达量产就绪"
    assert data[("adapter.sync.failed", ("PROJECT", "PRJ-D"))][
        "summary"
    ] == "PLM 同步失败（工具调用故障），里程碑数据待更新"
    assert data[("capability.result.dq_check", ("ORDER", "SO-2026-00130"))][
        "summary"
    ] == "客户ID在ERP存在双记录，需人工确认"


def test_adapter_failure_event_matches_scenario_ten() -> None:
    events = [event for event in RESULT_EVENTS if event.event_type == "adapter.sync.failed"]
    assert len(events) == 1
    event = events[0]
    assert event.result_type == "ADAPTER"
    assert event.risk_level == "P2"
    assert event.source_system == "edp-adapter"
    assert event.actor_type == "SERVICE"
    assert event.actor_id == "adapter:plm"
    assert event.data["adapter"] == "plm"
    assert event.data["order_no"] == "PLM"


def test_demo_case_matches_scenario_two() -> None:
    assert DEMO_CASE.question == "订单 SO-2026-00123 存在缺料风险，是否加急采购物料X？"
    assert DEMO_CASE.risk_level == "P1"
    assert [option.key for option in DEMO_CASE.options] == [
        "EXPEDITE",
        "SUBSTITUTE",
        "REJECT",
    ]
    assert [option.label for option in DEMO_CASE.options] == [
        "加急采购",
        "启用替代料",
        "拒绝建议",
    ]
    assert DEMO_CASE.source_event_ref == ("ORDER", "SO-2026-00123")
    assert DEMO_CASE.evidence_source_refs == (
        ("ORDER", "SO-2026-00123"),
        ("MATERIAL", "X-100"),
        ("PURCHASE_ORDER", "PO-2026-00771"),
    )


def test_demo_case_refs_resolve_in_dataset() -> None:
    snapshot_keys = {_key(record) for record in SNAPSHOT_RECORDS}
    assert set(DEMO_CASE.evidence_source_refs) <= snapshot_keys
    assert DEMO_CASE.source_event_ref in {
        event.object_ref for event in RESULT_EVENTS
    }
