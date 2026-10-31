"""ErpMock 适配器：确定性 BASE/DELTA 数据集（种子 random.Random(42)）。

时间窗冻结：BASE 60 条铺 2026-08-18T00:00Z ~ 2026-09-14T20:00Z（等差，
首末严格不含端点），DELTA 8 条在 2026-09-15T08:00Z 之后——两次进程实例化
完全一致（模块级构建一次，`_build_datasets()` 可重建验证种子确定性）。
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from .base import AdapterHealth, SourceRecord

WINDOW_START = datetime(2026, 8, 18, 0, 0, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 9, 14, 20, 0, 0, tzinfo=UTC)

SEED = 42

# DELTA 更新的五条既有订单（status → 已发货，amount 微调）
UPDATED_ORDER_IDS = (
    "SO-2026-00203",
    "SO-2026-00207",
    "SO-2026-00212",
    "SO-2026-00218",
    "SO-2026-00225",
)

_BASE_ORDER_IDS = [f"SO-2026-00{i:03d}" for i in range(201, 241)]
_BASE_CUSTOMER_IDS = [f"C-{i}" for i in range(101, 111)]
_BASE_MATERIAL_IDS = [f"M-{i}" for i in range(301, 311)]
_DELTA_NEW_ORDER_IDS = [f"SO-2026-00{i:03d}" for i in range(241, 244)]


def _order_payload(
    rng: random.Random, source_id: str, *, status: str = "已确认", amount: float | None = None
) -> dict:
    if amount is None:
        amount = round(rng.uniform(3, 98) * 10_000, 2)  # 3~98 万
    return {
        "name": f"销售订单 {source_id}",
        "customer_code": f"C-2{rng.randint(0, 99):02d}",
        "amount": amount,
        "currency": "CNY",
        "status": status,
        "delivery_date": f"2026-10-{rng.randint(1, 28):02d}",
        "owner_domain": "sales",
    }


def _build_datasets() -> tuple[list[SourceRecord], list[SourceRecord]]:
    """种子确定性构建（BASE, DELTA）；模块级初始化与确定性单测重放共用。"""
    rng = random.Random(SEED)
    span = WINDOW_END - WINDOW_START

    # 先按构造顺序生成 (object_type, source_id, payload)，再等差铺时间窗
    specs: list[tuple[str, str, dict]] = []
    order_amounts: dict[str, float] = {}
    for source_id in _BASE_ORDER_IDS:
        payload = _order_payload(rng, source_id)
        order_amounts[source_id] = payload["amount"]
        specs.append(("ORDER", source_id, payload))
    for source_id in _BASE_CUSTOMER_IDS:
        specs.append(
            (
                "CUSTOMER",
                source_id,
                {
                    "name": f"客户 {source_id}",
                    "level": rng.choice(["VIP", "普通"]),
                    "owner_domain": "master",
                },
            )
        )
    for source_id in _BASE_MATERIAL_IDS:
        total_available = rng.randint(500, 5000)
        specs.append(
            (
                "MATERIAL",
                source_id,
                {
                    "name": f"物料 {source_id}",
                    "total_available": total_available,
                    "reserved": rng.randint(0, total_available // 2),
                    "unit": "件",
                    "owner_domain": "master",
                },
            )
        )

    # 等差铺时间窗：(i+1)/(N+1) 严格不含端点 → 全部 > 窗口起点、< 窗口终点
    base = [
        SourceRecord(
            source_system="erp",
            object_type=object_type,
            source_id=source_id,
            occurred_at=WINDOW_START + span * (i + 1) / (len(specs) + 1),
            payload=payload,
        )
        for i, (object_type, source_id, payload) in enumerate(specs)
    ]

    delta: list[SourceRecord] = []
    for i, source_id in enumerate(UPDATED_ORDER_IDS):
        payload = _order_payload(
            rng,
            source_id,
            status="已发货",
            amount=order_amounts[source_id] + rng.randint(0, 5000),  # +5000 内微调
        )
        delta.append(
            SourceRecord(
                source_system="erp",
                object_type="ORDER",
                source_id=source_id,
                occurred_at=datetime(2026, 9, 15, 8, 0, 0, tzinfo=UTC)
                + timedelta(hours=4 * i),
                payload=payload,
            )
        )
    for i, source_id in enumerate(_DELTA_NEW_ORDER_IDS):
        payload = _order_payload(rng, source_id)
        delta.append(
            SourceRecord(
                source_system="erp",
                object_type="ORDER",
                source_id=source_id,
                occurred_at=datetime(2026, 9, 16, 10, 0, 0, tzinfo=UTC) + timedelta(hours=i),
                payload=payload,
            )
        )
    return base, delta


BASE, DELTA = _build_datasets()

_ALL = BASE + DELTA


def all_records() -> list[SourceRecord]:
    """源全集（BASE+DELTA），供对账（T14 reconcile）——返回副本，勿改。"""
    return list(_ALL)


class ErpMockAdapter:
    """ERP 模拟适配器：确定性内存数据集，无外部 IO。

    `anchor` 参数（T6 端口扩展）仅为签名对齐：本适配器时间窗已冻结在
    W2 基线常量中，忽略 anchor、行为不变。
    """

    name = "erp"

    def fetch_full(
        self, object_types: list[str], *, anchor: datetime | None = None
    ) -> list[SourceRecord]:
        if not object_types:
            return list(BASE)
        wanted = set(object_types)
        return [record for record in BASE if record.object_type in wanted]

    def fetch_incremental(
        self, since: datetime, *, anchor: datetime | None = None
    ) -> list[SourceRecord]:
        return sorted(
            (record for record in _ALL if record.occurred_at > since),
            key=lambda record: record.occurred_at,
        )

    def health_check(self) -> AdapterHealth:
        return AdapterHealth(ok=True, detail="erp mock ready")
