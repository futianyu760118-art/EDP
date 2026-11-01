"""Add the tenant-scoped Inbox ledger for Phase 1 cross-system delivery.

Inbox uniqueness is consumer-scoped and follows the AEOS key:
tenant + consumer + source_system + object_type + object_id + revision + event_type.
The producer event UUID is not used as the consumer idempotency key because one
event may be consumed independently by several systems.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021_phase1_inbox"
down_revision: str | None = "0020_v13_tenant_code_autogen"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_TABLE = "event.inbox"
POLICY = "tenant_isolation"
TENANT_QUAL = "(tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE event.inbox (
            inbox_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            consumer TEXT NOT NULL,
            source_system TEXT NOT NULL,
            object_type TEXT NOT NULL,
            object_id TEXT NOT NULL,
            revision INT NOT NULL CHECK (revision > 0),
            event_type TEXT NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'PENDING'
                CHECK (status IN ('PENDING','PROCESSED','FAILED')),
            attempt_count INT NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
            last_error TEXT,
            processed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT,
            CONSTRAINT uq_inbox_delivery UNIQUE (
                tenant_id, consumer, source_system, object_type,
                object_id, revision, event_type
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_inbox_pending
            ON event.inbox(tenant_id, consumer, status, updated_at)
            WHERE status IN ('PENDING','FAILED')
        """
    )
    op.execute(f"ALTER TABLE {RLS_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {RLS_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLICY} ON {RLS_TABLE} USING {TENANT_QUAL} WITH CHECK {TENANT_QUAL}"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON event.inbox TO edp_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA event TO edp_app")


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {RLS_TABLE}")
    op.execute(f"DROP TABLE IF EXISTS {RLS_TABLE}")
