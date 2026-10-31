"""core/db 租户绑定与 RLS 生效的集成测试（testcontainers PG16）。

覆盖：
1. bind_tenant 写入事务级 app.tenant_id（current_tenant_setting 可读回）；
2. RLS 对 edp_app 生效：未绑定 0 行 / 绑定 default 见种子 3 用户 /
   绑定其他租户 0 行 / WITH CHECK 阻断跨租户 INSERT；
3. set_config 事务级语义：同引擎独立 session 不串线，commit 后绑定失效。
"""

from uuid import UUID, uuid4

import pytest
from edp_api.core.db import bind_tenant, current_tenant_setting
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = pytest.mark.integration

DEFAULT_TENANT_SQL = "SELECT tenant_id FROM platform.tenants WHERE slug = 'default'"
COUNT_USERS_SQL = "SELECT count(*) FROM platform.users"


async def test_bind_tenant_sets_transaction_local_setting(db_session) -> None:
    tenant_id: UUID = (await db_session.execute(text(DEFAULT_TENANT_SQL))).scalar_one()
    assert await current_tenant_setting(db_session) is None

    await bind_tenant(db_session, tenant_id)

    assert await current_tenant_setting(db_session) == str(tenant_id)


async def test_rls_isolates_app_role_by_binding(app_session, db_session) -> None:
    default_tenant: UUID = (await db_session.execute(text(DEFAULT_TENANT_SQL))).scalar_one()

    # 未绑定：USING 判 NULL → 0 行
    unbound = (await app_session.execute(text(COUNT_USERS_SQL))).scalar_one()
    assert unbound == 0

    # 绑定 default：种子 3 用户可见
    await bind_tenant(app_session, default_tenant)
    bound = (await app_session.execute(text(COUNT_USERS_SQL))).scalar_one()
    assert bound == 3

    # 对照租户（仅存在于控制面 tenants 表）→ users 0 行
    other_tenant = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO platform.tenants (tenant_id, slug, name, status) "
            "VALUES (:t, 'rls-other', 'RLS对照租户', 'ACTIVE')"
        ),
        {"t": other_tenant},
    )
    await db_session.commit()
    await bind_tenant(app_session, other_tenant)
    other_count = (await app_session.execute(text(COUNT_USERS_SQL))).scalar_one()
    assert other_count == 0

    # WITH CHECK：绑定 default 却插 other 租户的行 → RLS 违规异常
    await bind_tenant(app_session, default_tenant)
    with pytest.raises(DBAPIError):
        await app_session.execute(
            text(
                "INSERT INTO platform.users "
                "(user_id, tenant_id, username, email, password_hash, display_name) "
                "VALUES (:u, :t, 'rls_probe', 'rls_probe@edp.local', 'x', 'RLS探针')"
            ),
            {"u": uuid4(), "t": other_tenant},
        )
    await app_session.rollback()


async def test_binding_is_session_and_transaction_scoped(
    migrated_db: str, app_database_url: str
) -> None:
    engine = create_async_engine(app_database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session1, session2 = factory(), factory()
    try:
        default_tenant: UUID = (
            await session1.execute(text(DEFAULT_TENANT_SQL))
        ).scalar_one()
        await bind_tenant(session1, default_tenant)
        assert (await session1.execute(text(COUNT_USERS_SQL))).scalar_one() == 3

        # 同引擎独立 session（连接）：事务级绑定不串线
        assert await current_tenant_setting(session2) is None
        assert (await session2.execute(text(COUNT_USERS_SQL))).scalar_one() == 0

        # 事务提交后绑定失效（set_config is_local=true）
        await session1.commit()
        assert await current_tenant_setting(session1) is None
        assert (await session1.execute(text(COUNT_USERS_SQL))).scalar_one() == 0
    finally:
        await session1.close()
        await session2.close()
        await engine.dispose()
