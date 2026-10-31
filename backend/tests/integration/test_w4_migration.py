"""T1 集成测试：0012 迁移语义（audit:policy 权限码 + dev Key scope +
audit.policies 表/RLS + cases 唯一索引 W3-23）。

覆盖：
1. 权限码 audit:policy_read / audit:policy_write 行存在（resource/action 正确）；
2. 角色矩阵精确：audit:policy_read → PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST；
   audit:policy_write → PLATFORM_ADMIN/ADMIN；
3. dev API Key（edp-dev-agent-hub-key）scopes 含 write:action，
   且既有 scopes（readonly/write:event/write:registry/write:decision/
   write:trace/write:memory）保留；
4. audit.policies 表存在且 RLS 生效：default 租户造数后，绑定本租户的
   edp_app 会话可见 1 行，换绑其他租户上下文 0 行；
5. uq_cases_tenant_source 存在：同 (tenant_id, source_id) 第二行插入抛
   IntegrityError（source_id IS NOT NULL 场景）；source_id 为 NULL 的
   两行不冲突（部分索引不含 NULL 行）。

会话形态：db_session（edp_migrator 超级用户，绕 RLS）直查/造数；
RLS 用例走 app_role_engine（edp_app，FORCE RLS）+ bind_tenant
（同 test_db_binding / test_pipeline 的 RLS 直证模式）。
"""

import hashlib
import os
from uuid import UUID, uuid4

import pytest
from edp_api.core.db import bind_tenant
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

pytestmark = [pytest.mark.integration]

DEV_KEY = "edp-dev-agent-hub-key"
NEW_PERMISSION_CODES = {"audit:policy_read", "audit:policy_write"}
EXPECTED_ROLES = {
    "audit:policy_read": {"PLATFORM_ADMIN", "ADMIN", "MANAGER", "ANALYST"},
    "audit:policy_write": {"PLATFORM_ADMIN", "ADMIN"},
}
EXISTING_SCOPES = {
    "readonly",
    "write:event",
    "write:registry",
    "write:decision",
    "write:trace",
    "write:memory",
}


async def _default_tenant_id(db_session: AsyncSession) -> UUID:
    return (
        await db_session.execute(
            text("SELECT tenant_id FROM platform.tenants WHERE slug = 'default'")
        )
    ).scalar_one()


async def _insert_case(
    db_session: AsyncSession, tenant_id: UUID, case_no: str, source_id: str | None
) -> None:
    await db_session.execute(
        text("""
            INSERT INTO decision.cases
                (case_id, tenant_id, case_no, question, source_type, source_id)
            VALUES (:cid, :tid, :cno, 'w4 uq probe', 'event', :src)
        """),
        {"cid": uuid4(), "tid": tenant_id, "cno": case_no, "src": source_id},
    )


async def test_permission_codes_and_role_matrix(db_session: AsyncSession) -> None:
    """audit:policy_read / audit:policy_write 行存在，角色矩阵精确。"""
    rows = (
        await db_session.execute(
            text("""
                SELECT p.code, p.resource, p.action, r.code AS role_code
                FROM platform.permissions p
                LEFT JOIN platform.role_permissions rp
                    ON rp.permission_id = p.permission_id
                LEFT JOIN platform.roles r ON r.role_id = rp.role_id
                WHERE p.code IN ('audit:policy_read', 'audit:policy_write')
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
        assert entry["resource"] == "audit"
        assert entry["action"] == code.split(":", 1)[1]
        assert entry["roles"] == expected_roles


async def test_dev_api_key_scopes_contain_write_action(
    db_session: AsyncSession,
) -> None:
    """种子 dev Key scopes 追加 write:action（原 scopes 保留）。"""
    if os.environ.get("EDP_DEV_API_KEY"):
        pytest.skip("EDP_DEV_API_KEY 已设置：0012 按设计跳过 scope 更新")

    scopes = (
        await db_session.execute(
            text("SELECT scopes FROM platform.api_keys WHERE key_hash = :key_hash"),
            {"key_hash": hashlib.sha256(DEV_KEY.encode()).hexdigest()},
        )
    ).scalar_one_or_none()
    assert scopes is not None, "0005 种子 dev Key 行缺失"
    assert "write:action" in set(scopes)
    assert EXISTING_SCOPES <= set(scopes)


async def test_audit_policies_table_exists(db_session: AsyncSession) -> None:
    """audit.policies 建成，业务列 + 审计四件套齐备。"""
    cols = set(
        (
            await db_session.execute(
                text("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = 'audit' AND table_name = 'policies'
                """)
            )
        ).scalars()
    )
    assert cols == {
        "policy_id",
        "tenant_id",
        "name",
        "description",
        "resource_types",
        "actions",
        "actor_types",
        "notify_channel",
        "status",
        "created_at",
        "created_by",
        "updated_at",
        "updated_by",
    }


async def test_audit_policies_rls_isolates_tenants(
    db_session: AsyncSession, app_role_engine: AsyncEngine
) -> None:
    """RLS 生效：edp_app 绑本租户可见，换绑其他租户上下文 0 行。"""
    tenant_id = await _default_tenant_id(db_session)
    policy_id = uuid4()
    await db_session.execute(
        text("""
            INSERT INTO audit.policies (policy_id, tenant_id, name)
            VALUES (:pid, :tid, 'w4-rls-probe')
        """),
        {"pid": policy_id, "tid": tenant_id},
    )
    await db_session.commit()

    session = async_sessionmaker(app_role_engine)()
    try:
        await bind_tenant(session, tenant_id)
        own = (
            await session.execute(text("SELECT count(*) FROM audit.policies"))
        ).scalar_one()
        assert own == 1  # 正对照：绑定本租户可见造数行

        await bind_tenant(session, uuid4())  # 任意其他租户上下文
        other = (
            await session.execute(text("SELECT count(*) FROM audit.policies"))
        ).scalar_one()
        assert other == 0
    finally:
        await session.rollback()
        await session.close()
        await db_session.execute(
            text("DELETE FROM audit.policies WHERE policy_id = :pid"),
            {"pid": policy_id},
        )
        await db_session.commit()


async def test_uq_cases_tenant_source(db_session: AsyncSession) -> None:
    """W3-23：同 (tenant_id, source_id) 第二行 IntegrityError；NULL 不冲突。"""
    indexname = (
        await db_session.execute(
            text("""
                SELECT indexname FROM pg_catalog.pg_indexes
                WHERE schemaname = 'decision' AND tablename = 'cases'
                  AND indexname = 'uq_cases_tenant_source'
            """)
        )
    ).scalar_one_or_none()
    assert indexname == "uq_cases_tenant_source"

    tenant_id = await _default_tenant_id(db_session)
    # source_id IS NOT NULL：同 (tenant_id, source_id) 第二行撞部分唯一索引
    await _insert_case(db_session, tenant_id, "W4-UQ-001", "w4-src-001")
    with pytest.raises(IntegrityError):
        await _insert_case(db_session, tenant_id, "W4-UQ-002", "w4-src-001")
    await db_session.rollback()  # 撞索引后事务中止，回滚再验 NULL 场景

    # source_id 为 NULL 的两行不冲突（部分索引 WHERE source_id IS NOT NULL）
    await _insert_case(db_session, tenant_id, "W4-UQ-003", None)
    await _insert_case(db_session, tenant_id, "W4-UQ-004", None)
    await db_session.rollback()  # 测试造数不落库（db_session 收尾亦回滚）
