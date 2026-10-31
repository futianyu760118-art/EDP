"""V1.2 经营结果层：metric schema（Registry + 计量值）+ value schema
（Value Ledger）+ 2 权限码。

- metric.metrics：口径定义注册表（V1.1 第十一节 + V1.2 第五节边界字段），
  UNIQUE(tenant_id, code)；版本化生效区间；
- metric.metric_values：计量值（UNIQUE(tenant, metric, period)）；
- value.value_ledger：改善前后价值事实（V1.1 第十三节）；
- 权限码：metric:read → PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST、
  metric:manage → PLATFORM_ADMIN/ADMIN（value ledger 复用 metric 轨道）。

Revision ID: 0016_v12_metric_value
Revises: 0015_v12_fact_layer
Create Date: 2026-10-10
"""

from collections.abc import Sequence
from uuid import UUID, uuid5

from alembic import op
from sqlalchemy import Uuid, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY

NIL = UUID(int=0)

revision: str = "0016_v12_metric_value"
down_revision: str | None = "0015_v12_fact_layer"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "tenant_isolation"
TENANT_QUAL = "(tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"

NEW_PERMISSIONS: tuple[tuple[str, str, str], ...] = (
    ("metric:read", "metric", "read"),
    ("metric:manage", "metric", "manage"),
)

PERMISSION_ROLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("metric:read", ("PLATFORM_ADMIN", "ADMIN", "MANAGER", "ANALYST")),
    ("metric:manage", ("PLATFORM_ADMIN", "ADMIN")),
)

PERMISSION_IDS = {code: uuid5(NIL, f"edp-perm-{code}") for code, _, _ in NEW_PERMISSIONS}
ROLE_IDS = {
    code: uuid5(NIL, f"edp-role-{code}")
    for code in ("PLATFORM_ADMIN", "ADMIN", "MANAGER", "ANALYST")
}


def _exists(conn, sql: str, params: dict | None = None) -> bool:
    return conn.execute(text(sql), params or {}).scalar() is not None


def _setup_schema(conn, schema: str, tables: tuple[tuple[str, str], ...]) -> None:
    """建 schema + 表 + RLS + 授权（幂等；口径同 0013/0014/0015）。"""
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    for table_name, ddl in tables:
        if not _exists(conn, f"SELECT to_regclass('{schema}.{table_name}')"):
            op.execute(ddl)
        op.execute(f"ALTER TABLE {schema}.{table_name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {schema}.{table_name} FORCE ROW LEVEL SECURITY")
        if not _exists(
            conn,
            """
            SELECT policyname FROM pg_catalog.pg_policies
            WHERE schemaname = :s AND tablename = :t
              AND policyname = 'tenant_isolation'
            """,
            {"s": schema, "t": table_name},
        ):
            op.execute(f"""
                CREATE POLICY {POLICY} ON {schema}.{table_name}
                USING {TENANT_QUAL} WITH CHECK {TENANT_QUAL}
            """)
    op.execute(f"GRANT USAGE ON SCHEMA {schema} TO edp_app")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema} TO edp_app"
    )


def upgrade() -> None:
    conn = op.get_bind()

    _setup_schema(
        conn,
        "metric",
        (
            (
                "metrics",
                """
                CREATE TABLE metric.metrics (
                    metric_id UUID PRIMARY KEY,
                    tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
                    code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    business_definition TEXT,
                    formula TEXT,
                    source TEXT,
                    owner TEXT NOT NULL,
                    definition_owner TEXT,
                    definition_source TEXT,
                    target_owner TEXT,
                    snapshot_policy TEXT,
                    period_rule TEXT,
                    dimension JSONB NOT NULL DEFAULT '[]',
                    unit TEXT,
                    version INTEGER NOT NULL DEFAULT 1,
                    effective_from TIMESTAMPTZ NOT NULL DEFAULT now(),
                    effective_to TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    created_by TEXT,
                    updated_by TEXT
                )
                """,
            ),
            (
                "metric_values",
                """
                CREATE TABLE metric.metric_values (
                    value_id UUID PRIMARY KEY,
                    tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
                    metric_id UUID NOT NULL REFERENCES metric.metrics(metric_id),
                    period TEXT NOT NULL,
                    value NUMERIC(18,4) NOT NULL,
                    source TEXT,
                    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    created_by TEXT,
                    updated_by TEXT,
                    UNIQUE (tenant_id, metric_id, period)
                )
                """,
            ),
        ),
    )
    if not _exists(
        conn,
        """
        SELECT indexname FROM pg_catalog.pg_indexes
        WHERE schemaname = 'metric' AND tablename = 'metric_values'
          AND indexname = 'ix_metric_values_tenant_metric'
        """,
    ):
        op.execute("""
            CREATE INDEX ix_metric_values_tenant_metric
                ON metric.metric_values (tenant_id, metric_id, period DESC)
        """)
    # 口径版本化：同 code 仅"生效中"（effective_to IS NULL）唯一——历史版本
    # 共存（版本化生效区间，V1.2 T23）
    if not _exists(
        conn,
        """
        SELECT indexname FROM pg_catalog.pg_indexes
        WHERE schemaname = 'metric' AND tablename = 'metrics'
          AND indexname = 'uq_metrics_active_code'
        """,
    ):
        op.execute("""
            CREATE UNIQUE INDEX uq_metrics_active_code
                ON metric.metrics (tenant_id, code) WHERE effective_to IS NULL
        """)

    _setup_schema(
        conn,
        "value",
        (
            (
                "value_ledger",
                """
                CREATE TABLE value.value_ledger (
                    value_id UUID PRIMARY KEY,
                    tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
                    baseline_ref TEXT,
                    initiative_ref TEXT,
                    metric_ref TEXT,
                    before_value NUMERIC(18,4),
                    after_value NUMERIC(18,4),
                    delta NUMERIC(18,4),
                    financial_value NUMERIC(18,4),
                    evidence_refs UUID[] NOT NULL DEFAULT '{}',
                    verified_by TEXT,
                    verified_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    created_by TEXT,
                    updated_by TEXT
                )
                """,
            ),
        ),
    )

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
    for schema, tables in (
        ("value", ("value_ledger",)),
        ("metric", ("metric_values", "metrics")),
    ):
        for table_name in tables:
            op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {schema}.{table_name}")
            op.execute(f"DROP TABLE IF EXISTS {schema}.{table_name}")
        op.execute(f"DROP SCHEMA IF EXISTS {schema}")
