"""ErpMock 适配器单测（T13）：确定性重放 / BASE 计数与类型过滤 /
incremental 语义（严格 >since、升序、恰 8 条 DELTA）/ 注册表 / payload 结构。
"""

from datetime import UTC, datetime

import pytest
from edp_adapters import (
    AdapterHealth,
    AdapterRegistry,
    ErpMockAdapter,
    SourceRecord,
    all_records,
)
from edp_adapters.erp_mock import _build_datasets

UPDATES = {
    "SO-2026-00203",
    "SO-2026-00207",
    "SO-2026-00212",
    "SO-2026-00218",
    "SO-2026-00225",
}
NEW_ORDERS = {"SO-2026-00241", "SO-2026-00242", "SO-2026-00243"}


def _snapshot(record: SourceRecord) -> tuple:
    return (
        record.source_system,
        record.object_type,
        record.source_id,
        record.occurred_at.isoformat(),
        record.payload,
    )


class _StubAdapter:
    name = "stub"

    def fetch_full(self, object_types: list[str]) -> list[SourceRecord]:
        return []

    def fetch_incremental(self, since: datetime) -> list[SourceRecord]:
        return []

    def health_check(self) -> AdapterHealth:
        return AdapterHealth(ok=True)


# ---- 确定性：种子重建两次全等；两实例 fetch_full 全等 ----


def test_dataset_rebuild_deterministic() -> None:
    base1, delta1 = _build_datasets()
    base2, delta2 = _build_datasets()
    assert [_snapshot(r) for r in base1] == [_snapshot(r) for r in base2]
    assert [_snapshot(r) for r in delta1] == [_snapshot(r) for r in delta2]


def test_two_instances_fetch_full_equal() -> None:
    first = ErpMockAdapter().fetch_full([])
    second = ErpMockAdapter().fetch_full([])
    assert [_snapshot(r) for r in first] == [_snapshot(r) for r in second]


# ---- 计数与类型过滤 ----


def test_fetch_full_counts_by_type() -> None:
    records = ErpMockAdapter().fetch_full([])
    assert len(records) == 60
    by_type: dict[str, int] = {}
    for record in records:
        by_type[record.object_type] = by_type.get(record.object_type, 0) + 1
    assert by_type == {"ORDER": 40, "CUSTOMER": 10, "MATERIAL": 10}


def test_fetch_full_type_filter() -> None:
    adapter = ErpMockAdapter()
    orders = adapter.fetch_full(["ORDER"])
    assert len(orders) == 40
    assert {r.object_type for r in orders} == {"ORDER"}
    assert {r.source_id for r in orders} == {f"SO-2026-00{i:03d}" for i in range(201, 241)}
    # 全类型显式列出 == 空列表（全部）
    assert adapter.fetch_full(["ORDER", "CUSTOMER", "MATERIAL"]) == adapter.fetch_full([])


# ---- incremental 语义：严格 >、升序、DELTA 边界 ----


def test_incremental_since_window_end_returns_delta_only() -> None:
    records = ErpMockAdapter().fetch_incremental(datetime(2026, 9, 14, 20, 0, 0, tzinfo=UTC))
    assert len(records) == 8
    assert {r.source_id for r in records} == UPDATES | NEW_ORDERS
    times = [r.occurred_at for r in records]
    assert times == sorted(times)  # occurred_at 升序
    update_times = [r.occurred_at for r in records if r.source_id in UPDATES]
    new_times = [r.occurred_at for r in records if r.source_id in NEW_ORDERS]
    assert max(update_times) < min(new_times)  # 五更新在前，三新在后
    assert all(r.payload["status"] == "已发货" for r in records if r.source_id in UPDATES)


def test_incremental_strictly_after_since() -> None:
    # 窗口终点恰为 since 的记录不存在；BASE 全部 <= 窗口终点 → 无混入
    adapter = ErpMockAdapter()
    latest_base = max(r.occurred_at for r in adapter.fetch_full([]))
    assert latest_base < datetime(2026, 9, 14, 20, 0, 0, tzinfo=UTC)


def test_incremental_since_future_is_empty() -> None:
    assert ErpMockAdapter().fetch_incremental(datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC)) == []


def test_incremental_since_before_all_returns_everything() -> None:
    records = ErpMockAdapter().fetch_incremental(datetime(2026, 8, 18, 0, 0, 0, tzinfo=UTC))
    assert len(records) == 68
    assert len(all_records()) == 68


# ---- 注册表 ----


def test_registry_register_get_list_lookup_error() -> None:
    registry = AdapterRegistry()
    adapter = ErpMockAdapter()
    registry.register(adapter)
    assert registry.get("erp") is adapter
    assert registry.list() == ["erp"]
    registry.register(_StubAdapter())
    assert registry.list() == ["erp", "stub"]
    with pytest.raises(LookupError) as exc_info:
        registry.get("crm")
    assert "crm" in str(exc_info.value)  # 错误信息含 adapter 名


# ---- payload 结构与端口行为 ----


def test_payload_owner_domain_and_order_fields() -> None:
    records = all_records()
    assert records
    assert all("owner_domain" in r.payload for r in records)
    orders = [r for r in records if r.object_type == "ORDER"]
    assert len(orders) == 48  # 40 BASE + 5 更新 + 3 新
    assert all({"amount", "currency", "status"} <= set(r.payload) for r in orders)
    assert all(r.occurred_at.tzinfo is not None for r in records)  # UTC aware
    assert all(r.source_system == "erp" for r in records)


def test_health_check_ok() -> None:
    health = ErpMockAdapter().health_check()
    assert health.ok is True


def test_all_records_returns_copy() -> None:
    snapshot = all_records()
    snapshot.clear()
    assert len(all_records()) == 68
