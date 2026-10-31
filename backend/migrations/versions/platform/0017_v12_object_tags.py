"""V1.2 标签挂接：governance.object_tags（search_objects 多维查询 T33 前置）。

object_id FK business_objects、tag_id FK governance.tags（0014 建）；
UNIQUE(tenant_id, object_id, tag_id) + RLS + 授权（口径同 0014/0015/0016）。

Revision ID: 0017_v12_object_tags
Revises: 0016_v12_metric_value
Create Date: 2026-10-10
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0017_v12_object_tags"
down_revision: str | None = "0016_v12_metric_value"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "tenant_isolation"
TENANT_QUAL = "(tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"


def _exists(conn, sql: str, params: dict | None = None) -> bool:
    return conn.execute(text(sql), params or {}).scalar() is not None


def upgrade() -> None:
    conn = op.get_bind()
    if not _exists(conn, "SELECT to_regclass('governance.object_tags')"):
        op.execute("""
            CREATE TABLE governance.object_tags (
                object_tag_id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
                object_id UUID NOT NULL REFERENCES master.business_objects(object_id),
                tag_id UUID NOT NULL REFERENCES governance.tags(tag_id),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                created_by TEXT,
                UNIQUE (tenant_id, object_id, tag_id)
            )
        """)
    if not _exists(
        conn,
        """
        SELECT indexname FROM pg_catalog.pg_indexes
        WHERE schemaname = 'governance' AND tablename = 'object_tags'
          AND indexname = 'ix_object_tags_tag'
        """,
    ):
        op.execute("""
            CREATE INDEX ix_object_tags_tag
                ON governance.object_tags (tenant_id, tag_id)
        """)
    op.execute("ALTER TABLE governance.object_tags ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE governance.object_tags FORCE ROW LEVEL SECURITY")
    if not _exists(
        conn,
        """
        SELECT policyname FROM pg_catalog.pg_policies
        WHERE schemaname = 'governance' AND tablename = 'object_tags'
          AND policyname = 'tenant_isolation'
        """,
    ):
        op.execute(f"""
            CREATE POLICY {POLICY} ON governance.object_tags
            USING {TENANT_QUAL} WITH CHECK {TENANT_QUAL}
        """)
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON governance.object_tags TO edp_app"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON governance.object_tags")
    op.execute("DROP TABLE IF EXISTS governance.object_tags")
