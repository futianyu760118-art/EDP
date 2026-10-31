"""uuidv5 确定性单测（T12）：同输入同 UUID / 租户隔离 / 时区等价 / 公式向量。

实现只接受 datetime（occurred_at 归一化在纯函数内完成，无 str 分支）。
"""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid5

from edp_api.modules.events.uuidv5 import (
    derive_event_id,
    normalize_occurred_at,
    tenant_namespace,
)

TENANT_A = UUID("11111111-1111-1111-1111-111111111111")
TENANT_B = UUID("22222222-2222-2222-2222-222222222222")

OCCURRED = datetime(2026, 9, 28, 8, 0, 0, tzinfo=UTC)


def test_tenant_namespace_matches_formula() -> None:
    # tenant_ns = UUIDv5(NIL, str(tenant_id))；NIL == UUID(int=0)
    assert tenant_namespace(TENANT_A) == uuid5(UUID(int=0), str(TENANT_A))
    assert tenant_namespace(TENANT_A) == tenant_namespace(TENANT_A)


def test_same_input_same_uuid() -> None:
    first = derive_event_id(TENANT_A, "erp", "SO-2026-00123", OCCURRED, "order.created")
    second = derive_event_id(
        TENANT_A, "erp", "SO-2026-00123", OCCURRED, "order.created"
    )
    assert first == second
    assert first.version == 5


def test_different_tenant_different_uuid() -> None:
    a = derive_event_id(TENANT_A, "erp", "SO-1", OCCURRED, "order.created")
    b = derive_event_id(TENANT_B, "erp", "SO-1", OCCURRED, "order.created")
    assert a != b  # 命名空间含 tenant_id → 天然租户隔离


def test_any_field_change_changes_uuid() -> None:
    base = derive_event_id(TENANT_A, "erp", "SO-1", OCCURRED, "order.created")
    assert derive_event_id(
        TENANT_A, "mes", "SO-1", OCCURRED, "order.created"
    ) != base  # source_system
    assert derive_event_id(
        TENANT_A, "erp", "SO-2", OCCURRED, "order.created"
    ) != base  # source_id
    assert derive_event_id(
        TENANT_A, "erp", "SO-1", OCCURRED + timedelta(seconds=1), "order.created"
    ) != base  # occurred_at
    assert derive_event_id(
        TENANT_A, "erp", "SO-1", OCCURRED, "order.updated"
    ) != base  # event_type


def test_timezone_equivalence_same_uuid() -> None:
    # 同一时刻：UTC 08:00（naive 视为 UTC）== 10:00+02:00（aware 转 UTC）
    naive_utc = datetime(2026, 9, 28, 8, 0, 0)
    aware_offset = datetime(2026, 9, 28, 10, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    assert normalize_occurred_at(naive_utc) == normalize_occurred_at(aware_offset)
    assert derive_event_id(
        TENANT_A, "erp", "SO-1", naive_utc, "order.created"
    ) == derive_event_id(TENANT_A, "erp", "SO-1", aware_offset, "order.created")


def test_microsecond_precision_is_significant() -> None:
    # 微秒参与 name（毫秒级输入 .123000 与 .123456 是不同时刻）
    milli = datetime(2026, 9, 28, 8, 0, 0, 123000, tzinfo=UTC)
    micro = datetime(2026, 9, 28, 8, 0, 0, 123456, tzinfo=UTC)
    assert derive_event_id(TENANT_A, "erp", "SO-1", milli, "t") != derive_event_id(
        TENANT_A, "erp", "SO-1", micro, "t"
    )


def test_formula_vector() -> None:
    # 黄金向量：name = "{source_system}|{source_id}|{isoformat}|{event_type}"
    name = f"erp|SO-1|{OCCURRED.isoformat()}|order.created"
    expected = uuid5(tenant_namespace(TENANT_A), name)
    assert derive_event_id(TENANT_A, "erp", "SO-1", OCCURRED, "order.created") == expected
