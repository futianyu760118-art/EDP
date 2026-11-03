"""Add AEOS person lifecycle event intake and per-system delivery state."""

from collections.abc import Sequence

from alembic import op

revision: str = "0024_phase1_person_lifecycle"
down_revision: str | None = "0023_phase1_lead_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "tenant_isolation"
TENANT_QUAL = "(tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {POLICY} ON {table} USING {TENANT_QUAL} WITH CHECK {TENANT_QUAL}")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE event.person_lifecycle_events (
            event_id TEXT PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            event_type TEXT NOT NULL CHECK (event_type IN ('person.offboarded','person.reinstated')),
            event_version INT NOT NULL CHECK (event_version = 1),
            source_system TEXT NOT NULL,
            object_type TEXT NOT NULL CHECK (object_type = 'Person'),
            object_id TEXT NOT NULL,
            revision INT NOT NULL CHECK (revision > 0),
            occurred_at TIMESTAMPTZ NOT NULL,
            effective_at TIMESTAMPTZ NOT NULL,
            correlation_id TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            payload JSONB NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('PENDING','SCHEDULED','RETRYING','PARTIAL','PENDING_CONFIRMATION','SYNCED','FAILED')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT,
            CONSTRAINT uq_person_lifecycle_event_idempotency UNIQUE (tenant_id, idempotency_key)
        )
    """)
    op.execute("""
        CREATE TABLE event.person_lifecycle_deliveries (
            delivery_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            event_id TEXT NOT NULL REFERENCES event.person_lifecycle_events(event_id) ON DELETE CASCADE,
            target_system TEXT NOT NULL,
            target_url TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('PENDING','SCHEDULED','RETRYING','SYNCED','SKIPPED','PENDING_CONFIRMATION','FAILED','DLQ')),
            attempt_count INT NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
            next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_error TEXT,
            response JSONB,
            delivered_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT,
            CONSTRAINT uq_person_lifecycle_delivery UNIQUE (tenant_id, event_id, target_system)
        )
    """)
    op.execute("CREATE INDEX idx_person_lifecycle_delivery_due ON event.person_lifecycle_deliveries(tenant_id, status, next_attempt_at)")
    _enable_rls("event.person_lifecycle_events")
    _enable_rls("event.person_lifecycle_deliveries")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON event.person_lifecycle_events TO edp_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON event.person_lifecycle_deliveries TO edp_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA event TO edp_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON event.person_lifecycle_deliveries")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON event.person_lifecycle_events")
    op.execute("DROP TABLE IF EXISTS event.person_lifecycle_deliveries")
    op.execute("DROP TABLE IF EXISTS event.person_lifecycle_events")
