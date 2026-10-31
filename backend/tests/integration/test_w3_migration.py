"""T1 集成测试：0010 迁移语义（计量列 / 只读角色 / 权限码 / dev Key scope）。

覆盖：
1. 列存在：event.events.ingest_latency_ms（INTEGER 可空）、
   platform.tenant_usage_daily.events_duplicated（BIGINT NOT NULL DEFAULT 0）；
2. 权限码 tools:read / ebms:read 行存在（resource/action 正确）且角色矩阵各 4 行
   （PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST，对齐 decision:read 角色集）；
3. dev API Key（edp-dev-agent-hub-key）scopes 含 write:decision；
4. 只读角色直证：edp_agent_ro 为 NOLOGIN + 四 schema USAGE/SELECT + 非 INSERT，
   且 SET LOCAL ROLE 后 master.business_objects SELECT 成功、sales.orders INSERT
   抛 InsufficientPrivilege（Read-Only 三层之数据库层，EDP-015）。

会话形态：db_session（edp_migrator 超级用户）+ app_session（edp_app，已 GRANT
edp_agent_ro 成员）。SQLAlchemy 会把 DBAPI 异常包成 exc.OperationalError，断言沿
__cause__ 链下钻到 asyncpg 原生异常。
"""

import hashlib
import os

import pytest
from asyncpg.exceptions import InsufficientPrivilegeError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.integration]

DEV_KEY = "edp-dev-agent-hub-key"
RO_ROLE = "edp_agent_ro"
RO_ROLES = {"PLATFORM_ADMIN", "ADMIN", "MANAGER", "ANALYST"}
RO_SCHEMAS = ("master", "sales", "delivery", "rd")


def _root_cause(exc: BaseException) -> BaseException:
    """沿 __cause__ 链下钻取 DBAPI 原生异常。"""
    while exc.__cause__ is not None:
        exc = exc.__cause__
    return exc


async def test_measurement_columns_exist(db_session: AsyncSession) -> None:
    """两条计量列在位且类型/可空/默认值符合 0010 清单。"""
    rows = (
        await db_session.execute(
            text("""
                SELECT table_schema, table_name, column_name, data_type,
                       is_nullable, column_default
                FROM information_schema.columns
                WHERE (table_schema = 'event' AND table_name = 'events'
                       AND column_name = 'ingest_latency_ms')
                   OR (table_schema = 'platform' AND table_name = 'tenant_usage_daily'
                       AND column_name = 'events_duplicated')
            """)
        )
    ).mappings().all()
    cols = {(r["table_schema"], r["table_name"], r["column_name"]): r for r in rows}

    latency = cols[("event", "events", "ingest_latency_ms")]
    assert latency["data_type"] == "integer"
    assert latency["is_nullable"] == "YES"

    duplicated = cols[("platform", "tenant_usage_daily", "events_duplicated")]
    assert duplicated["data_type"] == "bigint"
    assert duplicated["is_nullable"] == "NO"
    assert (duplicated["column_default"] or "").startswith("0")


async def test_permission_codes_and_role_matrix(db_session: AsyncSession) -> None:
    """tools:read / ebms:read 行存在，角色矩阵恰为四角色（对齐 decision:read）。"""
    rows = (
        await db_session.execute(
            text("""
                SELECT p.code, p.resource, p.action, r.code AS role_code
                FROM platform.permissions p
                LEFT JOIN platform.role_permissions rp
                    ON rp.permission_id = p.permission_id
                LEFT JOIN platform.roles r ON r.role_id = rp.role_id
                WHERE p.code IN ('tools:read', 'ebms:read')
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

    assert set(by_code) == {"tools:read", "ebms:read"}
    for code, entry in by_code.items():
        assert entry["resource"] == code.split(":", 1)[0]
        assert entry["action"] == "read"
        assert entry["roles"] == RO_ROLES


async def test_dev_api_key_scope_contains_write_decision(db_session: AsyncSession) -> None:
    """种子 dev Key scopes 追加 write:decision（原三 scope 保留）。"""
    if os.environ.get("EDP_DEV_API_KEY"):
        pytest.skip("EDP_DEV_API_KEY 已设置：0010 按设计跳过 scope 更新")

    scopes = (
        await db_session.execute(
            text("SELECT scopes FROM platform.api_keys WHERE key_hash = :key_hash"),
            {"key_hash": hashlib.sha256(DEV_KEY.encode()).hexdigest()},
        )
    ).scalar_one_or_none()
    assert scopes is not None, "0005 种子 dev Key 行缺失"
    assert "write:decision" in scopes
    assert {"readonly", "write:event", "write:registry"} <= set(scopes)


async def test_agent_ro_role_grants_and_nologin(db_session: AsyncSession) -> None:
    """edp_agent_ro：NOLOGIN/非 BYPASSRLS、四 schema 可读、不可写、edp_app 是其成员。"""
    row = (
        await db_session.execute(
            text("SELECT rolcanlogin, rolbypassrls FROM pg_roles WHERE rolname = :r"),
            {"r": RO_ROLE},
        )
    ).one_or_none()
    assert row is not None, "edp_agent_ro 角色缺失"
    assert row.rolcanlogin is False
    assert row.rolbypassrls is False

    for schema in RO_SCHEMAS:
        usage = (
            await db_session.execute(
                text("SELECT has_schema_privilege(CAST(:r AS name), CAST(:s AS name), 'USAGE')"),
                {"r": RO_ROLE, "s": schema},
            )
        ).scalar_one()
        assert usage, f"{schema} schema USAGE 未授权"

    select_ok = (
        await db_session.execute(
            text(
                "SELECT has_table_privilege(CAST(:r AS name),"
                " 'master.business_objects', 'SELECT')"
            ),
            {"r": RO_ROLE},
        )
    ).scalar_one()
    assert select_ok

    insert_denied = (
        await db_session.execute(
            text(
                "SELECT has_table_privilege(CAST(:r AS name), 'sales.orders', 'INSERT')"
            ),
            {"r": RO_ROLE},
        )
    ).scalar_one()
    assert not insert_denied

    member = (
        await db_session.execute(
            text("SELECT pg_has_role(CAST('edp_app' AS name), CAST(:r AS name), 'MEMBER')"),
            {"r": RO_ROLE},
        )
    ).scalar_one()
    assert member


async def test_agent_ro_can_select_but_not_insert(app_session: AsyncSession) -> None:
    """SET LOCAL ROLE edp_agent_ro：领域表 SELECT 成功，INSERT 被拒（只读层直证）。"""
    await app_session.execute(text(f"SET LOCAL ROLE {RO_ROLE}"))
    count = (
        await app_session.execute(text("SELECT count(*) FROM master.business_objects"))
    ).scalar_one()
    assert count >= 0

    with pytest.raises(Exception) as ei:
        await app_session.execute(
            text("""
                INSERT INTO sales.orders
                    (order_id, tenant_id, order_no, status, snapshot_at)
                VALUES
                    (gen_random_uuid(), gen_random_uuid(), 'SO-RO-PROBE', 'NEW', now())
            """)
        )
    assert isinstance(_root_cause(ei.value), InsufficientPrivilegeError)
