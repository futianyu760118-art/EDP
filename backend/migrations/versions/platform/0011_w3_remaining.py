"""W3 补齐：trace/memory 权限码 + dev Key scopes。

- 权限码（uuid5 主键与 0005/0008/0010 同命名空间）：
  - trace:read（trace, read）→ PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST
    （对齐 decision:read 角色集；EDP-013 查询轨道）；
  - memory:read（memory, read）→ 同上（EDP-014 查询轨道）；
  - memory:review（memory, review）→ PLATFORM_ADMIN/ADMIN/MANAGER
    （Human-Only 评审轨道，EDP-014；ANALYST 不入矩阵）；
- dev API Key（0005 种子，sha256('edp-dev-agent-hub-key')）scopes 追加
  write:trace / write:memory（EDP-013/014 SERVICE 写入轨道，数组去重守卫）；
  EDP_DEV_API_KEY 环境变量存在时种子 Key 哈希不可知，跳过并告警
  （CI/本地用默认值）。
- 无新表/列：trace/memory/capacity 表 0004 已建；tenant_quotas /
  tenant_usage_daily 字段齐备（EDP-025 为应用层实现）。

Revision ID: 0011_w3_remaining
Revises: 0010_w3_baseline
Create Date: 2026-09-17
"""

import hashlib
import logging
import os
from collections.abc import Sequence
from uuid import UUID, uuid5

from alembic import op
from sqlalchemy import Uuid, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY

# uuid.NIL 于 Python 3.14 才加入标准库；3.12 用 UUID(int=0) 等价表达 nil UUID
NIL = UUID(int=0)

# revision identifiers, used by Alembic.
revision: str = "0011_w3_remaining"
down_revision: str | None = "0010_w3_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger(__name__)

# ---- 权限码与角色矩阵（角色 code / role_id 命名同 0005，uuid5 命名空间同 0005/0008/0010） ----

NEW_PERMISSIONS: tuple[tuple[str, str, str], ...] = (
    ("trace:read", "trace", "read"),
    ("memory:read", "memory", "read"),
    ("memory:review", "memory", "review"),
)

PERMISSION_ROLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("trace:read", ("PLATFORM_ADMIN", "ADMIN", "MANAGER", "ANALYST")),
    ("memory:read", ("PLATFORM_ADMIN", "ADMIN", "MANAGER", "ANALYST")),
    ("memory:review", ("PLATFORM_ADMIN", "ADMIN", "MANAGER")),
)

PERMISSION_IDS = {code: uuid5(NIL, f"edp-perm-{code}") for code, _, _ in NEW_PERMISSIONS}
ROLE_IDS = {
    code: uuid5(NIL, f"edp-role-{code}")
    for code in ("PLATFORM_ADMIN", "ADMIN", "MANAGER", "ANALYST")
}

DEV_KEY_SCOPES = ("write:trace", "write:memory")

DEFAULT_DEV_API_KEY = "edp-dev-agent-hub-key"


def _exists(conn, sql: str, params: dict | None = None) -> bool:
    """幂等守卫：查询命中即视为已存在（调用方跳过插入）。"""
    return conn.execute(text(sql), params or {}).scalar() is not None


def _dev_key_hash() -> str | None:
    """dev Key 的 sha256 哈希；EDP_DEV_API_KEY 存在时返回 None（跳过并告警）。"""
    if os.environ.get("EDP_DEV_API_KEY"):
        logger.warning(
            "EDP_DEV_API_KEY 已设置：0011 跳过 dev Key write:trace/write:memory "
            "scope 更新（种子 Key 哈希不可知，如需该 scope 请手工追加）"
        )
        return None
    return hashlib.sha256(DEFAULT_DEV_API_KEY.encode()).hexdigest()


def upgrade() -> None:
    # ---- 1. 权限码 + 角色矩阵（幂等，风格同 0005/0008/0010） ----
    conn = op.get_bind()
    for code, resource, action in NEW_PERMISSIONS:
        if _exists(
            conn,
            "SELECT permission_id FROM platform.permissions WHERE code = :code",
            {"code": code},
        ):
            continue
        conn.execute(
            text("""
                INSERT INTO platform.permissions (permission_id, code, resource, action)
                VALUES (:permission_id, :code, :resource, :action)
            """),
            {
                "permission_id": PERMISSION_IDS[code],
                "code": code,
                "resource": resource,
                "action": action,
            },
        )
    for perm_code, role_codes in PERMISSION_ROLES:
        for role_code in role_codes:
            if _exists(
                conn,
                """
                SELECT role_id FROM platform.role_permissions
                WHERE role_id = :r AND permission_id = :p
                """,
                {"r": ROLE_IDS[role_code], "p": PERMISSION_IDS[perm_code]},
            ):
                continue
            conn.execute(
                text("""
                    INSERT INTO platform.role_permissions (role_id, permission_id)
                    VALUES (:r, :p)
                """),
                {"r": ROLE_IDS[role_code], "p": PERMISSION_IDS[perm_code]},
            )

    # ---- 2. dev API Key scope 追加（幂等守卫：数组不含才追加） ----
    key_hash = _dev_key_hash()
    if key_hash is not None:
        for scope in DEV_KEY_SCOPES:
            conn.execute(
                text(f"""
                    UPDATE platform.api_keys
                    SET scopes = scopes || ARRAY['{scope}']
                    WHERE key_hash = :key_hash AND NOT ('{scope}' = ANY(scopes))
                """),
                {"key_hash": key_hash},
            )


def downgrade() -> None:
    """逆序全清：Key scope 剔除 → role_permissions + permissions 删除。"""
    conn = op.get_bind()
    # 1. 恢复 dev Key scopes（数组剔除；环境变量路径未改则无操作）
    key_hash = _dev_key_hash()
    if key_hash is not None:
        for scope in DEV_KEY_SCOPES:
            conn.execute(
                text(f"""
                    UPDATE platform.api_keys
                    SET scopes = array_remove(scopes, '{scope}')
                    WHERE key_hash = :key_hash AND '{scope}' = ANY(scopes)
                """),
                {"key_hash": key_hash},
            )
    # 2. 删新增 role_permissions + permissions（固定 UUID）
    _delete = text(
        "DELETE FROM platform.role_permissions WHERE permission_id = ANY(:ids)"
    ).bindparams(bindparam("ids", type_=ARRAY(Uuid)))
    conn.execute(_delete, {"ids": list(PERMISSION_IDS.values())})
    conn.execute(
        text("DELETE FROM platform.permissions WHERE permission_id = ANY(:ids)").bindparams(
            bindparam("ids", type_=ARRAY(Uuid))
        ),
        {"ids": list(PERMISSION_IDS.values())},
    )
