"""projections ORM 单测：14 张领域表的 schema/表名/列名逐字对齐迁移 DDL。

断言口径以迁移 0002（master 6 表）与 0004（sales/delivery/rd 8 表）为准；
列序与 DDL 声明序一致，列集合必须完全相等（多/少/改名均失败）。
"""

import pytest
from edp_api.modules.projections import models as m
from sqlalchemy import Numeric

AUDIT = ("created_at", "updated_at", "created_by", "updated_by")

TABLES = [
    (
        m.Customer,
        "master",
        "customers",
        (
            "customer_id",
            "tenant_id",
            "code",
            "name",
            "level",
            "attributes",
            *AUDIT,
        ),
    ),
    (
        m.Material,
        "master",
        "materials",
        (
            "material_id",
            "tenant_id",
            "code",
            "name",
            "unit",
            "attributes",
            *AUDIT,
        ),
    ),
    (
        m.Product,
        "master",
        "products",
        (
            "product_id",
            "tenant_id",
            "code",
            "name",
            "category",
            "status",
            *AUDIT,
        ),
    ),
    (
        m.Supplier,
        "master",
        "suppliers",
        ("supplier_id", "tenant_id", "code", "name", "attributes", *AUDIT),
    ),
    (
        m.Bom,
        "master",
        "boms",
        ("bom_id", "tenant_id", "product_id", "version", "status", *AUDIT),
    ),
    (
        m.BomItem,
        "master",
        "bom_items",
        (
            "item_id",
            "tenant_id",
            "bom_id",
            "material_id",
            "quantity",
            "position",
            *AUDIT,
        ),
    ),
    (
        m.SalesOrder,
        "sales",
        "orders",
        (
            "order_id",
            "tenant_id",
            "order_no",
            "customer_id",
            "amount",
            "currency",
            "status",
            "order_date",
            "delivery_date",
            "snapshot_at",
            "attributes",
            *AUDIT,
        ),
    ),
    (
        m.SalesOrderLine,
        "sales",
        "order_lines",
        (
            "line_id",
            "tenant_id",
            "order_id",
            "product_id",
            "material_id",
            "quantity",
            "unit_price",
            "amount",
            *AUDIT,
        ),
    ),
    (
        m.Inventory,
        "delivery",
        "inventory",
        (
            "inv_id",
            "tenant_id",
            "material_id",
            "warehouse",
            "quantity_available",
            "quantity_reserved",
            "snapshot_at",
            "attributes",
            *AUDIT,
        ),
    ),
    (
        m.PurchaseOrder,
        "delivery",
        "purchase_orders",
        (
            "po_id",
            "tenant_id",
            "po_no",
            "supplier_id",
            "material_id",
            "quantity",
            "expected_date",
            "status",
            "snapshot_at",
            "attributes",
            *AUDIT,
        ),
    ),
    (
        m.SupplierLeadTime,
        "delivery",
        "supplier_lead_times",
        (
            "id",
            "tenant_id",
            "supplier_id",
            "material_id",
            "lead_time_days",
            "updated_at",
            "created_at",
            "created_by",
            "updated_by",
        ),
    ),
    (
        m.RdProject,
        "rd",
        "projects",
        (
            "project_id",
            "tenant_id",
            "project_no",
            "product_id",
            "status",
            "stage",
            "readiness_level",
            "snapshot_at",
            "attributes",
            *AUDIT,
        ),
    ),
    (
        m.RdMilestone,
        "rd",
        "milestones",
        (
            "milestone_id",
            "tenant_id",
            "project_id",
            "name",
            "due_date",
            "actual_date",
            "status",
            *AUDIT,
        ),
    ),
    (
        m.Capacity,
        "delivery",
        "capacity",
        (
            "id",
            "tenant_id",
            "product_line",
            "period",
            "capacity_qty",
            "snapshot_at",
            *AUDIT,
        ),
    ),
]


def test_metadata_holds_exactly_14_tables() -> None:
    assert len(TABLES) == 14
    assert set(m.Base.metadata.tables) == {
        f"{schema}.{table}" for _, schema, table, _ in TABLES
    }


@pytest.mark.parametrize(
    ("model", "schema", "table", "columns"),
    TABLES,
    ids=[model.__name__ for model, *_ in TABLES],
)
def test_schema_table_and_columns(
    model: type[m.Base], schema: str, table: str, columns: tuple[str, ...]
) -> None:
    assert model.__table__.schema == schema
    assert model.__table__.name == table
    assert tuple(model.__table__.columns.keys()) == columns


@pytest.mark.parametrize(
    "model",
    [model for model, *_ in TABLES],
    ids=[model.__name__ for model, *_ in TABLES],
)
def test_no_foreign_keys_declared(model: type[m.Base]) -> None:
    assert not any(col.foreign_keys for col in model.__table__.columns)


NUMERIC_18_4 = [
    (m.BomItem, "quantity"),
    (m.SalesOrder, "amount"),
    (m.SalesOrderLine, "quantity"),
    (m.SalesOrderLine, "unit_price"),
    (m.SalesOrderLine, "amount"),
    (m.Inventory, "quantity_available"),
    (m.Inventory, "quantity_reserved"),
    (m.PurchaseOrder, "quantity"),
    (m.Capacity, "capacity_qty"),
]


@pytest.mark.parametrize(
    ("model", "column"),
    NUMERIC_18_4,
    ids=[f"{model.__name__}.{column}" for model, column in NUMERIC_18_4],
)
def test_numeric_18_4_precision(model: type[m.Base], column: str) -> None:
    col_type = model.__table__.c[column].type
    assert isinstance(col_type, Numeric)
    assert (col_type.precision, col_type.scale) == (18, 4)


def test_nullability_and_defaults_match_ddl() -> None:
    assert m.SalesOrder.__table__.c.customer_id.nullable is True
    assert m.SalesOrder.__table__.c.amount.nullable is True
    assert m.SalesOrder.__table__.c.order_date.nullable is True
    assert m.SalesOrder.__table__.c.snapshot_at.nullable is False
    assert m.BomItem.__table__.c.position.nullable is True
    assert m.Inventory.__table__.c.quantity_available.nullable is False
    assert m.PurchaseOrder.__table__.c.supplier_id.nullable is True
    assert m.Capacity.__table__.c.capacity_qty.nullable is False
    assert m.Capacity.__table__.c.snapshot_at.nullable is False

    assert m.Product.__table__.c.status.default.arg == "ACTIVE"
    assert m.Bom.__table__.c.status.default.arg == "ACTIVE"
    assert m.SalesOrder.__table__.c.currency.default.arg == "CNY"
    assert m.Inventory.__table__.c.quantity_available.default.arg == 0
    assert m.Inventory.__table__.c.quantity_reserved.default.arg == 0
    assert m.RdMilestone.__table__.c.status.default.arg == "PENDING"
