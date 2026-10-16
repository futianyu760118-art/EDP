"""V1.3 T50a 集成测试：0019 迁移语义（systems.adapter_config JSONB）。

覆盖：
1. adapter_config 列存在（可空、无默认——既有行不受影响）；
2. catalog 注册携带 adapter_config 落库、adapter_mode 置 'real'；
3. RLS 语义不变：edp_app 仅见本租户行（造数按 (tenant, name) 隔离）。
"""

import pytest
from edp_api.core.db import bind_tenant
from edp_api.core.security.principal import Principal
from edp_api.modules.catalog import service as catalog_service
from edp_api.modules.catalog.schemas import SystemCreateRequest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

pytestmark = [pytest.mark.integration]


def _principal(tenant_id) -> Principal:
    return Principal(id="test-admin", kind="USER", tenant_id=tenant_id)


async def _tenant_id(db_session: AsyncSession):
    return (
        await db_session.execute(
            text("SELECT tenant_id FROM platform.tenants WHERE slug = 'default'")
        )
    ).scalar_one()


async def test_adapter_config_column_exists(db_session: AsyncSession) -> None:
    cols = set(
        (
            await db_session.execute(
                text("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = 'platform' AND table_name = 'systems'
                """)
            )
        ).scalars()
    )
    assert "adapter_config" in cols


async def test_create_system_with_adapter_config_sets_real_mode(
    app_role_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    tenant_id = await _tenant_id(db_session)
    factory = async_sessionmaker(app_role_engine, expire_on_commit=False)
    async with factory() as sess:
        await bind_tenant(sess, tenant_id)
        system = await catalog_service.create_system(
            sess,
            _principal(tenant_id),
            SystemCreateRequest(
                name="t50-probe",
                type="DB_PULL",
                adapter_config={
                    "dsn": "postgresql://x:y@127.0.0.1:5432/x",
                    "tables": [{"table": "scm_material", "increment_column": "update_time"}],
                },
            ),
        )
        await sess.commit()
        system_id = system.system_id

    row = (
        await db_session.execute(
            text("""
                SELECT adapter_config, adapter_mode FROM platform.systems
                WHERE system_id = :sid
            """),
            {"sid": system_id},
        )
    ).mappings().one()
    assert row["adapter_config"]["dsn"].startswith("postgresql://")
    assert row["adapter_config"]["tables"][0]["table"] == "scm_material"
    assert row["adapter_mode"] == "real"

    # 清场（migrator 绕 RLS）
    await db_session.execute(
        text("DELETE FROM platform.systems WHERE system_id = :sid"), {"sid": system_id}
    )
    await db_session.commit()


async def test_systems_rls_unaffected(
    app_role_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    """既有 RLS 语义：edp_app 绑本租户可见、他租户上下文 0 行。"""
    tenant_id = await _tenant_id(db_session)
    factory = async_sessionmaker(app_role_engine, expire_on_commit=False)
    async with factory() as sess:
        await bind_tenant(sess, tenant_id)
        system = await catalog_service.create_system(
            sess,
            _principal(tenant_id),
            SystemCreateRequest(name="t50-rls-probe", type="DB_PULL"),
        )
        await sess.commit()
        system_id = system.system_id

    session = async_sessionmaker(app_role_engine)()
    try:
        await bind_tenant(session, tenant_id)
        visible = (
            await session.execute(
                text("SELECT count(*) FROM platform.systems WHERE system_id = :sid"),
                {"sid": system_id},
            )
        ).scalar_one()
        assert visible == 1
        from uuid import uuid4

        await bind_tenant(session, uuid4())
        other = (
            await session.execute(text("SELECT count(*) FROM platform.systems"))
        ).scalar_one()
        assert other == 0
    finally:
        await session.rollback()
        await session.close()
        await db_session.execute(
            text("DELETE FROM platform.systems WHERE system_id = :sid"), {"sid": system_id}
        )
        await db_session.commit()
