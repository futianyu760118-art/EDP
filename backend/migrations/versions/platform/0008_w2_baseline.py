"""W2 基线：审计月分区 + 仅追加强制 + 适配器水位列 + adapters 权限码。

- audit_logs 0001 已 PARTITION BY RANGE (occurred_at) 但零分区——不建分区
  INSERT 必失败；本迁移预建 2026-09 起三个月分区 + ensure_audit_partitions()
  幂等函数（应用启动时调用，滚动创建未来月份）。
- REVOKE UPDATE/DELETE ON audit_logs FROM edp_app：仅追加语义在 DB 层强制
  （EDP-009 验收）。经父表路由的 INSERT/SELECT 只检查父表权限，分区自身
  无需授权（PG16 声明式分区行为，已实测验证）。
- platform.systems 已有 adapter_mode/auth_config（0001），仅补 last_watermark
  TIMESTAMPTZ（原 spec 写 config JSONB，已批偏差见 W2 计划 Architecture）。
- 权限码（uuid5 主键与 0005 同命名空间）：
  - adapters:read / adapters:write 为本迁移新增；
  - audit:read 已由 0005 种子（PERMISSIONS 含 audit:read，ADMIN/MANAGER/
    ANALYST/PLATFORM_ADMIN 均已覆盖角色矩阵）——此处仅按幂等守卫补齐声明，
    实际不产生新行；downgrade 只删 adapters 两码，不动 0005 的 audit:read。
  - 角色集以 0005 实际角色 code 为准（无 STEWARD，计划中的读权限位由
    ANALYST 承担）：adapters:read → PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST；
    adapters:write → PLATFORM_ADMIN/ADMIN/MANAGER；
    audit:read → PLATFORM_ADMIN/ADMIN/MANAGER。

Revision ID: 0008_w2_baseline
Revises: 0007_idem_tenant_pk
Create Date: 2026-09-16
"""

from collections.abc import Sequence
from uuid import UUID, uuid5

from alembic import op
from sqlalchemy import Uuid, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY

# uuid.NIL 于 Python 3.14 才加入标准库；3.12 用 UUID(int=0) 等价表达 nil UUID
NIL = UUID(int=0)

# revision identifiers, used by Alembic.
revision: str = "0008_w2_baseline"
down_revision: str | None = "0007_idem_tenant_pk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ---- 审计月分区：2026-09/10/11 三个月（四边界） ----

PARTITIONS = ("2026-09-01", "2026-10-01", "2026-11-01", "2026-12-01")
PARTITION_NAMES = tuple(
    f"audit_logs_{start[:7].replace('-', 'm')}" for start in PARTITIONS[:-1]
)

# ---- 权限码与角色矩阵（角色 code 与 role_id 种子命名均以 0005 为准） ----

NEW_PERMISSIONS: tuple[tuple[str, str, str], ...] = (
    ("adapters:read", "adapters", "read"),
    ("adapters:write", "adapters", "write"),
)

PERMISSION_ROLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("adapters:read", ("PLATFORM_ADMIN", "ADMIN", "MANAGER", "ANALYST")),
    ("adapters:write", ("PLATFORM_ADMIN", "ADMIN", "MANAGER")),
    # 0005 已覆盖（PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST 均有）→ 幂等守卫跳过
    ("audit:read", ("PLATFORM_ADMIN", "ADMIN", "MANAGER")),
)

PERMISSION_CODES = tuple(code for code, _, _ in NEW_PERMISSIONS) + ("audit:read",)
PERMISSION_IDS = {code: uuid5(NIL, f"edp-perm-{code}") for code in PERMISSION_CODES}
ROLE_IDS = {
    code: uuid5(NIL, f"edp-role-{code}")
    for code in ("PLATFORM_ADMIN", "ADMIN", "MANAGER", "ANALYST")
}


def _exists(conn, sql: str, params: dict | None = None) -> bool:
    """幂等守卫：查询命中即视为已存在（调用方跳过插入）。"""
    return conn.execute(text(sql), params or {}).scalar() is not None


def upgrade() -> None:
    # ---- 1. 预建三个月分区 ----
    for i in range(len(PARTITIONS) - 1):
        start, end = PARTITIONS[i], PARTITIONS[i + 1]
        name = PARTITION_NAMES[i]
        op.execute(f"""
            CREATE TABLE IF NOT EXISTS platform.{name}
            PARTITION OF platform.audit_logs
            FOR VALUES FROM ('{start}') TO ('{end}')
        """)

    # ---- 2. 滚动分区函数（应用启动时调用；当月起 3 个月 CREATE IF NOT EXISTS） ----
    op.execute("""
        CREATE OR REPLACE FUNCTION platform.ensure_audit_partitions()
        RETURNS void LANGUAGE plpgsql AS $$
        DECLARE
            d date := date_trunc('month', now())::date;
            p record;
        BEGIN
            FOR p IN
                SELECT generate_series(d, d + interval '2 months', interval '1 month') AS m
            LOOP
                EXECUTE format(
                    'CREATE TABLE IF NOT EXISTS platform.audit_logs_%s
                     PARTITION OF platform.audit_logs
                     FOR VALUES FROM (%L) TO (%L)',
                    to_char(p.m, 'YYYY"m"MM'), p.m, p.m + interval '1 month'
                );
            END LOOP;
        END $$;
    """)

    # ---- 3. 仅追加强制：edp_app 只可 SELECT/INSERT ----
    op.execute("REVOKE UPDATE, DELETE ON platform.audit_logs FROM edp_app")

    # ---- 4. 适配器水位列 ----
    op.execute(
        "ALTER TABLE platform.systems ADD COLUMN IF NOT EXISTS last_watermark TIMESTAMPTZ"
    )

    # ---- 5. 权限码 + 角色矩阵（幂等，风格同 0005） ----
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


def downgrade() -> None:
    """逆序全清：仅删本迁移新增行（audit:read 属 0005 种子，保留）。"""
    conn = op.get_bind()
    # 1. 删新增 role_permissions + permissions（adapters 两码的固定 UUID）
    _delete = text(
        "DELETE FROM platform.role_permissions WHERE permission_id = ANY(:ids)"
    ).bindparams(bindparam("ids", type_=ARRAY(Uuid)))
    conn.execute(_delete, {"ids": [PERMISSION_IDS[c] for c, _, _ in NEW_PERMISSIONS]})
    conn.execute(
        text("DELETE FROM platform.permissions WHERE permission_id = ANY(:ids)").bindparams(
            bindparam("ids", type_=ARRAY(Uuid))
        ),
        {"ids": [PERMISSION_IDS[c] for c, _, _ in NEW_PERMISSIONS]},
    )
    # 2. 水位列
    op.execute("ALTER TABLE platform.systems DROP COLUMN IF EXISTS last_watermark")
    # 3. 恢复 0001 尾部统一授权（audit_logs 当时授予全部四权）
    op.execute("GRANT UPDATE, DELETE ON platform.audit_logs TO edp_app")
    # 4. 分区函数
    op.execute("DROP FUNCTION IF EXISTS platform.ensure_audit_partitions()")
    # 5. 三个分区表
    for name in PARTITION_NAMES:
        op.execute(f"DROP TABLE IF EXISTS platform.{name}")
