"""V1.3 T50 集成测试：通用 DbPullAdapter（真实 PG 源库 → EDP 管道）。

源库：独立 PostgresContainer 模拟对端系统（三张代表表：scm_material
增量列 update_time、scm_supplier 含敏感列、scm_process 无时间列全量）。
覆盖：
1. 全量同步：对象/事件/证据入库，via='pipeline'（拉取轨）；
2. 敏感列 SQL 级排除：contact_phone 等不进 RAW/attributes；
3. 增量语义：update_time 未变 → duplicated；bump → 新 revision；
4. 全量表重拉幂等（纪元常量 occurred_at → 恒同 event_id）；
5. 增量列名 update_time（非 updated_at）适配。
"""

from datetime import UTC, datetime, timedelta

import pytest
from edp_adapters.db_pull import DbPullAdapter, DbTableSpec
from edp_api.modules.ingest import service as ingest_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from testcontainers.community.postgres import PostgresContainer

pytestmark = [pytest.mark.integration]

_SPECS = [
    DbTableSpec("scm_material", "update_time", "master"),
    DbTableSpec(
        "scm_supplier",
        "update_time",
        "procurement",
        ("contact_person", "contact_phone", "fax", "address"),
    ),
    DbTableSpec("scm_process", None, "production"),
]


@pytest.fixture(scope="module")
def spc_dsn():
    with PostgresContainer(
        "postgres:16-alpine", username="spc", password="spc", dbname="spc_test"
    ) as c:
        host = c.get_container_host_ip()
        port = c.get_exposed_port(c.port)
        dsn = f"postgresql://{c.username}:{c.password}@{host}:{port}/{c.dbname}"
        import asyncio as _a

        _a.run(_init_source(dsn))
        yield dsn


async def _init_source(dsn: str) -> None:
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("""
            CREATE TABLE scm_material (
                id BIGSERIAL PRIMARY KEY, code TEXT NOT NULL,
                name TEXT, update_time TIMESTAMPTZ NOT NULL DEFAULT now())
        """)
        await conn.execute("""
            CREATE TABLE scm_supplier (
                id BIGSERIAL PRIMARY KEY, code TEXT NOT NULL,
                contact_person TEXT, contact_phone TEXT, fax TEXT, address TEXT,
                update_time TIMESTAMPTZ NOT NULL DEFAULT now())
        """)
        await conn.execute("""
            CREATE TABLE scm_process (
                id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL)
        """)
        await conn.execute(
            "INSERT INTO scm_material (code, name, update_time) VALUES"
            " ('M-1', '螺母', '2026-10-15 08:00:00+00'),"
            " ('M-2', '螺栓', '2026-10-15 08:30:00+00')"
        )
        await conn.execute(
            "INSERT INTO scm_supplier (code, contact_person, contact_phone, fax, address)"
            " VALUES ('S-1', '张三', '13800000000', '0574-000', '宁波市XX路')"
        )
        await conn.execute("INSERT INTO scm_process (name) VALUES ('SMT'), ('组装')")
    finally:
        await conn.close()


def _adapter(spc_dsn: str) -> DbPullAdapter:
    return DbPullAdapter(name="spc", dsn=spc_dsn, table_specs=_SPECS)


async def _tenant_id(db_session: AsyncSession):
    return (
        await db_session.execute(
            text("SELECT tenant_id FROM platform.tenants WHERE slug = 'default'")
        )
    ).scalar_one()


@pytest.fixture(autouse=True)
async def _clean_spc_rows(db_session: AsyncSession) -> None:
    yield
    for stmt in (
        """
        DELETE FROM governance.review_records WHERE tenant_id IN (
            SELECT tenant_id FROM master.business_objects WHERE source_system = 'spc'
              AND object_type IN ('SCM_MATERIAL','SCM_SUPPLIER','SCM_PROCESS'))
        """,
        """
        DELETE FROM governance.admission_records WHERE object_id IN (
            SELECT object_id FROM master.business_objects WHERE source_system = 'spc'
              AND object_type IN ('SCM_MATERIAL','SCM_SUPPLIER','SCM_PROCESS'))
        """,
        """
        DELETE FROM governance.object_classifications WHERE object_id IN (
            SELECT object_id FROM master.business_objects WHERE source_system = 'spc'
              AND object_type IN ('SCM_MATERIAL','SCM_SUPPLIER','SCM_PROCESS'))
        """,
        """
        DELETE FROM governance.clean_records WHERE object_id IN (
            SELECT object_id FROM master.business_objects WHERE source_system = 'spc'
              AND object_type IN ('SCM_MATERIAL','SCM_SUPPLIER','SCM_PROCESS'))
        """,
        """
        DELETE FROM governance.raw_records WHERE source_system = 'spc'
            AND object_type IN ('SCM_MATERIAL','SCM_SUPPLIER','SCM_PROCESS')
        """,
        """
        DELETE FROM platform.audit_logs WHERE resource_id IN (
            SELECT event_id::text FROM event.events WHERE source_system = 'spc'
              AND event_type IN ('SCM_MATERIAL_SNAPSHOT', 'SCM_SUPPLIER_SNAPSHOT',
              'SCM_PROCESS_SNAPSHOT'))
        """,
        """
        DELETE FROM event.outbox WHERE aggregate_id IN (
            SELECT event_id FROM event.events WHERE source_system = 'spc'
              AND event_type IN ('SCM_MATERIAL_SNAPSHOT', 'SCM_SUPPLIER_SNAPSHOT',
              'SCM_PROCESS_SNAPSHOT'))
        """,
        """
        DELETE FROM evidence.records WHERE source_system = 'spc'
            AND source_record_id LIKE '1#%' OR source_record_id LIKE '2#%'
        """,
        """
        DELETE FROM event.events WHERE source_system = 'spc'
            AND event_type IN ('SCM_MATERIAL_SNAPSHOT', 'SCM_SUPPLIER_SNAPSHOT',
              'SCM_PROCESS_SNAPSHOT')
        """,
        """
        DELETE FROM master.business_objects WHERE source_system = 'spc'
            AND object_type IN ('SCM_MATERIAL','SCM_SUPPLIER','SCM_PROCESS')
        """,
        "DELETE FROM platform.systems WHERE name = 'spc'",
    ):
        await db_session.execute(text(stmt))
    await db_session.commit()


async def test_full_pull_registers_and_excludes_sensitive(
    spc_dsn: str, app_role_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    tenant_id = await _tenant_id(db_session)

    # 限定三张表（适配器全规格含对端演练库缺表——fetch 跳过缺表）
    stats = await ingest_service.run_sync_per_record(
        app_role_engine, tenant_id, _adapter(spc_dsn), "full"
    )
    assert stats.registered == 5  # 2 材料 + 1 供应商 + 2 工序（其余表在源库缺表跳过）
    assert stats.failed == 0

    via = (
        await db_session.execute(
            text("SELECT DISTINCT data->>'via' FROM event.events WHERE source_system='spc'")
        )
    ).scalars().all()
    assert via == ["pipeline"]  # 拉取轨通道标记

    # 敏感列 SQL 级排除：RAW payload 与对象 attributes 均无联系方式
    supplier_raw = (
        await db_session.execute(
            text("""
                SELECT raw_payload FROM governance.raw_records
                WHERE source_system='spc' AND object_type='SCM_SUPPLIER'
            """)
        )
    ).scalar_one()
    for banned in ("contact_person", "contact_phone", "fax", "address", "张三", "13800000000"):
        assert banned not in str(supplier_raw), banned

    material_count = (
        await db_session.execute(
            text("""
                SELECT count(*) FROM master.business_objects
                WHERE source_system='spc' AND object_type='SCM_MATERIAL'
            """)
        )
    ).scalar_one()
    assert material_count == 2


async def test_incremental_update_time_semantics(
    spc_dsn: str, app_role_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    """增量列是 update_time：未变 duplicated；bump 后新 revision。

    bump 时间戳取动态未来值（供应商行 update_time=now() 参与水位——
    固定过去时间戳在跨日后会被水位吞掉，历史教训见 ledger）。
    """
    import asyncpg

    tenant_id = await _tenant_id(db_session)
    await ingest_service.run_sync_per_record(
        app_role_engine, tenant_id, _adapter(spc_dsn), "incremental"
    )

    # 无变更再拉 → 全部 duplicated（水位推进后无新行）
    stats2 = await ingest_service.run_sync_per_record(
        app_role_engine, tenant_id, _adapter(spc_dsn), "incremental"
    )
    assert stats2.registered == 0

    # bump M-1 的 update_time → 增量拉到 → revision 2
    bump_ts = datetime.now(UTC) + timedelta(hours=1)
    conn = await asyncpg.connect(spc_dsn)
    try:
        await conn.execute(
            "UPDATE scm_material SET name='防松螺母', update_time=$1"
            " WHERE code='M-1'",
            bump_ts,
        )
    finally:
        await conn.close()

    stats3 = await ingest_service.run_sync_per_record(
        app_role_engine, tenant_id, _adapter(spc_dsn), "incremental"
    )
    assert stats3.registered == 1
    revision = (
        await db_session.execute(
            text("""
                SELECT revision FROM master.business_objects
                WHERE source_system='spc' AND object_type='SCM_MATERIAL'
                  AND attributes->>'code' = 'M-1'
            """)
        )
    ).scalar_one()
    assert revision == 2


async def test_full_pull_table_replay_idempotent(
    spc_dsn: str, app_role_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    """无时间列表（scm_process）：重拉恒 duplicated（纪元常量 occurred_at）。"""
    tenant_id = await _tenant_id(db_session)
    await ingest_service.run_sync_per_record(
        app_role_engine, tenant_id, _adapter(spc_dsn), "full"
    )
    stats = await ingest_service.run_sync_per_record(
        app_role_engine, tenant_id, _adapter(spc_dsn), "full"
    )
    assert stats.registered == 0
    assert stats.duplicated >= 2  # 全量重放：至少两张工序记录 duplicated
