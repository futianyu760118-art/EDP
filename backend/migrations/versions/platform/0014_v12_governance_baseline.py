"""V1.2 治理基线：governance schema 10 表 + RLS + 3 权限码。

- governance schema（V1.2 Phase 2 T08~T16 载体，spec 见
  docs/superpowers/specs/2026-10-10-edp-v12-governance-design.md §2）：
  raw_records（RAW 层，先留存后处理）/ clean_records（清洗留痕 fixAudit）/
  cleaning_rules（规则注册表）/ entity_aliases（实体解析别名）/
  dimensions / taxonomies / tags（多维分类三件套）/
  object_classifications（对象分类挂接）/ admission_records（A1–A4 状态机
  15 态）/ review_records（A2/A3 审核留痕）——全表 RLS tenant_isolation
  （app.tenant_id + NULLIF 空串守卫，同 0001/0003/0004/0012/0013）；
  幂等守卫同 0013（to_regclass / pg_indexes / pg_policies）。
- 权限码（uuid5 主键与 0005/0008/0010/0011/0012/0013 同命名空间）：
  - governance:read（governance, read）→ PLATFORM_ADMIN/ADMIN/MANAGER/ANALYST
  - governance:manage（governance, manage）→ PLATFORM_ADMIN/ADMIN
  - admission:review（admission, review）→ PLATFORM_ADMIN/ADMIN/MANAGER

Revision ID: 0014_v12_governance_baseline
Revises: 0013_w5_baseline
Create Date: 2026-10-10
"""

from collections.abc import Sequence
from uuid import UUID, uuid5

from alembic import op
from sqlalchemy import Uuid, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY

# uuid.NIL 于 Python 3.14 才加入标准库；3.12 用 UUID(int=0) 等价表达 nil UUID
NIL = UUID(int=0)

# revision identifiers, used by Alembic.
revision: str = "0014_v12_governance_baseline"
down_revision: str | None = "0013_w5_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "tenant_isolation"
TENANT_QUAL = "(tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"

SCHEMA = "governance"

# (表名, 建表 SQL) —— 全表 RLS + 审计四件套对齐既有口径
TABLES: tuple[tuple[str, str], ...] = (
    (
        "raw_records",
        """
        CREATE TABLE governance.raw_records (
            raw_record_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            source_system TEXT NOT NULL,
            source_record_id TEXT NOT NULL,
            object_type TEXT NOT NULL,
            source_timestamp TIMESTAMPTZ NOT NULL,
            raw_payload JSONB NOT NULL,
            received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            batch_id TEXT,
            checksum TEXT NOT NULL,
            schema_version TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, source_system, source_record_id, source_timestamp)
        )
        """,
    ),
    (
        "clean_records",
        """
        CREATE TABLE governance.clean_records (
            clean_record_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            object_id UUID NOT NULL REFERENCES master.business_objects(object_id),
            raw_record_id UUID REFERENCES governance.raw_records(raw_record_id),
            before JSONB NOT NULL,
            after JSONB NOT NULL,
            rule_refs JSONB NOT NULL DEFAULT '[]',
            executed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            confidence NUMERIC(5,4),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    ),
    (
        "cleaning_rules",
        """
        CREATE TABLE governance.cleaning_rules (
            rule_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            rule_name TEXT NOT NULL,
            object_type TEXT NOT NULL,
            field TEXT,
            rule_type TEXT NOT NULL CHECK (rule_type IN
                ('FORMAT','NORMALIZATION','DEDUPLICATION','MAPPING',
                 'RANGE_CHECK','REFERENTIAL_CHECK','BUSINESS_RULE',
                 'UNIT_CONVERSION','CURRENCY_NORMALIZATION','ENTITY_RESOLUTION')),
            condition TEXT,
            transformation JSONB NOT NULL DEFAULT '{}',
            severity TEXT NOT NULL CHECK (severity IN ('BLOCK','WARN','INFO')),
            owner TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            effective_from TIMESTAMPTZ NOT NULL DEFAULT now(),
            effective_to TIMESTAMPTZ,
            auto_fix BOOLEAN NOT NULL DEFAULT TRUE,
            review_required BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
        """,
    ),
    (
        "entity_aliases",
        """
        CREATE TABLE governance.entity_aliases (
            alias_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            object_type TEXT NOT NULL,
            alias TEXT NOT NULL,
            canonical_ref UUID REFERENCES master.business_objects(object_id),
            source TEXT NOT NULL CHECK (source IN
                ('RULE_BASED','HUMAN_MAINTAINED','AI_ASSISTED')),
            confidence NUMERIC(5,4),
            approved_by TEXT,
            approved_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT,
            UNIQUE (tenant_id, object_type, alias)
        )
        """,
    ),
    (
        "dimensions",
        """
        CREATE TABLE governance.dimensions (
            dimension_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT,
            UNIQUE (tenant_id, code)
        )
        """,
    ),
    (
        "taxonomies",
        """
        CREATE TABLE governance.taxonomies (
            taxonomy_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            dimension_id UUID NOT NULL REFERENCES governance.dimensions(dimension_id),
            parent_id UUID REFERENCES governance.taxonomies(taxonomy_id),
            label TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
        """,
    ),
    (
        "tags",
        """
        CREATE TABLE governance.tags (
            tag_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT,
            UNIQUE (tenant_id, code)
        )
        """,
    ),
    (
        "object_classifications",
        """
        CREATE TABLE governance.object_classifications (
            classification_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            object_id UUID NOT NULL REFERENCES master.business_objects(object_id),
            dimension_id UUID REFERENCES governance.dimensions(dimension_id),
            taxonomy_id UUID REFERENCES governance.taxonomies(taxonomy_id),
            label TEXT NOT NULL,
            source TEXT NOT NULL CHECK (source IN
                ('RULE_BASED','HUMAN_MAINTAINED','AI_ASSISTED')),
            rule_ref TEXT,
            confidence NUMERIC(5,4),
            version INTEGER NOT NULL DEFAULT 1,
            effective_from TIMESTAMPTZ NOT NULL DEFAULT now(),
            effective_to TIMESTAMPTZ,
            approved_by TEXT,
            approved_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
        """,
    ),
    (
        "admission_records",
        """
        CREATE TABLE governance.admission_records (
            admission_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            object_id UUID NOT NULL REFERENCES master.business_objects(object_id),
            state TEXT NOT NULL CHECK (state IN
                ('RECEIVED','PROFILED','CLEANED','STANDARDIZED','CLASSIFIED',
                 'SOURCE_REVIEW','SOURCE_APPROVED','MANAGEMENT_REVIEW',
                 'MANAGEMENT_APPROVED','OFFICIAL','ARCHIVED',
                 'RETURNED','REJECTED','SUSPENDED','ESCALATED')),
            review_result TEXT CHECK (review_result IN
                ('APPROVED','APPROVED_WITH_WARNING','RETURN_FOR_CORRECTION',
                 'REJECTED','SUSPENDED','ESCALATED')),
            quality_score NUMERIC(5,2),
            machine_result JSONB,
            source_human_reviewer TEXT,
            source_reviewed_at TIMESTAMPTZ,
            management_human_reviewer TEXT,
            management_reviewed_at TIMESTAMPTZ,
            archived_at TIMESTAMPTZ,
            raw_version TEXT,
            clean_version TEXT,
            standard_version TEXT,
            classification_version TEXT,
            dimensions JSONB,
            classifications JSONB,
            tags JSONB,
            evidence_refs UUID[] NOT NULL DEFAULT '{}',
            checksum TEXT,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT,
            UNIQUE (tenant_id, object_id)
        )
        """,
    ),
    (
        "review_records",
        """
        CREATE TABLE governance.review_records (
            review_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            admission_id UUID NOT NULL REFERENCES governance.admission_records(admission_id),
            stage TEXT NOT NULL CHECK (stage IN ('SOURCE_REVIEW','MANAGEMENT_REVIEW')),
            machine_result JSONB,
            human_decision TEXT NOT NULL CHECK (human_decision IN
                ('APPROVED','APPROVED_WITH_WARNING','RETURN_FOR_CORRECTION',
                 'REJECTED','SUSPENDED','ESCALATED')),
            human_reviewer TEXT NOT NULL,
            comment TEXT,
            reviewed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            evidence_refs UUID[] NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    ),
)

# 索引：(表名, 索引名, 建索引 SQL)
INDEXES: tuple[tuple[str, str, str], ...] = (
    (
        "raw_records",
        "ix_raw_records_tenant_type",
        "CREATE INDEX ix_raw_records_tenant_type"
        " ON governance.raw_records (tenant_id, object_type, received_at)",
    ),
    (
        "cleaning_rules",
        "ix_cleaning_rules_tenant_type",
        "CREATE INDEX ix_cleaning_rules_tenant_type"
        " ON governance.cleaning_rules (tenant_id, object_type, effective_from)",
    ),
    (
        "admission_records",
        "ix_admission_tenant_state",
        "CREATE INDEX ix_admission_tenant_state"
        " ON governance.admission_records (tenant_id, state, updated_at DESC)",
    ),
    (
        "review_records",
        "ix_reviews_admission",
        "CREATE INDEX ix_reviews_admission"
        " ON governance.review_records (admission_id, reviewed_at DESC)",
    ),
)

NEW_PERMISSIONS: tuple[tuple[str, str, str], ...] = (
    ("governance:read", "governance", "read"),
    ("governance:manage", "governance", "manage"),
    ("admission:review", "admission", "review"),
)

PERMISSION_ROLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("governance:read", ("PLATFORM_ADMIN", "ADMIN", "MANAGER", "ANALYST")),
    ("governance:manage", ("PLATFORM_ADMIN", "ADMIN")),
    ("admission:review", ("PLATFORM_ADMIN", "ADMIN", "MANAGER")),
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

    op.execute("CREATE SCHEMA IF NOT EXISTS governance")

    for table_name, ddl in TABLES:
        if not _exists(conn, f"SELECT to_regclass('{SCHEMA}.{table_name}')"):
            op.execute(ddl)
        op.execute(f"ALTER TABLE {SCHEMA}.{table_name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {SCHEMA}.{table_name} FORCE ROW LEVEL SECURITY")
        if not _exists(
            conn,
            """
            SELECT policyname FROM pg_catalog.pg_policies
            WHERE schemaname = :s AND tablename = :t
              AND policyname = 'tenant_isolation'
            """,
            {"s": SCHEMA, "t": table_name},
        ):
            op.execute(f"""
                CREATE POLICY {POLICY} ON {SCHEMA}.{table_name}
                USING {TENANT_QUAL} WITH CHECK {TENANT_QUAL}
            """)

    for table_name, index_name, ddl in INDEXES:
        if not _exists(
            conn,
            """
            SELECT indexname FROM pg_catalog.pg_indexes
            WHERE schemaname = :s AND tablename = :t AND indexname = :i
            """,
            {"s": SCHEMA, "t": table_name, "i": index_name},
        ):
            op.execute(ddl)

    op.execute("GRANT USAGE ON SCHEMA governance TO edp_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA governance TO edp_app"
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
    """逆序全清：role_permissions + permissions 删除 → RLS 策略 + 表（逆
    外键依赖序）→ schema governance。"""
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
    for table_name, _ in reversed(TABLES):
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {SCHEMA}.{table_name}")
        op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.{table_name}")
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
