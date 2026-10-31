"""T1 集成测试：0011 迁移语义（trace/memory 权限码 + dev Key scopes）。

覆盖：
1. 权限码 trace:read / memory:read / memory:review 行存在（resource/action 正确）；
2. 角色矩阵精确：trace:read、memory:read → PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST；
   memory:review → PLATFORM_ADMIN/ADMIN/MANAGER；
3. dev API Key（edp-dev-agent-hub-key）scopes 含 write:trace / write:memory，
   且既有 scopes（readonly/write:event/write:registry/write:decision）保留。

会话形态：db_session（edp_migrator 超级用户，绕 RLS）直查种子行。
"""

import hashlib
import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.integration]

DEV_KEY = "edp-dev-agent-hub-key"
NEW_PERMISSION_CODES = {"trace:read", "memory:read", "memory:review"}
EXPECTED_ROLES = {
    "trace:read": {"PLATFORM_ADMIN", "ADMIN", "MANAGER", "ANALYST"},
    "memory:read": {"PLATFORM_ADMIN", "ADMIN", "MANAGER", "ANALYST"},
    "memory:review": {"PLATFORM_ADMIN", "ADMIN", "MANAGER"},
}
EXISTING_SCOPES = {"readonly", "write:event", "write:registry", "write:decision"}


async def test_permission_codes_and_role_matrix(db_session: AsyncSession) -> None:
    """trace:read / memory:read / memory:review 行存在，角色矩阵精确。"""
    rows = (
        await db_session.execute(
            text("""
                SELECT p.code, p.resource, p.action, r.code AS role_code
                FROM platform.permissions p
                LEFT JOIN platform.role_permissions rp
                    ON rp.permission_id = p.permission_id
                LEFT JOIN platform.roles r ON r.role_id = rp.role_id
                WHERE p.code IN ('trace:read', 'memory:read', 'memory:review')
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
        resource, action = code.split(":", 1)
        assert entry["resource"] == resource
        assert entry["action"] == action
        assert entry["roles"] == expected_roles


async def test_dev_api_key_scopes_contain_trace_and_memory_writes(
    db_session: AsyncSession,
) -> None:
    """种子 dev Key scopes 追加 write:trace / write:memory（原 scopes 保留）。"""
    if os.environ.get("EDP_DEV_API_KEY"):
        pytest.skip("EDP_DEV_API_KEY 已设置：0011 按设计跳过 scope 更新")

    scopes = (
        await db_session.execute(
            text("SELECT scopes FROM platform.api_keys WHERE key_hash = :key_hash"),
            {"key_hash": hashlib.sha256(DEV_KEY.encode()).hexdigest()},
        )
    ).scalar_one_or_none()
    assert scopes is not None, "0005 种子 dev Key 行缺失"
    assert {"write:trace", "write:memory"} <= set(scopes)
    assert EXISTING_SCOPES <= set(scopes)
