"""Alembic 环境（asyncpg 异步引擎，run_sync 模式）。

- 版本目录：migrations/versions/{platform,master,event,misc} 多目录、单线性链。
- URL 解析优先级：alembic -x database_url > 环境变量 EDP_DATABASE_URL >
  DATABASE_URL > 缺省值（本地 tools 库，宿主 5432 被占用故用 15432）。
- 迁移全部为显式 SQL（op.execute），不使用 target_metadata / autogenerate。
"""

import asyncio
import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False：迁移与 pytest 同进程时不得禁用既有 logger
    # （否则后续测试的 caplog 捕获被破坏）
    fileConfig(config.config_file_name, disable_existing_loggers=False)

DEFAULT_DATABASE_URL = "postgresql+asyncpg://edp_migrator:edp_dev@localhost:15432/edp"

_MIGRATIONS_DIR = Path(__file__).resolve().parent
_VERSION_PARTS = ("platform", "master", "event", "misc")

# 多版本目录（与 alembic.ini 中 version_locations 一致）。CLI 场景下 ScriptDirectory
# 在 env.py 之前加载，实际生效的是 ini 中的配置；此处再设一次以兼容编程式调用。
config.set_main_option(
    "version_locations",
    " ".join(str(_MIGRATIONS_DIR / "versions" / part) for part in _VERSION_PARTS),
)


def _resolve_database_url() -> str:
    x_args = context.get_x_argument(as_dictionary=True)
    return (
        x_args.get("database_url")
        or os.environ.get("EDP_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or DEFAULT_DATABASE_URL
    )


config.set_main_option("sqlalchemy.url", _resolve_database_url())

target_metadata = None


def run_migrations_offline() -> None:
    """离线模式：alembic upgrade head --sql 仅生成脚本。"""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        dialect_opts={"paramstyle": "named"},
        literal_binds=True,
        include_schemas=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        include_schemas=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migration() -> None:
    """在线模式：异步引擎建立连接后经 run_sync 执行迁移。"""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migration())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
