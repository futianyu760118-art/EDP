"""V1.3 T45 集成测试：process_record 的 capture 通道标记（via / batch_id）。

实时消费侧（T44d）以 via="capture" + batch_id="capture:{topic}:{partition}:
{offset}" 调 process_record；拉取/CSV 侧不传参保持 "pipeline" 既有语义。
断言：事件 data.via、审计 detail.via、RAW.batch_id 三处通道标记落库，
其余管道语义（三元组/幂等）不变。

痕迹隔离：source_system='scm-cap'（兄弟模块不使用）；每测试后 migrator 清场。
"""

import pytest
from edp_adapters.base import SourceRecord
from edp_api.core.db import bind_tenant
from edp_api.modules.ingest import service as ingest_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

pytestmark = [pytest.mark.integration]

_SRC = "scm-cap"


def _record(
    source_id: str = "SO-CAP-001", ts_iso: str = "2026-10-14T08:00:00+00:00"
) -> SourceRecord:
    from datetime import datetime

    return SourceRecord(
        source_system=_SRC,
        object_type="ORDER",
        source_id=source_id,
        occurred_at=datetime.fromisoformat(ts_iso),
        payload={"order_no": source_id, "amount": 10, "owner_domain": "sales"},
    )


async def _default_tenant_id(db_session: AsyncSession):
    return (
        await db_session.execute(
            text("SELECT tenant_id FROM platform.tenants WHERE slug = 'default'")
        )
    ).scalar_one()


@pytest.fixture(autouse=True)
async def _clean_capture_rows(db_session: AsyncSession) -> None:
    yield
    # 领域投影子表先删（FK 指向 business_objects）
    await db_session.execute(
        text("""
            DELETE FROM sales.order_lines WHERE order_id IN (
                SELECT object_id FROM master.business_objects WHERE source_system = :s)
        """),
        {"s": _SRC},
    )
    await db_session.execute(
        text("""
            DELETE FROM sales.orders WHERE order_id IN (
                SELECT object_id FROM master.business_objects WHERE source_system = :s)
        """),
        {"s": _SRC},
    )
    # governance 子表先于父（review→admission→classification→clean→raw）
    await db_session.execute(
        text("""
            DELETE FROM governance.review_records WHERE tenant_id IN (
                SELECT tenant_id FROM master.business_objects WHERE source_system = :s)
        """),
        {"s": _SRC},
    )
    await db_session.execute(
        text("""
            DELETE FROM governance.admission_records WHERE object_id IN (
                SELECT object_id FROM master.business_objects WHERE source_system = :s)
        """),
        {"s": _SRC},
    )
    await db_session.execute(
        text("""
            DELETE FROM governance.object_classifications WHERE object_id IN (
                SELECT object_id FROM master.business_objects WHERE source_system = :s)
        """),
        {"s": _SRC},
    )
    await db_session.execute(
        text("""
            DELETE FROM governance.clean_records WHERE object_id IN (
                SELECT object_id FROM master.business_objects WHERE source_system = :s)
        """),
        {"s": _SRC},
    )
    await db_session.execute(
        text("DELETE FROM governance.raw_records WHERE source_system = :s"), {"s": _SRC}
    )
    await db_session.execute(
        text("""
            DELETE FROM platform.audit_logs WHERE
                detail->'after'->>'source_id' LIKE 'SO-CAP-%'
                OR detail->>'source_id' LIKE 'SO-CAP-%'
                OR resource_id IN (SELECT event_id::text FROM event.events
                                   WHERE source_system = :s)
        """),
        {"s": _SRC},
    )
    await db_session.execute(
        text("""
            DELETE FROM event.outbox WHERE aggregate_id IN (
                SELECT event_id FROM event.events WHERE source_system = :s)
            OR aggregate_id IN (SELECT object_id FROM master.business_objects
                                WHERE source_system = :s)
        """),
        {"s": _SRC},
    )
    await db_session.execute(
        text("DELETE FROM evidence.records WHERE source_system = :s"), {"s": _SRC}
    )
    await db_session.execute(
        text("DELETE FROM event.events WHERE source_system = :s"), {"s": _SRC}
    )
    await db_session.execute(
        text("DELETE FROM master.business_objects WHERE source_system = :s"), {"s": _SRC}
    )
    await db_session.commit()


async def test_capture_channel_marks_via_and_batch_id(
    app_role_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    """via='capture' → 事件 data / 审计 detail / RAW batch_id 三处标记。"""
    tenant_id = await _default_tenant_id(db_session)
    factory = async_sessionmaker(app_role_engine, expire_on_commit=False)

    async with factory() as sess:
        await bind_tenant(sess, tenant_id)
        registered = await ingest_service.process_record(
            sess,
            tenant_id,
            _record(),
            via="capture",
            batch_id="capture:edp.default.scm.orders:0:5",
        )
        await sess.commit()
    assert registered is True

    via = (
        await db_session.execute(
            text("SELECT data->>'via' FROM event.events WHERE source_system = :s"),
            {"s": _SRC},
        )
    ).scalar_one()
    assert via == "capture"

    raw_batch = (
        await db_session.execute(
            text("""
                SELECT batch_id FROM governance.raw_records
                WHERE source_system = :s AND source_record_id = 'SO-CAP-001'
            """),
            {"s": _SRC},
        )
    ).scalar_one()
    assert raw_batch == "capture:edp.default.scm.orders:0:5"

    audit_via = (
        await db_session.execute(
            text("""
                SELECT detail->>'via' FROM platform.audit_logs
                WHERE action = 'EVENT_CREATE'
                  AND resource_id IN (SELECT event_id::text FROM event.events
                                      WHERE source_system = :s)
            """),
            {"s": _SRC},
        )
    ).scalar_one()
    assert audit_via == "capture"


async def test_default_via_stays_pipeline(
    app_role_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    """不传参 → 既有 'pipeline' 语义不变（回归护栏）。"""
    tenant_id = await _default_tenant_id(db_session)
    factory = async_sessionmaker(app_role_engine, expire_on_commit=False)

    async with factory() as sess:
        await bind_tenant(sess, tenant_id)
        await ingest_service.process_record(sess, tenant_id, _record("SO-CAP-002"))
        await sess.commit()

    via = (
        await db_session.execute(
            text("SELECT data->>'via' FROM event.events WHERE source_system = :s"),
            {"s": _SRC},
        )
    ).scalar_one()
    assert via == "pipeline"
    raw_batch = (
        await db_session.execute(
            text("""
                SELECT batch_id FROM governance.raw_records
                WHERE source_system = :s AND source_record_id = 'SO-CAP-002'
            """),
            {"s": _SRC},
        )
    ).scalar_one()
    assert raw_batch is None
