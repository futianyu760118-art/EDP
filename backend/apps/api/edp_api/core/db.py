"""数据库会话与租户绑定基座（引擎惰性构造 + 请求级事务 + RLS 隔离键）。

协议（W1 认证链路，T10 落地）：
- ``get_db`` 是唯一的请求级会话来源：开 session → 存入 ``request.state.db`` →
  yield → 请求成功 commit / 异常 rollback → close，只负责事务生命周期。
- 认证依赖（T10 ``get_principal`` / ``tenant_scoped``）不自行开 session，而是从
  ``request.state.db`` 取同一个 session，在认证完成后调用 ``bind_tenant`` 写入
  事务级 ``app.tenant_id``（RLS 隔离键），业务代码经同一 session 访问受 RLS
  保护的表。业务路由统一 ``Depends(get_db)``，勿另建连接。
- ``bind_tenant`` 使用 ``set_config(..., is_local=true)``：绑定随事务结束
  （commit / rollback）自动失效，不会泄漏到连接池中被其他请求复用。
"""

from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from edp_api.core.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """惰性构造全局引擎（应用启动首次调用时创建），pool 10 + overflow 20。"""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            get_settings().database_url, pool_size=10, max_overflow=20
        )
    return _engine


def get_session_local() -> async_sessionmaker[AsyncSession]:
    """惰性构造全局会话工厂（SessionLocal），expire_on_commit=False。"""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def dispose_engine() -> None:
    """释放全局引擎（应用停机 / 测试收尾调用），下次 get_engine 重建。"""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def bind_tenant(sess: AsyncSession, tenant_id: UUID) -> None:
    """在当前事务内写入 RLS 隔离键 app.tenant_id（事务级，事务结束自动失效）。"""
    await sess.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
    )


async def current_tenant_setting(sess: AsyncSession) -> str | None:
    """读取当前会话/事务的 app.tenant_id（未绑定返回 None），用于 RLS 验证与测试。"""
    value: str | None = (
        await sess.execute(text("SELECT current_setting('app.tenant_id', true)"))
    ).scalar()
    return value or None


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：请求级事务生命周期（open → commit/rollback → close）。

    租户绑定发生在认证之后（见模块 docstring 协议），本依赖只负责事务边界；
    session 经 ``request.state.db`` 暴露给后续认证依赖共享。
    """
    session = get_session_local()()
    request.state.db = session
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
