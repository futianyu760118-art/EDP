"""event schema 基线（设计文档附录 A.3 逐条转录）。

schema：event；表数：2；RLS 表数：2（全部含 tenant_id 且标注 "-- + RLS"）。

2 张表：events, outbox（均标注 "+ 审计字段"）。
部分索引：idx_events_risk（WHERE risk_level IS NOT NULL）、
uq_events_idem（WHERE idempotency_key IS NOT NULL）、
idx_outbox_dispatch（WHERE status = 'PENDING'）。

Revision ID: 0003_event
Revises: 0002_master
Create Date: 2026-09-14
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_event"
down_revision: str | None = "0002_master"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A.3 全部表均含 tenant_id 且标注 "-- + RLS"
RLS_TABLES = (
    "event.events",
    "event.outbox",
)

POLICY = "tenant_isolation"
TENANT_QUAL = "(tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {POLICY} ON {table} USING {TENANT_QUAL} WITH CHECK {TENANT_QUAL}")


def upgrade() -> None:
    # ---- 0. schema ----
    op.execute("CREATE SCHEMA IF NOT EXISTS event")

    # ---- 1. 事件表（event_id = UUIDv5 确定性生成，全局唯一） ----
    op.execute("""
        CREATE TABLE event.events (
            event_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            event_type TEXT NOT NULL,
            object_id UUID NOT NULL REFERENCES master.business_objects(object_id),
            source_system TEXT NOT NULL,
            occurred_at TIMESTAMPTZ NOT NULL,
            actor_type TEXT CHECK (actor_type IN ('HUMAN','SERVICE','AI')),
            actor_id TEXT,
            result_type TEXT,
            risk_level TEXT CHECK (risk_level IN ('P0','P1','P2','P3') OR risk_level IS NULL),
            score NUMERIC(10,4),
            data JSONB NOT NULL DEFAULT '{}',
            idempotency_key TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("""
        CREATE INDEX idx_events_object
            ON event.events(tenant_id, object_id, occurred_at DESC)
    """)
    op.execute("""
        CREATE INDEX idx_events_type
            ON event.events(tenant_id, event_type, occurred_at DESC)
    """)
    op.execute("""
        CREATE INDEX idx_events_risk
            ON event.events(tenant_id, risk_level, occurred_at DESC)
            WHERE risk_level IS NOT NULL
    """)
    op.execute("CREATE INDEX idx_events_data ON event.events USING GIN (data)")
    op.execute("""
        CREATE UNIQUE INDEX uq_events_idem
            ON event.events(tenant_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL
    """)

    # ---- 2. 事务性发件箱 ----
    op.execute("""
        CREATE TABLE event.outbox (
            outbox_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            aggregate_type TEXT NOT NULL,
            aggregate_id UUID NOT NULL,
            event_type TEXT NOT NULL,
            payload JSONB NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING'
                CHECK (status IN ('PENDING','PUBLISHED','FAILED')),
            retry_count INT NOT NULL DEFAULT 0,
            available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            published_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("""
        CREATE INDEX idx_outbox_dispatch
            ON event.outbox(tenant_id, status, available_at)
            WHERE status = 'PENDING'
    """)

    # ---- 3. RLS：ENABLE + FORCE + tenant_isolation ----
    for table in RLS_TABLES:
        _enable_rls(table)

    # ---- 4. 尾部统一授权 ----
    op.execute("GRANT USAGE ON SCHEMA event TO edp_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA event TO edp_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA event TO edp_app")


def downgrade() -> None:
    # 逆序清理：策略 → schema（CASCADE 连带全部表/索引/序列）。
    for table in RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")

    op.execute("DROP SCHEMA IF EXISTS event CASCADE")
