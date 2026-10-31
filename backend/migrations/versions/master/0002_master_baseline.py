"""master schema 基线（设计文档附录 A.2 逐条转录）。

schema：master；表数：7；RLS 表数：7（全部含 tenant_id 且标注 "-- + RLS"）。

7 张表：business_objects, customers, products, materials, suppliers, boms,
bom_items（全部标注 "+ 审计字段"，追加 created_at/updated_at/created_by/updated_by）。

适配记录：
- bom_items.position 为 PG 保留字（POSITION(substr IN str) 函数语法），以
  "position" 引号创建，实际列名仍为小写 position，与附录 A 一致。

Revision ID: 0002_master
Revises: 0001_platform
Create Date: 2026-09-14
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_master"
down_revision: str | None = "0001_platform"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A.2 全部表均含 tenant_id 且标注 "-- + RLS"
RLS_TABLES = (
    "master.business_objects",
    "master.customers",
    "master.products",
    "master.materials",
    "master.suppliers",
    "master.boms",
    "master.bom_items",
)

POLICY = "tenant_isolation"
TENANT_QUAL = "(tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {POLICY} ON {table} USING {TENANT_QUAL} WITH CHECK {TENANT_QUAL}")


def upgrade() -> None:
    # ---- 0. schema ----
    op.execute("CREATE SCHEMA IF NOT EXISTS master")

    # ---- 1. 业务对象注册元表（全局锚点） ----
    op.execute("""
        CREATE TABLE master.business_objects (
            object_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            object_type TEXT NOT NULL,
            owner_domain TEXT NOT NULL,
            source_system TEXT NOT NULL,
            source_id TEXT NOT NULL,
            revision BIGINT NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'ACTIVE'
                CHECK (status IN ('ACTIVE','SUSPENDED','MERGED')),
            merged_into UUID REFERENCES master.business_objects(object_id),
            attributes JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_bo_natural_key
            ON master.business_objects(tenant_id, source_system, object_type, source_id)
    """)
    op.execute("""
        CREATE INDEX idx_bo_type
            ON master.business_objects(tenant_id, object_type, status)
    """)
    op.execute("CREATE INDEX idx_bo_domain ON master.business_objects(tenant_id, owner_domain)")
    op.execute("CREATE INDEX idx_bo_attrs ON master.business_objects USING GIN (attributes)")

    # ---- 2. 客户 ----
    op.execute("""
        CREATE TABLE master.customers (
            customer_id UUID PRIMARY KEY REFERENCES master.business_objects(object_id),
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            level TEXT,
            attributes JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_customer_code ON master.customers(tenant_id, code)")

    # ---- 3. 产品 / 物料 / 供应商 ----
    op.execute("""
        CREATE TABLE master.products (
            product_id UUID PRIMARY KEY REFERENCES master.business_objects(object_id),
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            category TEXT,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_product_code ON master.products(tenant_id, code)")

    op.execute("""
        CREATE TABLE master.materials (
            material_id UUID PRIMARY KEY REFERENCES master.business_objects(object_id),
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            unit TEXT,
            attributes JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_material_code ON master.materials(tenant_id, code)")

    op.execute("""
        CREATE TABLE master.suppliers (
            supplier_id UUID PRIMARY KEY REFERENCES master.business_objects(object_id),
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            attributes JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_supplier_code ON master.suppliers(tenant_id, code)")

    # ---- 4. BOM 及明细 ----
    op.execute("""
        CREATE TABLE master.boms (
            bom_id UUID PRIMARY KEY REFERENCES master.business_objects(object_id),
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            product_id UUID NOT NULL REFERENCES master.products(product_id),
            version TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ACTIVE'
                CHECK (status IN ('DRAFT','ACTIVE','RETIRED')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX uq_bom_product_version
            ON master.boms(tenant_id, product_id, version, status)
    """)

    op.execute("""
        CREATE TABLE master.bom_items (
            item_id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES platform.tenants(tenant_id),
            bom_id UUID NOT NULL REFERENCES master.boms(bom_id),
            material_id UUID NOT NULL REFERENCES master.materials(material_id),
            quantity NUMERIC(18,4) NOT NULL CHECK (quantity > 0),
            "position" INT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by TEXT,
            updated_by TEXT
        )
    """)
    op.execute("CREATE INDEX idx_bom_items_bom ON master.bom_items(tenant_id, bom_id)")

    # ---- 5. RLS：ENABLE + FORCE + tenant_isolation ----
    for table in RLS_TABLES:
        _enable_rls(table)

    # ---- 6. 尾部统一授权 ----
    op.execute("GRANT USAGE ON SCHEMA master TO edp_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA master TO edp_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA master TO edp_app")


def downgrade() -> None:
    # 逆序清理：策略 → schema（CASCADE 连带全部表/索引/序列）。
    for table in RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")

    op.execute("DROP SCHEMA IF EXISTS master CASCADE")
