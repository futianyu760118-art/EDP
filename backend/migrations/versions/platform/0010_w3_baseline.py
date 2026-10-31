"""W3 基线：计量列 + 只读角色 + 权限码 + dev Key scope。

- event.events 加列 ingest_latency_ms INTEGER（可空）：入库处理耗时，
  管道/events-batch 实测写入、seed 用确定性值回填（EDP-019/EDP-301）；
- platform.tenant_usage_daily 加列 events_duplicated BIGINT NOT NULL DEFAULT 0：
  幂等命中计数，events/batch 与管道两条入库路径 upsert 累加；
- 只读角色 edp_agent_ro（NOLOGIN）：master/sales/delivery/rd 四 schema
  USAGE + SELECT（覆盖 tools 六接口域），并 GRANT 给 edp_app——tools 查询
  事务内 SET LOCAL ROLE 收紧（Read-Only 三层之数据库层，EDP-015）；
- 权限码 tools:read / ebms:read（uuid5 主键与 0005/0008 同命名空间）：
  角色矩阵 = PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST（对齐 decision:read 角色集）；
- dev API Key（0005 种子，sha256('edp-dev-agent-hub-key')）scopes 追加
  write:decision（EDP-018 案例创建 SERVICE 轨道）；EDP_DEV_API_KEY 环境变量
  存在时种子 Key 哈希不可知，跳过并告警（CI/本地用默认值）。

Revision ID: 0010_w3_baseline
Revises: 0009_audit_fn_security
Create Date: 2026-09-16
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
revision: str = "0010_w3_baseline"
down_revision: str | None = "0009_audit_fn_security"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger(__name__)

# ---- 只读角色（Read-Only 三层之数据库层；role 生命周期归本迁移管理） ----

RO_ROLE = "edp_agent_ro"
RO_SCHEMAS = ("master", "sales", "delivery", "rd")

# ---- 权限码与角色矩阵（角色 code / role_id 命名同 0005，uuid5 命名空间同 0005/0008） ----

NEW_PERMISSIONS: tuple[tuple[str, str, str], ...] = (
    ("tools:read", "tools", "read"),
    ("ebms:read", "ebms", "read"),
)

PERMISSION_ROLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("tools:read", ("PLATFORM_ADMIN", "ADMIN", "MANAGER", "ANALYST")),
    ("ebms:read", ("PLATFORM_ADMIN", "ADMIN", "MANAGER", "ANALYST")),
)

PERMISSION_IDS = {code: uuid5(NIL, f"edp-perm-{code}") for code, _, _ in NEW_PERMISSIONS}
ROLE_IDS = {
    code: uuid5(NIL, f"edp-role-{code}")
    for code in ("PLATFORM_ADMIN", "ADMIN", "MANAGER", "ANALYST")
}

DEFAULT_DEV_API_KEY = "edp-dev-agent-hub-key"


def _exists(conn, sql: str, params: dict | None = None) -> bool:
    """幂等守卫：查询命中即视为已存在（调用方跳过插入）。"""
    return conn.execute(text(sql), params or {}).scalar() is not None


def _dev_key_hash() -> str | None:
    """dev Key 的 sha256 哈希；EDP_DEV_API_KEY 存在时返回 None（跳过并告警）。"""
    if os.environ.get("EDP_DEV_API_KEY"):
        logger.warning(
            "EDP_DEV_API_KEY 已设置：0010 跳过 dev Key write:decision scope 更新"
            "（种子 Key 哈希不可知，如需该 scope 请手工追加）"
        )
        return None
    return hashlib.sha256(DEFAULT_DEV_API_KEY.encode()).hexdigest()


def upgrade() -> None:
    # ---- 1. 计量列 ----
    op.execute("ALTER TABLE event.events ADD COLUMN IF NOT EXISTS ingest_latency_ms INTEGER")
    op.execute(
        "ALTER TABLE platform.tenant_usage_daily"
        " ADD COLUMN IF NOT EXISTS events_duplicated BIGINT NOT NULL DEFAULT 0"
    )

    # ---- 2. 只读角色 + 四 schema 授权（幂等守卫 pg_roles；GRANT 天然幂等） ----
    op.execute(f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{RO_ROLE}') THEN
                CREATE ROLE {RO_ROLE} NOLOGIN;
            END IF;
        END $$
    """)
    schemas = ", ".join(RO_SCHEMAS)
    op.execute(f"GRANT USAGE ON SCHEMA {schemas} TO {RO_ROLE}")
    op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA {schemas} TO {RO_ROLE}")
    op.execute(f"GRANT {RO_ROLE} TO edp_app")

    # ---- 3. 权限码 + 角色矩阵（幂等，风格同 0005/0008） ----
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

    # ---- 4. dev API Key scope 追加（幂等守卫：数组不含才追加） ----
    key_hash = _dev_key_hash()
    if key_hash is not None:
        conn.execute(
            text("""
                UPDATE platform.api_keys
                SET scopes = scopes || ARRAY['write:decision']
                WHERE key_hash = :key_hash AND NOT ('write:decision' = ANY(scopes))
            """),
            {"key_hash": key_hash},
        )


def downgrade() -> None:
    """逆序全清：Key scope → 权限码 → 只读角色 → 两列。"""
    conn = op.get_bind()
    # 1. 恢复 dev Key scopes（数组剔除；环境变量路径未改则无操作）
    key_hash = _dev_key_hash()
    if key_hash is not None:
        conn.execute(
            text("""
                UPDATE platform.api_keys
                SET scopes = array_remove(scopes, 'write:decision')
                WHERE key_hash = :key_hash AND 'write:decision' = ANY(scopes)
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
    # 3. 只读角色：先摘成员与对象权限（DROP ROLE 的依赖），再删角色
    op.execute(f"REVOKE {RO_ROLE} FROM edp_app")
    schemas = ", ".join(RO_SCHEMAS)
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA {schemas} FROM {RO_ROLE}")
    op.execute(f"REVOKE ALL ON SCHEMA {schemas} FROM {RO_ROLE}")
    op.execute(f"DROP ROLE IF EXISTS {RO_ROLE}")
    # 4. 两列（逆序：后加的先删）
    op.execute(
        "ALTER TABLE platform.tenant_usage_daily DROP COLUMN IF EXISTS events_duplicated"
    )
    op.execute("ALTER TABLE event.events DROP COLUMN IF EXISTS ingest_latency_ms")
