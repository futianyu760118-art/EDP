"""Add the tenant-scoped LeadIntakeV1 handoff ledger."""

from collections.abc import Sequence

from alembic import op

revision: str = "0022_phase1_lead_intake"
down_revision: str | None = "0021_phase1_inbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_TABLE = "event.lead_intakes"
POLICY = "tenant_isolation"
TENANT_QUAL = "(tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE event.lead_intakes (
            lead_intake_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            intake_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            payload JSONB NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING'
                CHECK (status IN ('PENDING','DELIVERED','FAILED')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT,
            CONSTRAINT uq_lead_intakes_tenant_idem UNIQUE (tenant_id, idempotency_key),
            CONSTRAINT uq_lead_intakes_tenant_intake UNIQUE (tenant_id, intake_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_lead_intakes_pending
            ON event.lead_intakes(tenant_id, status, updated_at)
            WHERE status IN ('PENDING','FAILED')
        """
    )
    op.execute(f"ALTER TABLE {RLS_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {RLS_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {POLICY} ON {RLS_TABLE} USING {TENANT_QUAL} WITH CHECK {TENANT_QUAL}"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON event.lead_intakes TO edp_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA event TO edp_app")


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {RLS_TABLE}")
    op.execute(f"DROP TABLE IF EXISTS {RLS_TABLE}")
