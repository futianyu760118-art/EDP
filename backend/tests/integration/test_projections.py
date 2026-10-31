"""T3 projections 集成测试：源记录 → 领域快照表投影 + 自然键解析 + 查询口。

真实 PG（testcontainers + alembic 全量迁移）。应用会话 = edp_app 角色
（app_role_engine，FORCE RLS + bind_tenant）——投影落库与查询在真实 RLS 下
验证；前置 business_objects 以 migrator 直插（绕 RLS，无 outbox/审计副作用）。
数据痕迹以 W3PROJ 前缀识别，每测试后清场（含 T4 前切面尚未排除的领域表审计行）。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4, uuid5

import pytest
from edp_adapters.base import SourceRecord
from edp_api.core.db import bind_tenant
from edp_api.modules.projections import service as projections_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

pytestmark = [pytest.mark.integration]

ANCHOR = datetime(2026, 9, 28, 8, 30, tzinfo=UTC)

CUSTOMER_CODE = "W3PROJ-C-1"
MATERIAL_CODE = "W3PROJ-M-1"
PRODUCT_CODE = "W3PROJ-P-1"
SUPPLIER_CODE = "W3PROJ-S-1"
ORDER_NO = "W3PROJ-SO-1"
PO_NO = "W3PROJ-PO-1"
BOM_NO = "W3PROJ-BOM-1"
PROJECT_NO = "W3PROJ-PRJ-1"
INVENTORY_SOURCE_ID = f"{MATERIAL_CODE}:WH-01"
LEAD_TIME_SOURCE_ID = f"{SUPPLIER_CODE}:{MATERIAL_CODE}"

_OWNER_DOMAINS = {
    "CUSTOMER": "master",
    "MATERIAL": "master",
    "PRODUCT": "master",
    "SUPPLIER": "master",
    "ORDER": "sales",
    "PURCHASE_ORDER": "delivery",
    "INVENTORY": "delivery",
    "BOM": "master",
    "SUPPLIER_LEAD_TIME": "delivery",
    "PROJECT": "rd",
}

_DOMAIN_AUDIT_TABLES = (
    "customers",
    "materials",
    "products",
    "suppliers",
    "boms",
    "bom_items",
    "orders",
    "order_lines",
    "inventory",
    "purchase_orders",
    "supplier_lead_times",
    "projects",
    "milestones",
)


@pytest.fixture
async def default_tenant_id(db_session: AsyncSession) -> UUID:
    """default 租户 id（0005 种子；tenants 控制面表，migrator 直查）。"""
    return (
        await db_session.execute(
            text("SELECT tenant_id FROM platform.tenants WHERE slug = 'default'")
        )
    ).scalar_one()


@pytest.fixture(autouse=True)
async def _clean_projection_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> AsyncIterator[None]:
    """每测试后清场：审计行（T4 前切面尚未排除 13 张派生表）→ 领域行（逆依赖
    序）→ business_objects → 临时租户（migrator 绕 RLS）。"""
    yield
    await db_session.execute(
        text(
            "DELETE FROM platform.audit_logs"
            " WHERE tenant_id = :t AND resource_type = ANY(:types)"
        ),
        {"t": default_tenant_id, "types": list(_DOMAIN_AUDIT_TABLES)},
    )
    subquery = (
        "SELECT object_id FROM master.business_objects WHERE source_id LIKE 'W3PROJ%'"
    )
    for sql in (
        f"DELETE FROM sales.order_lines WHERE order_id IN ({subquery})",
        "DELETE FROM sales.orders WHERE order_no LIKE 'W3PROJ%'",
        f"DELETE FROM master.bom_items WHERE bom_id IN ({subquery})",
        f"DELETE FROM master.boms WHERE bom_id IN ({subquery})",
        f"DELETE FROM rd.milestones WHERE project_id IN ({subquery})",
        "DELETE FROM rd.projects WHERE project_no LIKE 'W3PROJ%'",
        f"DELETE FROM delivery.inventory WHERE inv_id IN ({subquery})",
        "DELETE FROM delivery.purchase_orders WHERE po_no LIKE 'W3PROJ%'",
        f"DELETE FROM delivery.supplier_lead_times WHERE supplier_id IN ({subquery})",
        "DELETE FROM master.customers WHERE code LIKE 'W3PROJ%'",
        "DELETE FROM master.materials WHERE code LIKE 'W3PROJ%'",
        "DELETE FROM master.products WHERE code LIKE 'W3PROJ%'",
        "DELETE FROM master.suppliers WHERE code LIKE 'W3PROJ%'",
        "DELETE FROM master.business_objects WHERE source_id LIKE 'W3PROJ%'",
        "DELETE FROM platform.tenant_usage_daily WHERE tenant_id IN"
        " (SELECT tenant_id FROM platform.tenants WHERE slug = 'w3proj-tenant-b')",
        "DELETE FROM platform.tenants WHERE slug = 'w3proj-tenant-b'",
    ):
        await db_session.execute(text(sql))
    await db_session.commit()


@asynccontextmanager
async def _tenant_session(
    engine: AsyncEngine, tenant_id: UUID
) -> AsyncIterator[AsyncSession]:
    """edp_app 会话（bind_tenant 后受 FORCE RLS）；收尾回滚。"""
    session = async_sessionmaker(engine, expire_on_commit=False)()
    try:
        await bind_tenant(session, tenant_id)
        yield session
    finally:
        await session.rollback()
        await session.close()


async def _insert_objects(
    db_session: AsyncSession,
    tenant_id: UUID,
    specs: list[tuple[str, str, str]],
) -> dict[str, UUID]:
    """migrator 直插 business_objects；返回 {source_id: object_id}。"""
    mapping: dict[str, UUID] = {}
    for object_type, source_system, source_id in specs:
        object_id = uuid5(tenant_id, f"W3PROJ:{object_type}:{source_id}")
        mapping[source_id] = object_id
        await db_session.execute(
            text(
                "INSERT INTO master.business_objects"
                " (object_id, tenant_id, object_type, owner_domain, source_system, source_id)"
                " VALUES (:object_id, :tenant_id, :object_type, :owner_domain,"
                " :source_system, :source_id)"
            ),
            {
                "object_id": object_id,
                "tenant_id": tenant_id,
                "object_type": object_type,
                "owner_domain": _OWNER_DOMAINS.get(object_type, "master"),
                "source_system": source_system,
                "source_id": source_id,
            },
        )
    await db_session.commit()
    return mapping


async def _project(
    engine: AsyncEngine,
    tenant_id: UUID,
    records: list[SourceRecord],
    objects: dict[str, UUID],
) -> None:
    """应用会话逐条投影（单事务提交）。"""
    async with _tenant_session(engine, tenant_id) as session:
        for record in records:
            await projections_service.project_record(
                session, tenant_id, record, objects[record.source_id]
            )
        await session.commit()


async def _scalar(db_session: AsyncSession, sql: str, **params: Any) -> Any:
    return (await db_session.execute(text(sql), params)).scalar_one()


async def _row(db_session: AsyncSession, sql: str, **params: Any) -> Any:
    return (await db_session.execute(text(sql), params)).mappings().one()


def _record(
    object_type: str,
    source_id: str,
    payload: dict[str, Any],
    *,
    source_system: str = "erp",
    offset_minutes: int = 0,
) -> SourceRecord:
    return SourceRecord(
        source_system=source_system,
        object_type=object_type,
        source_id=source_id,
        occurred_at=ANCHOR + timedelta(minutes=offset_minutes),
        payload={"owner_domain": _OWNER_DOMAINS.get(object_type, "master"), **payload},
    )


def _dataset() -> list[SourceRecord]:
    """依赖顺序的 10 类记录（主数据先于订单/采购/BOM/交期）。"""
    return [
        _record(
            "CUSTOMER",
            CUSTOMER_CODE,
            {"name": "投影客户", "level": "VIP", "region": "华东"},
        ),
        _record(
            "MATERIAL",
            MATERIAL_CODE,
            {"name": "投影物料", "unit": "件", "total_available": 3200},
        ),
        _record(
            "PRODUCT",
            PRODUCT_CODE,
            {"name": "投影产品", "category": "整机", "status": "ACTIVE"},
        ),
        _record("SUPPLIER", SUPPLIER_CODE, {"name": "投影供应商", "rating": "A"}),
        _record(
            "ORDER",
            ORDER_NO,
            {
                "name": "销售订单 W3PROJ-SO-1",
                "customer_code": CUSTOMER_CODE,
                "amount": 120000.0,
                "currency": "CNY",
                "status": "已确认",
                "order_date": "2026-09-20",
                "delivery_date": "2026-10-20T08:00:00Z",
                "lines": [
                    {"product_code": PRODUCT_CODE, "quantity": 500, "unit_price": 240.0},
                    {"material_code": MATERIAL_CODE, "quantity": 10, "unit_price": 5.5},
                ],
                "note": "加急",
            },
        ),
        _record(
            "PURCHASE_ORDER",
            PO_NO,
            {
                "supplier_code": SUPPLIER_CODE,
                "material_code": MATERIAL_CODE,
                "quantity": 2000,
                "expected_date": "2026-10-20",
                "status": "在途",
            },
        ),
        _record(
            "INVENTORY",
            INVENTORY_SOURCE_ID,
            {
                "material_code": MATERIAL_CODE,
                "warehouse": "WH-01",
                "available": 0,
                "reserved": 0,
            },
        ),
        _record(
            "BOM",
            BOM_NO,
            {
                "product_code": PRODUCT_CODE,
                "bom_version": "V3",
                "status": "ACTIVE",
                "items": [{"material_code": MATERIAL_CODE, "quantity": 2.5}],
            },
        ),
        _record(
            "SUPPLIER_LEAD_TIME",
            LEAD_TIME_SOURCE_ID,
            {
                "supplier_code": SUPPLIER_CODE,
                "material_code": MATERIAL_CODE,
                "lead_time_days": 10,
            },
        ),
        _record(
            "PROJECT",
            PROJECT_NO,
            {
                "product_code": PRODUCT_CODE,
                "status": "验证中",
                "stage": "DVT",
                "readiness_level": "未达产",
                "milestones": [
                    {
                        "name": "完成验证与测试",
                        "status": "IN_PROGRESS",
                        "due_date": "2026-10-05",
                    }
                ],
            },
            source_system="plm",
        ),
    ]


async def _project_dataset(
    app_role_engine: AsyncEngine, db_session: AsyncSession, tenant_id: UUID
) -> tuple[list[SourceRecord], dict[str, UUID]]:
    records = _dataset()
    objects = await _insert_objects(
        db_session,
        tenant_id,
        [(r.object_type, r.source_system, r.source_id) for r in records],
    )
    await _project(app_role_engine, tenant_id, records, objects)
    return records, objects


# ---- 1. 10 类记录投影：列映射/attributes 兜底/FK 解析/行明细 ----


async def test_project_record_writes_all_domain_tables(
    app_role_engine: AsyncEngine, db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    _, objects = await _project_dataset(
        app_role_engine, db_session, default_tenant_id
    )
    order_id = objects[ORDER_NO]

    customer = await _row(
        db_session,
        "SELECT * FROM master.customers WHERE code = :code",
        code=CUSTOMER_CODE,
    )
    assert customer["customer_id"] == objects[CUSTOMER_CODE]
    assert customer["name"] == "投影客户"
    assert customer["level"] == "VIP"
    assert customer["attributes"] == {"region": "华东"}

    material = await _row(
        db_session,
        "SELECT * FROM master.materials WHERE code = :code",
        code=MATERIAL_CODE,
    )
    assert material["unit"] == "件"
    assert material["attributes"] == {"total_available": 3200}

    product = await _row(
        db_session,
        "SELECT * FROM master.products WHERE code = :code",
        code=PRODUCT_CODE,
    )
    assert product["category"] == "整机"
    assert product["status"] == "ACTIVE"

    supplier = await _row(
        db_session,
        "SELECT * FROM master.suppliers WHERE code = :code",
        code=SUPPLIER_CODE,
    )
    assert supplier["attributes"] == {"rating": "A"}

    order = await _row(
        db_session, "SELECT * FROM sales.orders WHERE order_no = :no", no=ORDER_NO
    )
    assert order["order_id"] == order_id
    assert order["customer_id"] == objects[CUSTOMER_CODE]
    assert order["amount"] == Decimal("120000")
    assert order["currency"] == "CNY"
    assert order["status"] == "已确认"
    assert order["order_date"] == datetime(2026, 9, 20, tzinfo=UTC)
    assert order["delivery_date"] == datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
    assert order["snapshot_at"] == ANCHOR
    assert order["attributes"] == {"name": "销售订单 W3PROJ-SO-1", "note": "加急"}

    lines = (
        (
            await db_session.execute(
                text(
                    "SELECT * FROM sales.order_lines"
                    " WHERE order_id = :oid ORDER BY line_id"
                ),
                {"oid": order_id},
            )
        )
        .mappings()
        .all()
    )
    assert len(lines) == 2
    by_product = {line["product_id"]: line for line in lines if line["product_id"]}
    assert set(by_product) == {objects[PRODUCT_CODE]}
    product_line = by_product[objects[PRODUCT_CODE]]
    assert product_line["line_id"] == uuid5(order_id, "line:0")
    assert product_line["quantity"] == Decimal("500")
    assert product_line["unit_price"] == Decimal("240")
    assert product_line["amount"] == Decimal("120000")
    by_material = {line["material_id"]: line for line in lines if line["material_id"]}
    assert set(by_material) == {objects[MATERIAL_CODE]}
    assert by_material[objects[MATERIAL_CODE]]["amount"] == Decimal("55")

    po = await _row(
        db_session,
        "SELECT * FROM delivery.purchase_orders WHERE po_no = :no",
        no=PO_NO,
    )
    assert po["po_id"] == objects[PO_NO]
    assert po["supplier_id"] == objects[SUPPLIER_CODE]
    assert po["material_id"] == objects[MATERIAL_CODE]
    assert po["quantity"] == Decimal("2000")
    assert po["expected_date"] == datetime(2026, 10, 20, tzinfo=UTC)
    assert po["status"] == "在途"
    assert po["snapshot_at"] == ANCHOR

    inv = await _row(
        db_session,
        "SELECT * FROM delivery.inventory WHERE inv_id = :oid",
        oid=objects[INVENTORY_SOURCE_ID],
    )
    assert inv["material_id"] == objects[MATERIAL_CODE]
    assert inv["warehouse"] == "WH-01"
    assert inv["quantity_available"] == Decimal(0)
    assert inv["quantity_reserved"] == Decimal(0)

    bom = await _row(
        db_session,
        "SELECT * FROM master.boms WHERE bom_id = :oid",
        oid=objects[BOM_NO],
    )
    assert bom["product_id"] == objects[PRODUCT_CODE]
    assert bom["version"] == "V3"
    assert bom["status"] == "ACTIVE"
    bom_item = await _row(
        db_session,
        "SELECT * FROM master.bom_items WHERE bom_id = :oid",
        oid=objects[BOM_NO],
    )
    assert bom_item["item_id"] == uuid5(objects[BOM_NO], "item:0")
    assert bom_item["material_id"] == objects[MATERIAL_CODE]
    assert bom_item["quantity"] == Decimal("2.5")
    assert bom_item["position"] == 0

    lead_time = await _row(
        db_session,
        "SELECT * FROM delivery.supplier_lead_times WHERE supplier_id = :sid",
        sid=objects[SUPPLIER_CODE],
    )
    assert lead_time["supplier_id"] == objects[SUPPLIER_CODE]
    assert lead_time["material_id"] == objects[MATERIAL_CODE]
    assert lead_time["lead_time_days"] == 10
    assert lead_time["updated_at"] == ANCHOR

    project = await _row(
        db_session,
        "SELECT * FROM rd.projects WHERE project_no = :no",
        no=PROJECT_NO,
    )
    assert project["project_id"] == objects[PROJECT_NO]
    assert project["product_id"] == objects[PRODUCT_CODE]
    assert project["status"] == "验证中"
    assert project["stage"] == "DVT"
    assert project["readiness_level"] == "未达产"
    assert project["attributes"] == {}
    milestone = await _row(
        db_session,
        "SELECT * FROM rd.milestones WHERE project_id = :pid",
        pid=objects[PROJECT_NO],
    )
    assert milestone["milestone_id"] == uuid5(objects[PROJECT_NO], "milestone:0")
    assert milestone["name"] == "完成验证与测试"
    assert milestone["status"] == "IN_PROGRESS"
    assert milestone["due_date"] == datetime(2026, 10, 5, tzinfo=UTC)
    assert milestone["actual_date"] is None


# ---- 2. 同 object_id 二次投影：行明细替换不翻倍 + 缺键不降级 ----


async def test_reproject_replaces_lines_and_preserves_missing_values(
    app_role_engine: AsyncEngine, db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    records = _dataset()[:5]  # CUSTOMER/MATERIAL/PRODUCT/SUPPLIER/ORDER
    objects = await _insert_objects(
        db_session,
        default_tenant_id,
        [(r.object_type, r.source_system, r.source_id) for r in records],
    )
    await _project(app_role_engine, default_tenant_id, records, objects)
    order_id = objects[ORDER_NO]

    # 二次投影：金额缺键（保留旧值）、状态更新、行明细由 2 行缩为 1 行
    second = _record(
        "ORDER",
        ORDER_NO,
        {
            "customer_code": CUSTOMER_CODE,
            "status": "已发货",
            "lines": [
                {"product_code": PRODUCT_CODE, "quantity": 500, "unit_price": 240.0}
            ],
        },
        offset_minutes=60,
    )
    await _project(app_role_engine, default_tenant_id, [second], objects)

    order = await _row(
        db_session, "SELECT * FROM sales.orders WHERE order_no = :no", no=ORDER_NO
    )
    assert order["amount"] == Decimal("120000")  # 缺键 → 保留首次快照
    assert order["status"] == "已发货"
    assert order["snapshot_at"] == ANCHOR + timedelta(minutes=60)

    lines = (
        (
            await db_session.execute(
                text("SELECT * FROM sales.order_lines WHERE order_id = :oid"),
                {"oid": order_id},
            )
        )
        .mappings()
        .all()
    )
    assert len(lines) == 1  # 先删后插，不翻倍
    assert lines[0]["line_id"] == uuid5(order_id, "line:0")
    assert lines[0]["product_id"] == objects[PRODUCT_CODE]


# ---- 3. resolve 未命中：FK 置 NULL 不抛 ----


async def test_resolve_miss_leaves_fk_null_without_error(
    app_role_engine: AsyncEngine, db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    record = _record(
        "ORDER",
        ORDER_NO,
        {
            "customer_code": "W3PROJ-NOPE-C",
            "amount": 2,
            "lines": [
                {
                    "product_code": "W3PROJ-NOPE-P",
                    "material_code": "W3PROJ-NOPE-M",
                    "quantity": 1,
                    "unit_price": 2,
                }
            ],
        },
    )
    objects = await _insert_objects(
        db_session, default_tenant_id, [("ORDER", "erp", ORDER_NO)]
    )
    await _project(app_role_engine, default_tenant_id, [record], objects)

    order = await _row(
        db_session, "SELECT * FROM sales.orders WHERE order_no = :no", no=ORDER_NO
    )
    assert order["customer_id"] is None
    line = await _row(
        db_session,
        "SELECT * FROM sales.order_lines WHERE order_id = :oid",
        oid=objects[ORDER_NO],
    )
    assert line["product_id"] is None
    assert line["material_id"] is None
    assert line["amount"] == Decimal("2")


# ---- 4. SUPPLIER_LEAD_TIME：(tenant, supplier, material) 唯一键 upsert ----


async def test_lead_time_upserts_by_supplier_material_key(
    app_role_engine: AsyncEngine, db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    first_source_id = f"{SUPPLIER_CODE}:{MATERIAL_CODE}"
    second_source_id = f"{SUPPLIER_CODE}:{MATERIAL_CODE}#v2"
    specs = [
        ("SUPPLIER", "erp", SUPPLIER_CODE),
        ("MATERIAL", "erp", MATERIAL_CODE),
        ("SUPPLIER_LEAD_TIME", "erp", first_source_id),
        ("SUPPLIER_LEAD_TIME", "erp", second_source_id),
    ]
    objects = await _insert_objects(db_session, default_tenant_id, specs)
    supplier_record = _record("SUPPLIER", SUPPLIER_CODE, {"name": "投影供应商"})
    material_record = _record("MATERIAL", MATERIAL_CODE, {"name": "投影物料"})
    first = _record(
        "SUPPLIER_LEAD_TIME",
        first_source_id,
        {
            "supplier_code": SUPPLIER_CODE,
            "material_code": MATERIAL_CODE,
            "lead_time_days": 10,
        },
    )
    second = _record(
        "SUPPLIER_LEAD_TIME",
        second_source_id,
        {
            "supplier_code": SUPPLIER_CODE,
            "material_code": MATERIAL_CODE,
            "lead_time_days": 15,
        },
        offset_minutes=120,
    )
    await _project(
        app_role_engine,
        default_tenant_id,
        [supplier_record, material_record, first],
        objects,
    )
    await _project(app_role_engine, default_tenant_id, [second], objects)

    rows = (
        (
            await db_session.execute(
                text(
                    "SELECT * FROM delivery.supplier_lead_times WHERE supplier_id = :sid"
                ),
                {"sid": objects[SUPPLIER_CODE]},
            )
        )
        .mappings()
        .all()
    )
    assert len(rows) == 1  # 自然键 upsert，不产生第二行
    assert rows[0]["lead_time_days"] == 15
    assert rows[0]["id"] == uuid5(objects[first_source_id], "lead")
    assert rows[0]["updated_at"] == ANCHOR + timedelta(minutes=120)


# ---- 5. tools 查询口：join 主数据 code + 未命中 None/[] ----


async def test_query_functions_return_joined_views(
    app_role_engine: AsyncEngine, db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    await _project_dataset(app_role_engine, db_session, default_tenant_id)

    async with _tenant_session(app_role_engine, default_tenant_id) as sess:
        view = await projections_service.get_order_by_no(sess, default_tenant_id, ORDER_NO)
        assert view is not None
        assert view.order.order_no == ORDER_NO
        assert view.customer is not None
        assert (view.customer.code, view.customer.level) == (CUSTOMER_CODE, "VIP")
        assert len(view.lines) == 2
        assert {(line.product_code, line.material_code) for line in view.lines} == {
            (PRODUCT_CODE, None),
            (None, MATERIAL_CODE),
        }
        assert {line.line.quantity for line in view.lines} == {
            Decimal("500"),
            Decimal("10"),
        }

        orders = await projections_service.list_orders(
            sess, default_tenant_id, customer_code=CUSTOMER_CODE, status="已确认"
        )
        assert [item.order.order_no for item in orders] == [ORDER_NO]
        assert orders[0].customer is not None
        assert orders[0].lines == ()  # 摘要列表不含行明细
        assert (
            await projections_service.list_orders(
                sess, default_tenant_id, customer_code="W3PROJ-NOPE-C"
            )
            == []
        )

        inventory = await projections_service.list_inventory_by_material_code(
            sess, default_tenant_id, MATERIAL_CODE
        )
        assert inventory is not None
        assert inventory.material.code == MATERIAL_CODE
        assert [row.warehouse for row in inventory.warehouses] == ["WH-01"]
        assert inventory.warehouses[0].quantity_available == Decimal(0)

        purchase_orders = await projections_service.list_purchase_orders(
            sess, default_tenant_id, material_code=MATERIAL_CODE, status="在途"
        )
        assert len(purchase_orders) == 1
        assert purchase_orders[0].po.po_no == PO_NO
        assert purchase_orders[0].supplier is not None
        assert purchase_orders[0].supplier.code == SUPPLIER_CODE

        bom = await projections_service.get_active_bom(
            sess, default_tenant_id, PRODUCT_CODE
        )
        assert bom is not None
        assert bom.product.code == PRODUCT_CODE
        assert bom.bom.version == "V3"
        assert len(bom.items) == 1
        assert bom.items[0].material is not None
        assert bom.items[0].material.code == MATERIAL_CODE
        assert bom.items[0].item.quantity == Decimal("2.5")

        lead_times = await projections_service.list_lead_times(
            sess, default_tenant_id, SUPPLIER_CODE
        )
        assert lead_times is not None
        assert lead_times.supplier.code == SUPPLIER_CODE
        assert len(lead_times.items) == 1
        assert lead_times.items[0].lead_time.lead_time_days == 10
        assert lead_times.items[0].material is not None
        assert lead_times.items[0].material.code == MATERIAL_CODE

        customer = await projections_service.get_customer_by_code(
            sess, default_tenant_id, CUSTOMER_CODE
        )
        assert customer is not None
        assert (customer.name, customer.level) == ("投影客户", "VIP")

        # 未命中 → None/[]
        assert (
            await projections_service.get_order_by_no(
                sess, default_tenant_id, "W3PROJ-NOPE"
            )
            is None
        )
        assert (
            await projections_service.get_active_bom(
                sess, default_tenant_id, "W3PROJ-NOPE"
            )
            is None
        )
        assert (
            await projections_service.list_lead_times(
                sess, default_tenant_id, "W3PROJ-NOPE"
            )
            is None
        )
        assert (
            await projections_service.list_inventory_by_material_code(
                sess, default_tenant_id, "W3PROJ-NOPE"
            )
            is None
        )
        assert (
            await projections_service.list_purchase_orders(
                sess, default_tenant_id, material_code="W3PROJ-NOPE"
            )
            == []
        )
        assert (
            await projections_service.get_customer_by_code(
                sess, default_tenant_id, "W3PROJ-NOPE"
            )
            is None
        )


# ---- 6. resolve 租户隔离：他租户同码对象不可见 ----


async def test_resolve_object_id_is_tenant_scoped(
    app_role_engine: AsyncEngine, db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    tenant_b = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO platform.tenants (tenant_id, slug, name, status)"
            " VALUES (:t, 'w3proj-tenant-b', '投影租户B', 'ACTIVE')"
        ),
        {"t": tenant_b},
    )
    b_object = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO master.business_objects"
            " (object_id, tenant_id, object_type, owner_domain, source_system, source_id)"
            " VALUES (:o, :t, 'CUSTOMER', 'master', 'erp', :sid)"
        ),
        {"o": b_object, "t": tenant_b, "sid": CUSTOMER_CODE},
    )
    await db_session.commit()

    async with _tenant_session(app_role_engine, default_tenant_id) as sess:
        assert (
            await projections_service.resolve_object_id(
                sess, default_tenant_id, "CUSTOMER", CUSTOMER_CODE
            )
            is None
        )

    async with _tenant_session(app_role_engine, tenant_b) as sess:
        assert (
            await projections_service.resolve_object_id(
                sess, tenant_b, "CUSTOMER", CUSTOMER_CODE
            )
            == b_object
        )
