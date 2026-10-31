"""testcontainers 集成测试基座（session 级 PG 容器 + alembic 全量迁移）。

- 容器：postgres:16-alpine；超级用户 edp_migrator（edp_migrator/edp_dev，库名 edp）
  由容器环境创建；受 RLS 约束的 edp_app 角色（LOGIN PASSWORD 'edp_app'）由
  0001 迁移的 DO 块幂等创建——即在全新容器内跑通 0001~0005 全量 + 种子，
  这正是 CI 将来的路径。
- 迁移：编程式 alembic command.upgrade（env.py 优先级 -x database_url >
  EDP_DATABASE_URL 环境变量，此处设环境变量后调用）。
- 会话：db_session 以 edp_migrator（超级用户，绕 RLS）直查/造数；
  app_session 以 edp_app 登录（受 RLS 约束）。async 引擎按 function 级
  创建/销毁，避免跨事件循环复用连接池（pytest-asyncio 每测试独立 loop）。
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import quote

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.community.postgres import PostgresContainer

BACKEND_DIR = Path(__file__).resolve().parents[2]

MIGRATOR_USER = "edp_migrator"
MIGRATOR_PASSWORD = "edp_dev"
APP_ROLE_USER = "edp_app"
APP_ROLE_PASSWORD = "edp_app"


@pytest.fixture(scope="session")
def pg_container():
    with PostgresContainer(
        "postgres:16-alpine",
        username=MIGRATOR_USER,
        password=MIGRATOR_PASSWORD,
        dbname="edp",
    ) as container:
        yield container


def _url_for(container: PostgresContainer, username: str, password: str) -> str:
    host = container.get_container_host_ip()
    port = container.get_exposed_port(container.port)
    return (
        f"postgresql+asyncpg://{quote(username)}:{quote(password)}"
        f"@{host}:{port}/{quote(container.dbname)}"
    )


@pytest.fixture(scope="session")
def database_url(pg_container: PostgresContainer) -> str:
    """edp_migrator（超级用户）连接 URL。"""
    return _url_for(pg_container, MIGRATOR_USER, MIGRATOR_PASSWORD)


@pytest.fixture(scope="session")
def app_database_url(pg_container: PostgresContainer) -> str:
    """edp_app（受 RLS 约束角色）连接 URL。"""
    return _url_for(pg_container, APP_ROLE_USER, APP_ROLE_PASSWORD)


@pytest.fixture(scope="session")
def migrated_db(database_url: str) -> str:
    """在全新容器内执行 alembic upgrade head（0001~0005 全量 + 种子），返回 URL。"""
    env_key = "EDP_DATABASE_URL"
    saved = os.environ.get(env_key)
    os.environ[env_key] = database_url
    try:
        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
        command.upgrade(cfg, "head")
    finally:
        if saved is None:
            os.environ.pop(env_key, None)
        else:
            os.environ[env_key] = saved
    return database_url


@pytest.fixture(autouse=True)
async def _relax_rate_limit(migrated_db: str) -> AsyncIterator[None]:
    """EDP-025 限流测试基座：清空进程内令牌桶 + 默认租户配额复位
    （api_rate_limit 提到高位、batch_max_events/query_timeout_ms 回默认），
    避免限流器干扰其他集成用例；限流专项测试（test_ratelimit）自行改低
    配额，下一用例的基座会复位。"""
    from edp_api.modules.tenantmgmt import ratelimit

    ratelimit.reset_buckets()
    engine = create_async_engine(migrated_db)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE platform.tenant_quotas"
                    " SET api_rate_limit = 100000,"
                    " batch_max_events = 1000,"
                    " query_timeout_ms = 5000"
                    " WHERE tenant_id = (SELECT tenant_id FROM platform.tenants"
                    " WHERE slug = 'default')"
                )
            )
        yield
    finally:
        await engine.dispose()


@pytest.fixture
async def db_session(migrated_db: str) -> AsyncIterator[AsyncSession]:
    """edp_migrator 直查会话（超级用户绕 RLS）；收尾回滚，不污染种子。"""
    engine = create_async_engine(migrated_db)
    session = async_sessionmaker(engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        await session.rollback()
        await session.close()
        await engine.dispose()


@pytest.fixture
async def app_session(migrated_db: str, app_database_url: str) -> AsyncIterator[AsyncSession]:
    """edp_app 登录会话（受 RLS 约束）；收尾回滚。"""
    engine = create_async_engine(app_database_url)
    session = async_sessionmaker(engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        await session.rollback()
        await session.close()
        await engine.dispose()


@pytest.fixture
async def app_role_engine(migrated_db: str, app_database_url: str) -> AsyncIterator[AsyncEngine]:
    """edp_app 角色引擎（NOBYPASSRLS，受 RLS 约束）——T10 起集成测试的
    应用连接形态（与生产 api 同角色）：monkeypatch 到 core.db.get_engine 后，
    经 get_db 打开的请求会话全部受 FORCE RLS 约束。"""
    engine = create_async_engine(app_database_url)
    try:
        yield engine
    finally:
        await engine.dispose()
