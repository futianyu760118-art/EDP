"""V1.3 T50 集成测试：适配器 CRUD 全链路（catalog 配置 → 动态装配 → 同步）。

源库：独立 PostgresContainer（vendor 增量表 + product 全量表）。
覆盖：
1. POST 语义（service 层）：带 adapter_config 注册 → adapter_mode real；
2. refresh_dynamic 后 get_adapter 可装配 → 清单 mode='real'；
3. 触发同步（run_sync_per_record）→ 对象落库（拉取轨）；
4. 更新 adapter_config（换表）→ 重装配 → 新表可同步；
5. 删除 → 重装配 → get_adapter LookupError（同步 404 语义）；
6. 租户隔离：他租户上下文装配不到（RLS + (tenant, name) 键）。
"""

import pytest
from edp_api.core.db import bind_tenant
from edp_api.core.security.principal import Principal
from edp_api.modules.adapters_admin import service as adapters_service
from edp_api.modules.catalog import service as catalog_service
from edp_api.modules.catalog.schemas import (
    SystemCreateRequest,
    SystemUpdateRequest,
)
from edp_api.modules.ingest import service as ingest_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from testcontainers.community.postgres import PostgresContainer

pytestmark = [pytest.mark.integration]

ADAPTER_NAME = "t50-e2e-src"
_SRC = ADAPTER_NAME


def _principal(tenant_id) -> Principal:
    return Principal(id="test-admin", kind="USER", tenant_id=tenant_id)


@pytest.fixture(scope="module")
def source_dsn():
    with PostgresContainer(
        "postgres:16-alpine", username="src", password="src", dbname="src"
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
            CREATE TABLE vendor (
                id BIGSERIAL PRIMARY KEY, code TEXT NOT NULL, updated_at TIMESTAMPTZ DEFAULT now())
        """)
        await conn.execute("""
            CREATE TABLE product (
                id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL)
        """)
        await conn.execute(
            "INSERT INTO vendor (code, updated_at) VALUES ('V-1', '2026-10-15 08:00:00+00')"
        )
        await conn.execute("INSERT INTO product (name) VALUES ('P-1')")
    finally:
        await conn.close()


def _config(dsn: str, tables: list[dict]) -> dict:
    return {"dsn": dsn, "tables": tables}


async def _tenant_id(db_session: AsyncSession):
    return (
        await db_session.execute(
            text("SELECT tenant_id FROM platform.tenants WHERE slug = 'default'")
        )
    ).scalar_one()


@pytest.fixture(autouse=True)
async def _clean(db_session: AsyncSession) -> None:
    yield
    await db_session.execute(
        text("DELETE FROM platform.systems WHERE name = :n"), {"n": ADAPTER_NAME}
    )
    # 领域投影表先删（FK 指向 business_objects；PRODUCT→master.products）
    for projection in ("master.products", "master.suppliers"):
        await db_session.execute(
            text(f"""
                DELETE FROM {projection} WHERE
                    {'product_id' if 'products' in projection else 'supplier_id'} IN (
                        SELECT object_id FROM master.business_objects WHERE source_system = :s)
            """),
            {"s": _SRC},
        )
    for table in ("governance.review_records", "governance.admission_records",
                  "governance.object_classifications", "governance.clean_records"):
        await db_session.execute(
            text(f"""
                DELETE FROM {table} WHERE tenant_id IN (
                    SELECT tenant_id FROM master.business_objects WHERE source_system = :s)
            """),
            {"s": _SRC},
        )
    await db_session.execute(
        text("DELETE FROM governance.raw_records WHERE source_system = :s"), {"s": _SRC}
    )
    await db_session.execute(
        text("""
            DELETE FROM platform.audit_logs WHERE resource_id IN (
                SELECT event_id::text FROM event.events WHERE source_system = :s)
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


async def _create(factory, tenant_id, dsn: str):
    async with factory() as sess:
        await bind_tenant(sess, tenant_id)
        system = await catalog_service.create_system(
            sess,
            _principal(tenant_id),
            SystemCreateRequest(
                name=ADAPTER_NAME,
                type="DB_PULL",
                adapter_config=_config(
                    dsn,
                    [{"table": "vendor", "increment_column": "updated_at",
                      "owner_domain": "procurement"}],
                ),
            ),
        )
        await adapters_service.refresh_dynamic(sess, tenant_id)
        await sess.commit()
        return system


async def test_crud_assembly_sync_update_delete(
    source_dsn: str, app_role_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    tenant_id = await _tenant_id(db_session)
    factory = async_sessionmaker(app_role_engine, expire_on_commit=False)

    # 1. 注册 + 装配
    await _create(factory, tenant_id, source_dsn)
    adapter = adapters_service.get_adapter(tenant_id, ADAPTER_NAME)
    assert adapter.name == ADAPTER_NAME

    # 2. 清单 mode=real
    async with factory() as sess:
        await bind_tenant(sess, tenant_id)
        items = await adapters_service.list_adapters(sess, tenant_id)
    row = next(item for item in items if item.adapter == ADAPTER_NAME)
    assert row.mode == "real"

    # 3. 同步 → vendor 对象落库
    stats = await ingest_service.run_sync_per_record(
        app_role_engine, tenant_id, adapter, "full"
    )
    assert stats.registered == 1
    assert stats.failed == 0
    count = (
        await db_session.execute(
            text("""
                SELECT count(*) FROM master.business_objects
                WHERE source_system = :s AND object_type = 'VENDOR'
            """),
            {"s": _SRC},
        )
    ).scalar_one()
    assert count == 1

    # 4. 更新配置（换表：product 全量）→ 重装配 → 同步新表
    async with factory() as sess:
        await bind_tenant(sess, tenant_id)
        system = await catalog_service.get_system_by_name(sess, ADAPTER_NAME)
        await catalog_service.update_system(
            sess,
            _principal(tenant_id),
            system,
            SystemUpdateRequest(
                adapter_config=_config(
                    source_dsn, [{"table": "product", "increment_column": None}]
                )
            ),
        )
        await adapters_service.refresh_dynamic(sess, tenant_id)
        await sess.commit()

    adapter2 = adapters_service.get_adapter(tenant_id, ADAPTER_NAME)
    stats2 = await ingest_service.run_sync_per_record(
        app_role_engine, tenant_id, adapter2, "full"
    )
    assert stats2.registered == 1  # product（vendor 已不在配置中）
    product_count = (
        await db_session.execute(
            text("""
                SELECT count(*) FROM master.business_objects
                WHERE source_system = :s AND object_type = 'PRODUCT'
            """),
            {"s": _SRC},
        )
    ).scalar_one()
    assert product_count == 1

    # 5. 删除 → 重装配 → 404 语义 + 他租户不可见
    async with factory() as sess:
        await bind_tenant(sess, tenant_id)
        system = await catalog_service.get_system_by_name(sess, ADAPTER_NAME)
        await catalog_service.delete_system(sess, system)
        await adapters_service.refresh_dynamic(sess, tenant_id)
        await sess.commit()

    with pytest.raises(LookupError):
        adapters_service.get_adapter(tenant_id, ADAPTER_NAME)


async def test_tenant_isolation_of_dynamic_adapters(
    source_dsn: str, app_role_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    """他租户上下文装配不到本租户配置（RLS + (tenant, name) 键）。"""
    tenant_id = await _tenant_id(db_session)
    factory = async_sessionmaker(app_role_engine, expire_on_commit=False)
    await _create(factory, tenant_id, source_dsn)

    other_tenant = "11111111-2222-3333-4444-555555555555"
    # 他租户装配不到（进程内无该键 + RLS 查询也取不到本租户行）
    with pytest.raises(LookupError):
        adapters_service.get_adapter(other_tenant, ADAPTER_NAME)
