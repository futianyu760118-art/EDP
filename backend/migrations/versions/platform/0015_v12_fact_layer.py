"""V1.2 事实与结果层：result schema + result_refs 三表扩展 + 对象官方列 +
governance.lineage + 2 权限码。

- result.results（新 schema result，RLS + 授权 edp_app，spec Phase 3 §2）；
- decision.cases / action.actions / trace.traces 各加 result_refs UUID[]
  DEFAULT '{}'（evidence 经 links ref_type=RESULT，无列变更）；
- master.business_objects 加 layer_status（5 值 CHECK）/ official_version /
  lineage_id（OFFICIAL/ARCHIVED 转换回写，T19）；
- governance.lineage（契约 contracts/governance/lineage.schema.json 逐字段；
  governance schema 由 0014 建立，本迁移只加表 + RLS + 授权沿用）；
- 权限码：result:read → PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST、
  result:write → PLATFORM_ADMIN/ADMIN/MANAGER。

Revision ID: 0015_v12_fact_layer
Revises: 0014_v12_governance_baseline
Create Date: 2026-10-10
"""

from collections.abc import Sequence
from uuid import UUID, uuid5

from alembic import op
from sqlalchemy import Uuid, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY

NIL = UUID(int=0)

revision: str = "0015_v12_fact_layer"
down_revision: str | None = "0014_v12_governance_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "tenant_isolation"
TENANT_QUAL = "(tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"

NEW_PERMISSIONS: tuple[tuple[str, str, str], ...] = (
    ("result:read", "result", "read"),
    ("result:write", "result", "write"),
)

PERMISSION_ROLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("result:read", ("PLATFORM_ADMIN", "ADMIN", "MANAGER", "ANALYST")),
    ("result:write", ("PLATFORM_ADMIN", "ADMIN", "MANAGER")),
)

PERMISSION_IDS = {code: uuid5(NIL, f"edp-perm-{code}") for code, _, _ in NEW_PERMISSIONS}
ROLE_IDS = {
    code: uuid5(NIL, f"edp-role-{code}")
    for code in ("PLATFORM_ADMIN", "ADMIN", "MANAGER", "ANALYST")
}


def _exists(conn, sql: str, params: dict | None = None) -> bool:
    return conn.execute(text(sql), params or {}).scalar() is not None


def _column_exists(conn, schema: str, table: str, column: str) -> bool:
    return _exists(
        conn,
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = :s AND table_name = :t AND column_name = :c
        """,
        {"s": schema, "t": table, "c": column},
    )


def upgrade() -> None:
    conn = op.get_bind()

    # ---- 1. result schema + result.results + RLS + 授权 ----
    op.execute("CREATE SCHEMA IF NOT EXISTS result")
    if not _exists(conn, "SELECT to_regclass('result.results')"):
        op.execute("""
            CREATE TABLE result.results (
                result_id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
                result_type TEXT NOT NULL,
                object_id UUID NOT NULL REFERENCES master.business_objects(object_id),
                domain TEXT NOT NULL,
                period TEXT,
                metric_refs JSONB NOT NULL DEFAULT '[]',
                value JSONB NOT NULL DEFAULT '{}',
                status TEXT NOT NULL,
                source_refs JSONB NOT NULL DEFAULT '[]',
                evidence_refs UUID[] NOT NULL DEFAULT '{}',
                generated_by TEXT NOT NULL,
                generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                verified_status TEXT,
                verified_by TEXT,
                verified_at TIMESTAMPTZ,
                version INTEGER NOT NULL DEFAULT 1,
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
        WHERE schemaname = 'result' AND tablename = 'results'
          AND indexname = 'ix_results_tenant_type'
        """,
    ):
        op.execute("""
            CREATE INDEX ix_results_tenant_type
                ON result.results (tenant_id, result_type, generated_at DESC)
        """)
    op.execute("ALTER TABLE result.results ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE result.results FORCE ROW LEVEL SECURITY")
    if not _exists(
        conn,
        """
        SELECT policyname FROM pg_catalog.pg_policies
        WHERE schemaname = 'result' AND tablename = 'results'
          AND policyname = 'tenant_isolation'
        """,
    ):
        op.execute(f"""
            CREATE POLICY {POLICY} ON result.results
            USING {TENANT_QUAL} WITH CHECK {TENANT_QUAL}
        """)
    op.execute("GRANT USAGE ON SCHEMA result TO edp_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA result TO edp_app"
    )

    # ---- 2. result_refs 三表扩展（幂等：列存在即跳过） ----
    for schema, table in (("decision", "cases"), ("action", "actions"), ("trace", "traces")):
        if not _column_exists(conn, schema, table, "result_refs"):
            op.execute(
                f"ALTER TABLE {schema}.{table}"
                " ADD COLUMN result_refs UUID[] NOT NULL DEFAULT '{}'"
            )

    # ---- 3. business_objects 官方列（T19） ----
    if not _column_exists(conn, "master", "business_objects", "layer_status"):
        op.execute("""
            ALTER TABLE master.business_objects ADD COLUMN layer_status TEXT
                CHECK (layer_status IN ('RAW','CLEAN','STANDARD','CURATED','ARCHIVED'))
        """)
    if not _column_exists(conn, "master", "business_objects", "official_version"):
        op.execute("ALTER TABLE master.business_objects ADD COLUMN official_version TEXT")
    if not _column_exists(conn, "master", "business_objects", "lineage_id"):
        op.execute("ALTER TABLE master.business_objects ADD COLUMN lineage_id UUID")

    # ---- 4. governance.lineage（契约 lineage.schema.json 逐字段） ----
    if not _exists(conn, "SELECT to_regclass('governance.lineage')"):
        op.execute("""
            CREATE TABLE governance.lineage (
                lineage_id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
                source_record_id TEXT NOT NULL,
                transformation_id UUID,
                cleaning_rule_version TEXT,
                standardization_rule_version TEXT,
                classification_version TEXT,
                source_review_ref UUID,
                management_review_ref UUID,
                official_version TEXT NOT NULL,
                timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
                operator TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
    if not _exists(
        conn,
        """
        SELECT indexname FROM pg_catalog.pg_indexes
        WHERE schemaname = 'governance' AND tablename = 'lineage'
          AND indexname = 'ix_lineage_source_record'
        """,
    ):
        op.execute("""
            CREATE INDEX ix_lineage_source_record
                ON governance.lineage (tenant_id, source_record_id, timestamp DESC)
        """)
    op.execute("ALTER TABLE governance.lineage ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE governance.lineage FORCE ROW LEVEL SECURITY")
    if not _exists(
        conn,
        """
        SELECT policyname FROM pg_catalog.pg_policies
        WHERE schemaname = 'governance' AND tablename = 'lineage'
          AND policyname = 'tenant_isolation'
        """,
    ):
        op.execute(f"""
            CREATE POLICY {POLICY} ON governance.lineage
            USING {TENANT_QUAL} WITH CHECK {TENANT_QUAL}
        """)
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON governance.lineage TO edp_app"
    )

    # ---- 5. 权限码 + 角色矩阵（幂等，风格同 0013/0014） ----
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
    conn = op.get_bind()
    # 1. 权限码
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
    # 2. governance.lineage（表 + 索引随表）
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON governance.lineage")
    op.execute("DROP TABLE IF EXISTS governance.lineage")
    # 3. business_objects 三列（逆序）
    for column in ("lineage_id", "official_version", "layer_status"):
        if _column_exists(conn, "master", "business_objects", column):
            op.execute(f"ALTER TABLE master.business_objects DROP COLUMN {column}")
    # 4. result_refs 三表扩展
    for schema, table in (("trace", "traces"), ("action", "actions"), ("decision", "cases")):
        if _column_exists(conn, schema, table, "result_refs"):
            op.execute(f"ALTER TABLE {schema}.{table} DROP COLUMN result_refs")
    # 5. result schema
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON result.results")
    op.execute("DROP TABLE IF EXISTS result.results")
    op.execute("DROP SCHEMA IF EXISTS result")
