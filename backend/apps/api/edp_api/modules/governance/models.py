"""governance ORM 映射（V1.2 0014 迁移 10 表）。

DDL 单一事实来源 = 迁移链（0014_v12_governance_baseline）；ORM 不参与
迁移、不声明跨表 ForeignKey（沿袭各模块约定）。全表 FORCE RLS——
调用方会话需 bind_tenant（tenant_scoped 依赖已处理）。
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Integer, Numeric, Text, Uuid, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RawRecord(Base):
    """RAW 层源记录（先留存后处理；同源重放经唯一键幂等不重复落数）。"""

    __tablename__ = "raw_records"
    __table_args__ = {"schema": "governance"}

    raw_record_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    source_system: Mapped[str] = mapped_column(Text, nullable=False)
    source_record_id: Mapped[str] = mapped_column(Text, nullable=False)
    object_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    batch_id: Mapped[str | None] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CleanRecord(Base):
    """CLEAN 留痕（fixAudit）：before/after + 规则引用，不得覆盖 RAW。"""

    __tablename__ = "clean_records"
    __table_args__ = {"schema": "governance"}

    clean_record_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    object_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    raw_record_id: Mapped[UUID | None] = mapped_column(Uuid)
    before: Mapped[dict] = mapped_column(JSONB, nullable=False)
    after: Mapped[dict] = mapped_column(JSONB, nullable=False)
    rule_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CleaningRule(Base):
    """清洗规则注册表（契约 cleaning-rule.schema.json；版本化生效区间）。"""

    __tablename__ = "cleaning_rules"
    __table_args__ = {"schema": "governance"}

    rule_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    rule_name: Mapped[str] = mapped_column(Text, nullable=False)
    object_type: Mapped[str] = mapped_column(Text, nullable=False)
    field: Mapped[str | None] = mapped_column(Text)
    rule_type: Mapped[str] = mapped_column(Text, nullable=False)
    condition: Mapped[str | None] = mapped_column(Text)
    transformation: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    severity: Mapped[str] = mapped_column(Text, nullable=False, default="WARN")
    owner: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auto_fix: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class EntityAlias(Base):
    """实体解析别名（别名保留，canonical 归一到业务对象）。"""

    __tablename__ = "entity_aliases"
    __table_args__ = {"schema": "governance"}

    alias_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    object_type: Mapped[str] = mapped_column(Text, nullable=False)
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_ref: Mapped[UUID | None] = mapped_column(Uuid)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="HUMAN_MAINTAINED")
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4))
    approved_by: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class Dimension(Base):
    """多维分类维度（code 租户内唯一）。"""

    __tablename__ = "dimensions"
    __table_args__ = {"schema": "governance"}

    dimension_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class Taxonomy(Base):
    """分类树节点（parent 自引用）。"""

    __tablename__ = "taxonomies"
    __table_args__ = {"schema": "governance"}

    taxonomy_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    dimension_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(Uuid)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class Tag(Base):
    """动态标签（code 租户内唯一）。"""

    __tablename__ = "tags"
    __table_args__ = {"schema": "governance"}

    tag_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class ObjectClassification(Base):
    """对象分类挂接（契约 classification.schema.json；版本化）。"""

    __tablename__ = "object_classifications"
    __table_args__ = {"schema": "governance"}

    classification_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    object_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    dimension_id: Mapped[UUID | None] = mapped_column(Uuid)
    taxonomy_id: Mapped[UUID | None] = mapped_column(Uuid)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="HUMAN_MAINTAINED")
    rule_ref: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class AdmissionRecord(Base):
    """A1–A4 准入状态机（15 态；一对象一租户一条，重审 version+1）。"""

    __tablename__ = "admission_records"
    __table_args__ = {"schema": "governance"}

    admission_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    object_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, default="RECEIVED")
    review_result: Mapped[str | None] = mapped_column(Text)
    quality_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    machine_result: Mapped[dict | None] = mapped_column(JSONB)
    source_human_reviewer: Mapped[str | None] = mapped_column(Text)
    source_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    management_human_reviewer: Mapped[str | None] = mapped_column(Text)
    management_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_version: Mapped[str | None] = mapped_column(Text)
    clean_version: Mapped[str | None] = mapped_column(Text)
    standard_version: Mapped[str | None] = mapped_column(Text)
    classification_version: Mapped[str | None] = mapped_column(Text)
    dimensions: Mapped[dict | None] = mapped_column(JSONB)
    classifications: Mapped[dict | None] = mapped_column(JSONB)
    tags: Mapped[dict | None] = mapped_column(JSONB)
    evidence_refs: Mapped[list] = mapped_column(ARRAY(Uuid), nullable=False, default=list)
    checksum: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class ObjectTag(Base):
    """对象标签挂接（0017；(tenant, object, tag) 唯一；search_objects 前置）。"""

    __tablename__ = "object_tags"
    __table_args__ = {"schema": "governance"}

    object_tag_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    object_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    tag_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)


class ReviewRecord(Base):
    """A2/A3 审核留痕（人工决策六结果 + 机器检查输出）。"""

    __tablename__ = "review_records"
    __table_args__ = {"schema": "governance"}

    review_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    admission_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    machine_result: Mapped[dict | None] = mapped_column(JSONB)
    human_decision: Mapped[str] = mapped_column(Text, nullable=False)
    human_reviewer: Mapped[str] = mapped_column(Text, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    evidence_refs: Mapped[list] = mapped_column(ARRAY(Uuid), nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
