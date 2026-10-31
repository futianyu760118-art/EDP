"""T1 集成测试：0013 迁移语义（quality 权限码 + ops.tasks 表/RLS/CHECK）。

覆盖：
1. 权限码 quality:read / quality:run 行存在（resource/action 正确）；
2. 角色矩阵精确：quality:read → PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST；
   quality:run → PLATFORM_ADMIN/ADMIN；
3. ops.tasks 表存在且 RLS 生效：default 租户造数后，绑定本租户的
   edp_app 会话可见 1 行，换绑其他租户上下文 0 行；
4. task_type / status CHECK 拒绝非法值（IntegrityError），合法三态/
   三类默认与显式值均可落库。

会话形态：db_session（edp_migrator 超级用户，绕 RLS）直查/造数；
RLS 用例走 app_role_engine（edp_app，FORCE RLS）+ bind_tenant
（同 test_w4_migration 的 RLS 直证模式）。
"""

from uuid import UUID, uuid4

import pytest
from edp_api.core.db import bind_tenant
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

pytestmark = [pytest.mark.integration]

NEW_PERMISSION_CODES = {"quality:read", "quality:run"}
EXPECTED_ROLES = {
    "quality:read": {"PLATFORM_ADMIN", "ADMIN", "MANAGER", "ANALYST"},
    "quality:run": {"PLATFORM_ADMIN", "ADMIN"},
}
TASK_TYPES = {"quality_recheck", "evidence_reindex", "adapter_sync"}
STATUSES = {"RUNNING", "SUCCEEDED", "FAILED"}


async def _default_tenant_id(db_session: AsyncSession) -> UUID:
    return (
        await db_session.execute(
            text("SELECT tenant_id FROM platform.tenants WHERE slug = 'default'")
        )
    ).scalar_one()


async def _insert_task(
    db_session: AsyncSession,
    tenant_id: UUID,
    task_type: str,
    status: str | None = None,
) -> None:
    # status=None 走列默认 'RUNNING'（显式 NULL 会撞 NOT NULL，非本测意图）
    if status is None:
        await db_session.execute(
            text("""
                INSERT INTO ops.tasks (task_id, tenant_id, task_type)
                VALUES (:tid, :tenant, :ttype)
            """),
            {"tid": uuid4(), "tenant": tenant_id, "ttype": task_type},
        )
    else:
        await db_session.execute(
            text("""
                INSERT INTO ops.tasks (task_id, tenant_id, task_type, status)
                VALUES (:tid, :tenant, :ttype, :status)
            """),
            {"tid": uuid4(), "tenant": tenant_id, "ttype": task_type, "status": status},
        )


async def test_permission_codes_and_role_matrix(db_session: AsyncSession) -> None:
    """quality:read / quality:run 行存在，角色矩阵精确。"""
    rows = (
        await db_session.execute(
            text("""
                SELECT p.code, p.resource, p.action, r.code AS role_code
                FROM platform.permissions p
                LEFT JOIN platform.role_permissions rp
                    ON rp.permission_id = p.permission_id
                LEFT JOIN platform.roles r ON r.role_id = rp.role_id
                WHERE p.code IN ('quality:read', 'quality:run')
            """)
        )
    ).mappings().all()
    by_code: dict[str, dict] = {}
    for row in rows:
        entry = by_code.setdefault(
            row["code"],
            {"resource": row["resource"], "action": row["action"], "roles": set()},
        )
        if row["role_code"] is not None:
            entry["roles"].add(row["role_code"])

    assert set(by_code) == NEW_PERMISSION_CODES
    for code, expected_roles in EXPECTED_ROLES.items():
        entry = by_code[code]
        assert entry["resource"] == "quality"
        assert entry["action"] == code.split(":", 1)[1]
        assert entry["roles"] == expected_roles


async def test_ops_tasks_table_exists(db_session: AsyncSession) -> None:
    """ops.tasks 建成，业务列 + 审计四件套齐备。"""
    cols = set(
        (
            await db_session.execute(
                text("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = 'ops' AND table_name = 'tasks'
                """)
            )
        ).scalars()
    )
    assert cols == {
        "task_id",
        "tenant_id",
        "task_type",
        "status",
        "scope",
        "ref_name",
        "stats",
        "logs",
        "started_at",
        "finished_at",
        "created_at",
        "created_by",
        "updated_at",
        "updated_by",
    }
    indexname = (
        await db_session.execute(
            text("""
                SELECT indexname FROM pg_catalog.pg_indexes
                WHERE schemaname = 'ops' AND tablename = 'tasks'
                  AND indexname = 'ix_tasks_tenant_type'
            """)
        )
    ).scalar_one_or_none()
    assert indexname == "ix_tasks_tenant_type"


async def test_ops_tasks_rls_isolates_tenants(
    db_session: AsyncSession, app_role_engine: AsyncEngine
) -> None:
    """RLS 生效：edp_app 绑本租户可见，换绑其他租户上下文 0 行。"""
    tenant_id = await _default_tenant_id(db_session)
    task_id = uuid4()
    await db_session.execute(
        text("""
            INSERT INTO ops.tasks (task_id, tenant_id, task_type)
            VALUES (:tid, :tenant, 'quality_recheck')
        """),
        {"tid": task_id, "tenant": tenant_id},
    )
    await db_session.commit()

    session = async_sessionmaker(app_role_engine)()
    try:
        await bind_tenant(session, tenant_id)
        visible_own = (
            await session.execute(
                text("SELECT count(*) FROM ops.tasks WHERE task_id = :tid"),
                {"tid": task_id},
            )
        ).scalar_one()
        assert visible_own == 1  # 正对照：本租户上下文可见造数行（按行定位，
        # 与全表存量解耦——其他测试文件的 adapter_sync 行不得影响本断言）

        await bind_tenant(session, uuid4())  # 任意其他租户上下文
        other = (
            await session.execute(text("SELECT count(*) FROM ops.tasks"))
        ).scalar_one()
        assert other == 0
    finally:
        await session.rollback()
        await session.close()
        await db_session.execute(
            text("DELETE FROM ops.tasks WHERE task_id = :tid"),
            {"tid": task_id},
        )
        await db_session.commit()


async def test_ops_tasks_check_constraints(db_session: AsyncSession) -> None:
    """task_type / status CHECK 拒绝非法值；三类型/三状态合法落库。"""
    tenant_id = await _default_tenant_id(db_session)

    # 非法 task_type / status → CheckViolation（SQLAlchemy 包为 IntegrityError）
    with pytest.raises(IntegrityError):
        await _insert_task(db_session, tenant_id, "not_a_task_type")
    await db_session.rollback()
    with pytest.raises(IntegrityError):
        await _insert_task(db_session, tenant_id, "quality_recheck", "PENDING")
    await db_session.rollback()

    # 合法三类型 × 默认/显式三状态均可落库
    for task_type in TASK_TYPES:
        await _insert_task(db_session, tenant_id, task_type)
    for status in STATUSES:
        await _insert_task(db_session, tenant_id, "adapter_sync", status)
    defaults = (
        await db_session.execute(
            text("""
                SELECT task_type, status, stats, logs, started_at, finished_at
                FROM ops.tasks WHERE tenant_id = :tenant AND status = 'RUNNING'
            """),
            {"tenant": tenant_id},
        )
    ).mappings().all()
    # 三条默认 RUNNING（status 未显式给值）+ 显式 RUNNING 一条 = 4 行，
    # 且 RUNNING 行覆盖全部三类 task_type
    assert len(defaults) == 4
    assert {row["task_type"] for row in defaults} == TASK_TYPES
    for row in defaults:
        assert row["stats"] == {}
        assert row["logs"] == []
        assert row["started_at"] is not None
        assert row["finished_at"] is None
    await db_session.rollback()  # 测试造数不落库（db_session 收尾亦回滚）
