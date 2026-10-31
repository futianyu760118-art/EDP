"""T10 集成测试：0008 迁移语义（审计月分区 / 仅追加强制 / 分区函数幂等）。

覆盖三条验收：
1. migrator 插入 audit 行（occurred_at=now()）成功且落入当月分区
   （tableoid::regclass = platform.audit_logs_YYYYmMM）；
2. edp_app（app_session）UPDATE / DELETE platform.audit_logs 均被拒——
   asyncpg InsufficientPrivilegeError（REVOKE 的仅追加强制）；
3. platform.ensure_audit_partitions() 重复调用幂等不炸，且当月起 3 个月分区在位。

会话形态：db_session（edp_migrator 超级用户）+ app_session（edp_app，
受 RLS 约束角色；audit_logs 为控制面不启用 RLS，权限检查即表级
GRANT/REVOKE）。SQLAlchemy 会把 DBAPI 异常包成 exc.OperationalError，
断言沿 __cause__ 链下钻到 asyncpg 原生异常。
"""

from datetime import UTC, datetime

import pytest
from asyncpg.exceptions import InsufficientPrivilegeError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.integration]

_ACTOR = "t10-w2-migration-probe"


def _root_cause(exc: BaseException) -> BaseException:
    """沿 __cause__ 链下钻取 DBAPI 原生异常。"""
    while exc.__cause__ is not None:
        exc = exc.__cause__
    return exc


async def test_audit_insert_lands_in_current_month_partition(db_session: AsyncSession) -> None:
    """migrator 插入 audit 行成功，且 tableoid 落在当月分区（0001 零分区时必失败）。"""
    occurred = datetime.now(UTC)
    await db_session.execute(
        text("""
            INSERT INTO platform.audit_logs
                (occurred_at, tenant_id, actor_type, actor_id, action, resource_type)
            VALUES
                (:occurred, NULL, 'SERVICE', :actor, 'TEST_W2_MIGRATION', 'test')
        """),
        {"occurred": occurred, "actor": _ACTOR},
    )
    table = (
        await db_session.execute(
            text("SELECT tableoid::regclass::text FROM platform.audit_logs WHERE actor_id = :a"),
            {"a": _ACTOR},
        )
    ).scalar()
    expected = f"platform.audit_logs_{occurred.year}m{occurred.month:02d}"
    assert table == expected


async def test_audit_update_delete_denied_for_app_role(app_session: AsyncSession) -> None:
    """edp_app UPDATE / DELETE audit_logs → InsufficientPrivilegeError（仅追加）。"""
    with pytest.raises(Exception) as ei:
        await app_session.execute(text("UPDATE platform.audit_logs SET action = 'HACK'"))
    assert isinstance(_root_cause(ei.value), InsufficientPrivilegeError)
    await app_session.rollback()  # 失败语句使事务进入 aborted 态，先回滚再试 DELETE

    with pytest.raises(Exception) as ei:
        await app_session.execute(text("DELETE FROM platform.audit_logs"))
    assert isinstance(_root_cause(ei.value), InsufficientPrivilegeError)


async def test_ensure_audit_partitions_idempotent(db_session: AsyncSession) -> None:
    """ensure_audit_partitions() 二次调用幂等不炸，且当月起 3 个月分区在位。"""
    await db_session.execute(text("SELECT platform.ensure_audit_partitions()"))
    await db_session.execute(text("SELECT platform.ensure_audit_partitions()"))

    count = (
        await db_session.execute(text("""
            SELECT count(*) FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'platform' AND c.relname LIKE 'audit_logs\\_2026m%'
        """))
    ).scalar_one()
    assert count >= 3
