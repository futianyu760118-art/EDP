"""V1.3 T47 集成测试：reconcile_capture（CDC 轨 vs 拉取轨双轨对账）。

语义（方案 V1.3 §2.4）：拉取轨全集计数（adapter.fetch_incremental(纪元)）
vs capture 轨事件计数（event_type LIKE %_SNAPSHOT AND data->>'via' =
'capture'），按 object_type 逐行对比；ok = source == capture。

造数：capture 侧经 process_record(via="capture") 落 3×ORDER + 1×MATERIAL；
拉取侧用进程内替身适配器返回同源 3×ORDER（无 MATERIAL）→ 期望
ORDER 行 ok=True、MATERIAL 行 source=0/capture=1 ok=False。

痕迹隔离：pull 源 'scm-recon-pull' / capture 源 'scm-recon-cap'。
"""

from datetime import UTC, datetime

import pytest
from edp_adapters import AdapterHealth
from edp_adapters.base import SourceRecord
from edp_api.core.db import bind_tenant
from edp_api.modules.ingest import service as ingest_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

pytestmark = [pytest.mark.integration]

_PULL = "scm-recon-pull"
_CAP = "scm-recon-cap"
_TS = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)


def _cap_record(object_type: str, source_id: str) -> SourceRecord:
    return SourceRecord(
        source_system=_CAP,
        object_type=object_type,
        source_id=source_id,
        occurred_at=_TS,
        payload={"code": source_id, "owner_domain": "master"},
    )


class _PullAdapter:
    """拉取轨替身：同源 3×ORDER 快照（不感知 MATERIAL）。"""

    name = _PULL

    def __init__(self) -> None:
        self._records = [
            SourceRecord(
                source_system=_PULL,
                object_type="ORDER",
                source_id=f"SO-R-{i}",
                occurred_at=_TS,
                payload={"code": f"SO-R-{i}", "owner_domain": "sales"},
            )
            for i in (1, 2, 3)
        ]

    def fetch_full(self, object_types, *, anchor=None):
        return list(self._records)

    def fetch_incremental(self, since, *, anchor=None):
        return list(self._records)

    def health_check(self):  # pragma: no cover - 协议补齐
        return AdapterHealth(ok=True)


def _sources() -> str:
    return f"('{_PULL}','{_CAP}')"


@pytest.fixture(autouse=True)
async def _clean_recon_rows(db_session: AsyncSession) -> None:
    yield
    await db_session.execute(
        text(f"""
            DELETE FROM sales.order_lines WHERE order_id IN (
                SELECT object_id FROM master.business_objects
                WHERE source_system IN {_sources()})
        """)
    )
    await db_session.execute(
        text(f"""
            DELETE FROM sales.orders WHERE order_id IN (
                SELECT object_id FROM master.business_objects
                WHERE source_system IN {_sources()})
        """)
    )
    await db_session.execute(
        text(f"""
            DELETE FROM master.materials WHERE material_id IN (
                SELECT object_id FROM master.business_objects
                WHERE source_system IN {_sources()})
        """)
    )
    for table in (
        "governance.review_records",
        "governance.admission_records",
        "governance.object_classifications",
        "governance.clean_records",
    ):
        await db_session.execute(
            text(f"""
                DELETE FROM {table} WHERE tenant_id IN (
                    SELECT tenant_id FROM master.business_objects
                    WHERE source_system IN {_sources()})
            """)
        )
    await db_session.execute(
        text(f"DELETE FROM governance.raw_records WHERE source_system IN {_sources()}")
    )
    await db_session.execute(
        text(f"""
            DELETE FROM platform.audit_logs WHERE
                detail->'after'->>'source_id' LIKE 'SO-R-%'
                OR detail->'after'->>'source_id' LIKE 'M-R-%'
                OR resource_id IN (SELECT event_id::text FROM event.events
                                   WHERE source_system IN {_sources()})
        """)
    )
    await db_session.execute(
        text(f"""
            DELETE FROM event.outbox WHERE aggregate_id IN (
                SELECT event_id FROM event.events WHERE source_system IN {_sources()})
            OR aggregate_id IN (SELECT object_id FROM master.business_objects
                                WHERE source_system IN {_sources()})
        """)
    )
    await db_session.execute(
        text(f"DELETE FROM evidence.records WHERE source_system IN {_sources()}")
    )
    await db_session.execute(
        text(f"DELETE FROM event.events WHERE source_system IN {_sources()}")
    )
    await db_session.execute(
        text(f"DELETE FROM master.business_objects WHERE source_system IN {_sources()}")
    )
    await db_session.commit()


async def _default_tenant_id(db_session: AsyncSession):
    return (
        await db_session.execute(
            text("SELECT tenant_id FROM platform.tenants WHERE slug = 'default'")
        )
    ).scalar_one()


async def test_reconcile_capture_detects_deviation(
    app_role_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    tenant_id = await _default_tenant_id(db_session)

    # capture 侧造数：3×ORDER + 1×MATERIAL（via='capture'）
    factory = async_sessionmaker(app_role_engine, expire_on_commit=False)
    async with factory() as sess:
        await bind_tenant(sess, tenant_id)
        for object_type, source_id in [
            ("ORDER", "SO-R-1"),
            ("ORDER", "SO-R-2"),
            ("ORDER", "SO-R-3"),
            ("MATERIAL", "M-R-1"),
        ]:
            await ingest_service.process_record(
                sess, tenant_id, _cap_record(object_type, source_id), via="capture"
            )
        await sess.commit()

    async with factory() as sess:
        await bind_tenant(sess, tenant_id)
        rows = await ingest_service.reconcile_capture(
            sess, tenant_id, _PullAdapter(), capture_source_system=_CAP
        )

    by_type = {row.object_type: row for row in rows}
    assert by_type["ORDER"].source_count == 3
    assert by_type["ORDER"].capture_count == 3
    assert by_type["ORDER"].ok is True
    # 拉取轨无 MATERIAL → 偏差行可见（source=0 / capture=1）
    assert by_type["MATERIAL"].source_count == 0
    assert by_type["MATERIAL"].capture_count == 1
    assert by_type["MATERIAL"].ok is False


async def test_reconcile_capture_excludes_pipeline_channel(
    app_role_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    """via='pipeline' 的同源事件不计入 capture 轨（通道过滤正确性）。"""
    tenant_id = await _default_tenant_id(db_session)
    factory = async_sessionmaker(app_role_engine, expire_on_commit=False)
    async with factory() as sess:
        await bind_tenant(sess, tenant_id)
        # pipeline 通道写入一条（应为 capture 计数不可见）
        await ingest_service.process_record(
            sess, tenant_id, _cap_record("ORDER", "SO-R-9")
        )
        await sess.commit()

    async with factory() as sess:
        await bind_tenant(sess, tenant_id)
        rows = await ingest_service.reconcile_capture(
            sess, tenant_id, _PullAdapter(), capture_source_system=_CAP
        )

    order = next(row for row in rows if row.object_type == "ORDER")
    assert order.source_count == 3
    assert order.capture_count == 0
    assert order.ok is False
