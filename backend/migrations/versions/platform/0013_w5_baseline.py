"""W5 基线：ops.tasks 任务表 + quality 权限码。

- ops.tasks（EDP-W5 运维任务登记最小版）：异步运维任务（质量重跑 /
  证据重建索引 / 适配器同步）的执行档案——task_type 三值 CHECK +
  status 三态 CHECK（RUNNING/SUCCEEDED/FAILED）+ stats/logs JSONB
  （默认 '{}'/'[]'）+ started_at/finished_at 生命周期；审计字段四件套
  对齐 0004 既有表（TIMESTAMPTZ + TEXT）；RLS 沿 tenant_isolation 模式
  （app.tenant_id + NULLIF 空串守卫，同 0001/0003/0004/0012）；
  schema ops 由本迁移幂等创建（0001~0012 未登记该 schema）；
  (tenant_id, task_type, started_at DESC) 复合索引支撑任务列表按
  租户 + 类型近序查询。
- 权限码（uuid5 主键与 0005/0008/0010/0011/0012 同命名空间）：
  - quality:read（quality, read）→ PLATFORM_ADMIN/ADMIN/MANAGER/
    ANALYST（质量查询轨道，角色集对齐 trace:read 一类读码）；
  - quality:run（quality, run）→ PLATFORM_ADMIN/ADMIN（质量重跑
    管理轨道，MANAGER/ANALYST 不入矩阵）。

Revision ID: 0013_w5_baseline
Revises: 0012_w4_baseline
Create Date: 2026-09-20
"""

from collections.abc import Sequence
from uuid import UUID, uuid5

from alembic import op
from sqlalchemy import Uuid, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY

# uuid.NIL 于 Python 3.14 才加入标准库；3.12 用 UUID(int=0) 等价表达 nil UUID
NIL = UUID(int=0)

# revision identifiers, used by Alembic.
revision: str = "0013_w5_baseline"
down_revision: str | None = "0012_w4_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ---- ops.tasks / RLS（策略与限定词同 0001/0004/0012 的 tenant_isolation） ----

POLICY = "tenant_isolation"
# NULLIF 防御：事务级 set_config 提交/回滚后复位为空串（''::uuid 会抛错），
# 空串统一归一为 NULL → 隔离判空（0 行），未绑定请求不致 500
TENANT_QUAL = "(tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"

# ---- 权限码与角色矩阵（角色 code / role_id 命名同 0005，uuid5 命名空间同 0012） ----

NEW_PERMISSIONS: tuple[tuple[str, str, str], ...] = (
    ("quality:read", "quality", "read"),
    ("quality:run", "quality", "run"),
)

PERMISSION_ROLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("quality:read", ("PLATFORM_ADMIN", "ADMIN", "MANAGER", "ANALYST")),
    ("quality:run", ("PLATFORM_ADMIN", "ADMIN")),
)

PERMISSION_IDS = {code: uuid5(NIL, f"edp-perm-{code}") for code, _, _ in NEW_PERMISSIONS}
ROLE_IDS = {
    code: uuid5(NIL, f"edp-role-{code}")
    for code in ("PLATFORM_ADMIN", "ADMIN", "MANAGER", "ANALYST")
}


def _exists(conn, sql: str, params: dict | None = None) -> bool:
    """幂等守卫：查询命中即视为已存在（调用方跳过创建/插入）。"""
    return conn.execute(text(sql), params or {}).scalar() is not None


def upgrade() -> None:
    conn = op.get_bind()

    # ---- 1. ops.tasks 表 + 索引 + RLS（幂等守卫：to_regclass / pg_indexes / pg_policies） ----
    op.execute("CREATE SCHEMA IF NOT EXISTS ops")
    if not _exists(conn, "SELECT to_regclass('ops.tasks')"):
        op.execute("""
            CREATE TABLE ops.tasks (
                task_id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
                task_type TEXT NOT NULL CHECK (task_type IN
                    ('quality_recheck','evidence_reindex','adapter_sync')),
                status TEXT NOT NULL DEFAULT 'RUNNING'
                    CHECK (status IN ('RUNNING','SUCCEEDED','FAILED')),
                scope TEXT,
                ref_name TEXT,
                stats JSONB NOT NULL DEFAULT '{}',
                logs JSONB NOT NULL DEFAULT '[]',
                started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                finished_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                created_by TEXT,
                updated_by TEXT
            )
        """)
    if not _exists(
        conn,
        """
        SELECT indexname FROM pg_catalog.pg_indexes
        WHERE schemaname = 'ops' AND tablename = 'tasks'
          AND indexname = 'ix_tasks_tenant_type'
        """,
    ):
        op.execute("""
            CREATE INDEX ix_tasks_tenant_type
                ON ops.tasks (tenant_id, task_type, started_at DESC)
        """)
    op.execute("ALTER TABLE ops.tasks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ops.tasks FORCE ROW LEVEL SECURITY")
    if not _exists(
        conn,
        """
        SELECT policyname FROM pg_catalog.pg_policies
        WHERE schemaname = 'ops' AND tablename = 'tasks'
          AND policyname = 'tenant_isolation'
        """,
    ):
        op.execute(f"""
            CREATE POLICY {POLICY} ON ops.tasks
            USING {TENANT_QUAL} WITH CHECK {TENANT_QUAL}
        """)
    # 尾部授权（同 0004/0012 逐 schema 模式；GRANT 天然幂等）
    op.execute("GRANT USAGE ON SCHEMA ops TO edp_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ops TO edp_app"
    )

    # ---- 2. 权限码 + 角色矩阵（幂等，风格同 0005/0008/0010/0011/0012） ----
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
    """逆序全清：role_permissions + permissions 删除 → RLS 策略 →
    ops.tasks 表（索引随表）→ schema ops。"""
    conn = op.get_bind()
    # 1. 删新增 role_permissions + permissions（固定 UUID）
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
    # 2. RLS 策略 → 表 → schema（RESTRICT：ops schema 内仅本迁移对象，
    #    后续迁移若登记新对象，其 downgrade 先行清理后此处方可通过）
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ops.tasks")
    op.execute("DROP TABLE IF EXISTS ops.tasks")
    op.execute("DROP SCHEMA IF EXISTS ops")
