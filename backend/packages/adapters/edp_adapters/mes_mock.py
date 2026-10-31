"""DemoMesAdapter（name="mes-demo"）：演示数据集 mes 段适配器（EDP-017 剩余）。

与 demo_erp/demo_plm 同构（确定性 / 锚平移 / 无 IO），仅 source_system 过滤
为 "mes"（CAPACITY——场景 7 产能紧张）：

- `build_records(anchor)` 读 `demo_dataset.SNAPSHOT_RECORDS`，取
  source_system="mes" 的记录，`occurred_at = anchor + offset_minutes`；
  anchor 为 None → `DEMO_ANCHOR` 兜底；
- fetch_full / fetch_incremental 语义与 ErpMockAdapter 一致：object_types
  为空 = 全集；incremental 严格 > since 且 occurred_at 升序。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .base import AdapterHealth, SourceRecord
from .demo_dataset import DEMO_ANCHOR, SNAPSHOT_RECORDS

SOURCE_SYSTEM = "mes"


def build_records(anchor: datetime | None = None) -> list[SourceRecord]:
    """mes 段演示记录（anchor 为 None → DEMO_ANCHOR 兜底）。"""
    resolved = anchor if anchor is not None else DEMO_ANCHOR
    return [
        SourceRecord(
            source_system=spec.source_system,
            object_type=spec.object_type,
            source_id=spec.source_id,
            occurred_at=resolved + timedelta(minutes=spec.offset_minutes),
            payload=dict(spec.payload),
        )
        for spec in SNAPSHOT_RECORDS
        if spec.source_system == SOURCE_SYSTEM
    ]


class DemoMesAdapter:
    """演示 MES 适配器：相对时间锚的确定性产能数据集，无外部 IO。"""

    name = "mes-demo"

    def fetch_full(
        self, object_types: list[str], *, anchor: datetime | None = None
    ) -> list[SourceRecord]:
        records = build_records(anchor)
        if not object_types:
            return records
        wanted = set(object_types)
        return [record for record in records if record.object_type in wanted]

    def fetch_incremental(
        self, since: datetime, *, anchor: datetime | None = None
    ) -> list[SourceRecord]:
        return sorted(
            (record for record in build_records(anchor) if record.occurred_at > since),
            key=lambda record: record.occurred_at,
        )

    def health_check(self) -> AdapterHealth:
        return AdapterHealth(ok=True, detail="mes demo dataset ready")
