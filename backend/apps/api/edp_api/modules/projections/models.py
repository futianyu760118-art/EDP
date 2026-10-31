"""projections ORM：领域快照表映射（表由迁移 0002/0004 建立；本模块为唯一持有者）。

约定同 registry/models.py：不声明 ForeignKey（跨 metadata 引用目标在别的模块
metadata 中，跨 metadata 声明会在 flush 排序时解析失败）、不参与迁移；列名与
DDL 逐字一致。

映射清单（14 张）：
    master(6):   customers / materials / products / suppliers / boms / bom_items
    sales(2):    orders / order_lines
    delivery(4): inventory / purchase_orders / supplier_lead_times / capacity
    rd(2):       projects / milestones
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DateTime, Integer, Numeric, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import quoted_name


class Base(DeclarativeBase):
    pass


class Customer(Base):
    """客户主数据（master.customers；自然键 = tenant_id + code）。"""

    __tablename__ = "customers"
    __table_args__ = {"schema": "master"}

    customer_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[str | None] = mapped_column(Text)
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class Material(Base):
    """物料主数据（master.materials；自然键 = tenant_id + code）。"""

    __tablename__ = "materials"
    __table_args__ = {"schema": "master"}

    material_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(Text)
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class Product(Base):
    """产品主数据（master.products；自然键 = tenant_id + code）。"""

    __tablename__ = "products"
    __table_args__ = {"schema": "master"}

    product_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class Supplier(Base):
    """供应商主数据（master.suppliers；自然键 = tenant_id + code）。"""

    __tablename__ = "suppliers"
    __table_args__ = {"schema": "master"}

    supplier_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class Bom(Base):
    """BOM 头（master.boms；唯一键 = tenant_id + product_id + version + status）。"""

    __tablename__ = "boms"
    __table_args__ = {"schema": "master"}

    bom_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    product_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class BomItem(Base):
    """BOM 行（master.bom_items；position 为 SQL 保留字，列名显式引号）。"""

    __tablename__ = "bom_items"
    __table_args__ = {"schema": "master"}

    item_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    bom_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    material_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    position: Mapped[int | None] = mapped_column(quoted_name("position", True), Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class SalesOrder(Base):
    """订单快照（sales.orders；order_id 即 master.business_objects.object_id）。"""

    __tablename__ = "orders"
    __table_args__ = {"schema": "sales"}

    order_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    order_no: Mapped[str] = mapped_column(Text, nullable=False)
    customer_id: Mapped[UUID | None] = mapped_column(Uuid)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="CNY")
    status: Mapped[str] = mapped_column(Text, nullable=False)
    order_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class SalesOrderLine(Base):
    """订单行（sales.order_lines；product_id/material_id 二选一或并存）。"""

    __tablename__ = "order_lines"
    __table_args__ = {"schema": "sales"}

    line_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    order_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    product_id: Mapped[UUID | None] = mapped_column(Uuid)
    material_id: Mapped[UUID | None] = mapped_column(Uuid)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class Inventory(Base):
    """库存快照（delivery.inventory；inv_id 即 master.business_objects.object_id）。"""

    __tablename__ = "inventory"
    __table_args__ = {"schema": "delivery"}

    inv_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    material_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    warehouse: Mapped[str | None] = mapped_column(Text)
    quantity_available: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=0
    )
    quantity_reserved: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=0
    )
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class PurchaseOrder(Base):
    """采购单快照（delivery.purchase_orders；po_id 即 business_objects.object_id）。"""

    __tablename__ = "purchase_orders"
    __table_args__ = {"schema": "delivery"}

    po_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    po_no: Mapped[str] = mapped_column(Text, nullable=False)
    supplier_id: Mapped[UUID | None] = mapped_column(Uuid)
    material_id: Mapped[UUID | None] = mapped_column(Uuid)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    expected_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class SupplierLeadTime(Base):
    """供应商交期（delivery.supplier_lead_times；updated_at 为业务列——
    交期刷新时间，故仅追加 created_at/created_by/updated_by 三个审计列）。"""

    __tablename__ = "supplier_lead_times"
    __table_args__ = {"schema": "delivery"}

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    supplier_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    material_id: Mapped[UUID | None] = mapped_column(Uuid)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class RdProject(Base):
    """研发项目快照（rd.projects；project_id 即 business_objects.object_id）。"""

    __tablename__ = "projects"
    __table_args__ = {"schema": "rd"}

    project_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    project_no: Mapped[str] = mapped_column(Text, nullable=False)
    product_id: Mapped[UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str | None] = mapped_column(Text)
    readiness_level: Mapped[str | None] = mapped_column(Text)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class RdMilestone(Base):
    """项目里程碑（rd.milestones；行明细随项目投影整组替换）。"""

    __tablename__ = "milestones"
    __table_args__ = {"schema": "rd"}

    milestone_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class Capacity(Base):
    """产能快照（delivery.capacity，MES 源；EDP-017 剩余）。

    行粒度 =（产线, 周期, 快照时刻）——uq_capacity 唯一索引；
    id=uuid5(object_id,"cap") 随对象稳定，重投影原地更新。
    """

    __tablename__ = "capacity"
    __table_args__ = {"schema": "delivery"}

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    product_line: Mapped[str] = mapped_column(Text, nullable=False)
    period: Mapped[str] = mapped_column(Text, nullable=False)
    capacity_qty: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)
