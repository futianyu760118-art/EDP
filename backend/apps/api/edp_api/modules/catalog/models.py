"""catalog ORM 映射：platform.systems / capabilities / skills（迁移 0001 建立）。

沿袭既有约定：ORM 不参与迁移（DDL 单一事实来源 = 迁移链）；列不声明
ForeignKey（跨表外键以迁移 DDL 为准）；列名与 DDL 逐字一致。

**platform.systems 与 ingest 水位共表**——catalog 管注册字段（type/
endpoint/auth_config/status），ingest 管 ``last_watermark``/``adapter_mode``
（modules/ingest 自持同名表映射，互不干扰，按需映射先例见 tenantmgmt/
models.py）；故本 System 只声明注册字段 + 审计列，不映射水位两列
（INSERT 落 DDL 默认 adapter_mode='mock' / last_watermark=NULL）。
capabilities/skills 为 catalog 独占映射。
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class System(Base):
    """系统注册行（platform.systems；uq_systems_name = (tenant_id, name)；
    FORCE RLS——会话需 bind_tenant）。字段分工见模块 docstring。"""

    __tablename__ = "systems"
    __table_args__ = {"schema": "platform"}

    system_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint: Mapped[str | None] = mapped_column(Text)
    auth_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # 0019（V1.3 T50）：驱动配置（DB 拉取 dsn/tables）；非空 = 可装配真实适配器
    adapter_config: Mapped[dict | None] = mapped_column(JSONB)
    # 0019 起由 catalog 显式写入：有 adapter_config → 'real'，否则 'mock'
    # （DDL 默认 'mock'；ingest 侧同名映射互不干扰）
    adapter_mode: Mapped[str] = mapped_column(Text, nullable=False, default="mock")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class Capability(Base):
    """能力注册行（platform.capabilities；uq_capability_name = (tenant_id,
    name)；status DRAFT/ACTIVE/RETIRED、risk_level L0~L3、permission 三态由
    DDL CHECK 约束；FORCE RLS）。"""

    __tablename__ = "capabilities"
    __table_args__ = {"schema": "platform"}

    capability_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(Text, nullable=False)
    input_schema: Mapped[dict] = mapped_column(JSONB, nullable=False)
    output_schema: Mapped[dict] = mapped_column(JSONB, nullable=False)
    risk_level: Mapped[str] = mapped_column(Text, nullable=False)
    permission: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)


class Skill(Base):
    """技能注册行（platform.skills；capability_id 引用 capabilities
    （FK 见 DDL，ORM 不声明）；idx_skills_capability 支撑按能力过滤；
    FORCE RLS）。"""

    __tablename__ = "skills"
    __table_args__ = {"schema": "platform"}

    skill_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    capability_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(Text)
