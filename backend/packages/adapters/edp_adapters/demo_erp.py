"""DemoErpAdapter（name="erp-demo"）：演示数据集 erp 段适配器（T6）。

- `build_records(anchor)` 读 `demo_dataset.SNAPSHOT_RECORDS`（纯数据包，
  不依赖 edp_api），取 source_system="erp" 的记录，`occurred_at = anchor +
  timedelta(minutes=offset_minutes)`；anchor 为 None → `DEMO_ANCHOR` 兜底
  （租户未设置 attributes.demo_seed.anchor 时）；
- 纯函数：无随机数、无 now()、无外部 IO——同锚两次构建完全一致（重放走
  UUIDv5 幂等 → duplicated，不产生重复行）；
- fetch_full / fetch_incremental 语义与 ErpMockAdapter 一致：object_types
  为空 = 全集；incremental 严格 > since 且 occurred_at 升序。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .base import AdapterHealth, SourceRecord
from .demo_dataset import DEMO_ANCHOR, SNAPSHOT_RECORDS

SOURCE_SYSTEM = "erp"


def build_records(anchor: datetime | None = None) -> list[SourceRecord]:
    """erp 段演示记录（anchor 为 None → DEMO_ANCHOR 兜底）。"""
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


class DemoErpAdapter:
    """演示 ERP 适配器：相对时间锚的确定性数据集，无外部 IO。"""

    name = "erp-demo"

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
        return AdapterHealth(ok=True, detail="erp demo dataset ready")
