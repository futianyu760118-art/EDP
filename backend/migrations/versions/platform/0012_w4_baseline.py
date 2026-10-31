"""W4 基线：audit.policies 表 + cases 唯一索引（W3-23）+ audit:policy 权限码。

- audit.policies（EDP-032 审计策略最小版）：三维匹配数组（resource_types /
  actions / actor_types，空数组=通配）+ notify_channel + 启停 status +
  租户内重名唯一（uq_audit_policy_name）；审计字段四件套对齐 0004 既有表
  （TIMESTAMPTZ + TEXT）；RLS 沿 tenant_isolation 模式（app.tenant_id +
  NULLIF 空串守卫，同 0001/0003/0004）；schema audit 由本迁移幂等创建
  （0001~0011 未登记该 schema）。
- W3-23：decision.cases (tenant_id, source_id) 部分唯一索引
  （WHERE source_id IS NOT NULL）——source 事件 → 案例 1:1 捕获的 DB 兜底
  （与 ebms exceptions 标量子查询互为双保险）。
- 权限码（uuid5 主键与 0005/0008/0010/0011 同命名空间）：
  - audit:policy_read（audit, policy_read）→ PLATFORM_ADMIN/ADMIN/MANAGER/
    ANALYST（策略查询轨道，角色集对齐 trace:read 一类读码）；
  - audit:policy_write（audit, policy_write）→ PLATFORM_ADMIN/ADMIN
    （策略管理轨道，MANAGER/ANALYST 不入矩阵）。
- dev API Key（0005 种子，sha256('edp-dev-agent-hub-key')）scopes 追加
  write:action（EDP-020 Action SERVICE 写入轨道，resource 名 action 与
  make_require_access 双轨一致，数组去重守卫）；EDP_DEV_API_KEY 环境变量
  存在时种子 Key 哈希不可知，跳过并告警（CI/本地用默认值）。

Revision ID: 0012_w4_baseline
Revises: 0011_w3_remaining
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
revision: str = "0012_w4_baseline"
down_revision: str | None = "0011_w3_remaining"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger(__name__)

# ---- audit.policies / RLS（策略与限定词同 0001/0004 的 tenant_isolation） ----

POLICY = "tenant_isolation"
# NULLIF 防御：事务级 set_config 提交/回滚后复位为空串（''::uuid 会抛错），
# 空串统一归一为 NULL → 隔离判空（0 行），未绑定请求不致 500
TENANT_QUAL = "(tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"

# ---- 权限码与角色矩阵（角色 code / role_id 命名同 0005，uuid5 命名空间同 0011） ----

NEW_PERMISSIONS: tuple[tuple[str, str, str], ...] = (
    ("audit:policy_read", "audit", "policy_read"),
    ("audit:policy_write", "audit", "policy_write"),
)

PERMISSION_ROLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("audit:policy_read", ("PLATFORM_ADMIN", "ADMIN", "MANAGER", "ANALYST")),
    ("audit:policy_write", ("PLATFORM_ADMIN", "ADMIN")),
)

PERMISSION_IDS = {code: uuid5(NIL, f"edp-perm-{code}") for code, _, _ in NEW_PERMISSIONS}
ROLE_IDS = {
    code: uuid5(NIL, f"edp-role-{code}")
    for code in ("PLATFORM_ADMIN", "ADMIN", "MANAGER", "ANALYST")
}

DEV_KEY_SCOPES = ("write:action",)

DEFAULT_DEV_API_KEY = "edp-dev-agent-hub-key"


def _exists(conn, sql: str, params: dict | None = None) -> bool:
    """幂等守卫：查询命中即视为已存在（调用方跳过创建/插入）。"""
    return conn.execute(text(sql), params or {}).scalar() is not None


def _dev_key_hash() -> str | None:
    """dev Key 的 sha256 哈希；EDP_DEV_API_KEY 存在时返回 None（跳过并告警）。"""
    if os.environ.get("EDP_DEV_API_KEY"):
        logger.warning(
            "EDP_DEV_API_KEY 已设置：0012 跳过 dev Key write:action scope 更新"
            "（种子 Key 哈希不可知，如需该 scope 请手工追加）"
        )
        return None
    return hashlib.sha256(DEFAULT_DEV_API_KEY.encode()).hexdigest()


def upgrade() -> None:
    conn = op.get_bind()

    # ---- 1. audit.policies 表 + RLS（幂等守卫：to_regclass / pg_policies） ----
    op.execute("CREATE SCHEMA IF NOT EXISTS audit")
    if not _exists(conn, "SELECT to_regclass('audit.policies')"):
        op.execute("""
            CREATE TABLE audit.policies (
                policy_id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
                name TEXT NOT NULL,
                description TEXT,
                resource_types TEXT[] NOT NULL DEFAULT '{}',
                actions TEXT[] NOT NULL DEFAULT '{}',
                actor_types TEXT[] NOT NULL DEFAULT '{}',
                notify_channel TEXT,
                status TEXT NOT NULL DEFAULT 'ACTIVE'
                    CHECK (status IN ('ACTIVE','DISABLED')),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                created_by TEXT,
                updated_by TEXT,
                CONSTRAINT uq_audit_policy_name UNIQUE (tenant_id, name)
            )
        """)
    op.execute("ALTER TABLE audit.policies ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit.policies FORCE ROW LEVEL SECURITY")
    if not _exists(
        conn,
        """
        SELECT policyname FROM pg_catalog.pg_policies
        WHERE schemaname = 'audit' AND tablename = 'policies'
          AND policyname = 'tenant_isolation'
        """,
    ):
        op.execute(f"""
            CREATE POLICY {POLICY} ON audit.policies
            USING {TENANT_QUAL} WITH CHECK {TENANT_QUAL}
        """)
    # 尾部授权（同 0004 逐 schema 模式；GRANT 天然幂等）
    op.execute("GRANT USAGE ON SCHEMA audit TO edp_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA audit TO edp_app"
    )

    # ---- 2. W3-23：cases (tenant_id, source_id) 部分唯一索引（_exists 查 pg_indexes） ----
    if not _exists(
        conn,
        """
        SELECT indexname FROM pg_catalog.pg_indexes
        WHERE schemaname = 'decision' AND tablename = 'cases'
          AND indexname = 'uq_cases_tenant_source'
        """,
    ):
        op.execute("""
            CREATE UNIQUE INDEX uq_cases_tenant_source
                ON decision.cases(tenant_id, source_id)
                WHERE source_id IS NOT NULL
        """)

    # ---- 3. 权限码 + 角色矩阵（幂等，风格同 0005/0008/0010/0011） ----
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
    """逆序全清：Key scope 剔除 → role_permissions + permissions 删除 →
    唯一索引 → RLS 策略 + audit.policies 表 + schema audit。"""
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
    # 3. W3-23 唯一索引
    op.execute("DROP INDEX IF EXISTS decision.uq_cases_tenant_source")
    # 4. RLS 策略 → 表 → schema（RESTRICT：audit schema 内仅本迁移对象，
    #    后续迁移若登记新对象，其 downgrade 先行清理后此处方可通过）
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON audit.policies")
    op.execute("DROP TABLE IF EXISTS audit.policies")
    op.execute("DROP SCHEMA IF EXISTS audit")
