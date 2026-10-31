"""catalog 服务：系统/能力/技能注册（B.7，EDP-011）。

- 创建冲突（并发首插竞争）：uq_systems_name / uq_capability_name 唯一索引
  IntegrityError → 回滚、重新绑定租户（事务级 set_config 已随回滚失效）、
  409 CONFLICT（与 registry 模块 upsert 冲突路径同一手法）；
- skills 创建先校验 capability 存在（RLS 下跨租户与不存在同义）→
  400 VALIDATION_ERROR；
- PUT capabilities 局部更新：仅覆盖请求传入字段（exclude_unset），ORM 属性
  赋值（切面可捕获 UPDATE），RETIRED 可下线；
- 游标分页统一 created_at DESC + 主键 DESC tiebreak（锚 ``{"c","i"}``，
  非法 cursor 视为首页）。

RLS：platform.systems/capabilities/skills 均 FORCE RLS——会话由
tenant_scoped 预 bind_tenant；显式 tenant_id 条件双保险，跨租户读取恒表现
为"不存在"（详情 404 / 列表空）。

事务边界：本层只 flush 不 commit——请求级提交由 core.db.get_db 统一执行。
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import bind_tenant
from edp_api.core.errors import EdpError
from edp_api.core.pagination import decode_cursor, encode_cursor
from edp_api.core.security.principal import Principal
from edp_api.modules.catalog.models import Capability, Skill, System
from edp_api.modules.catalog.schemas import (
    CapabilityCreateRequest,
    CapabilityListItem,
    CapabilityUpdateRequest,
    SkillCreateRequest,
    SkillListItem,
    SystemCreateRequest,
    SystemListItem,
    SystemUpdateRequest,
)

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


async def _flush_unique(
    sess: AsyncSession, tenant_id: UUID, obj: System | Capability, message: str
) -> None:
    """唯一名 INSERT：并发首插竞争（唯一索引胜者已提交）→ 回滚重绑租户后
    409 CONFLICT；成功后 refresh 载入 server 默认（created_at/updated_at）。"""
    sess.add(obj)
    try:
        await sess.flush()
    except IntegrityError:
        await sess.rollback()
        await bind_tenant(sess, tenant_id)
        raise EdpError.conflict(message) from None
    await sess.refresh(obj)


# ---- systems ----


async def create_system(
    sess: AsyncSession, principal: Principal, req: SystemCreateRequest
) -> System:
    """注册系统（B.7）；同名（本租户 uq_systems_name）→ 409。

    T50：adapter_config 提供 → adapter_mode='real'（可装配真实适配器），
    缺省保持 'mock'。
    """
    system = System(
        system_id=uuid4(),
        tenant_id=principal.tenant_id,
        name=req.name,
        type=req.type,
        endpoint=req.endpoint,
        auth_config=req.auth_config,
        adapter_config=req.adapter_config,
        adapter_mode="real" if req.adapter_config else "mock",
        status="ACTIVE",
        created_by=principal.id,
        updated_by=principal.id,
    )
    await _flush_unique(sess, principal.tenant_id, system, f"同名系统已存在：{req.name}")
    return system


async def query_systems(
    sess: AsyncSession,
    *,
    status: str | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> tuple[list[SystemListItem], str | None]:
    """status 过滤 + 游标分页（分页语义见 _query_page）。"""
    conditions = [System.status == status] if status else []
    rows, next_cursor = await _query_page(
        sess, System, "system_id", conditions=conditions, limit=limit, cursor=cursor
    )
    return [SystemListItem.model_validate(row) for row in rows], next_cursor


async def get_system(sess: AsyncSession, system_id: UUID) -> System | None:
    """系统详情（RLS 会话：跨租户行不可见 → None，语义 404）。"""
    return (
        await sess.execute(select(System).where(System.system_id == system_id))
    ).scalar_one_or_none()


async def get_system_by_name(sess: AsyncSession, name: str) -> System | None:
    """按名查系统（RLS 会话仅见本租户行；uq_systems_name 本租户唯一）。"""
    return (
        await sess.execute(select(System).where(System.name == name))
    ).scalar_one_or_none()


async def update_system(
    sess: AsyncSession, principal: Principal, system: System, req: SystemUpdateRequest
) -> System:
    """局部更新（T50）：仅覆盖传入字段；adapter_config 变更同步
    adapter_mode（None 清空 → 回 mock；提供 → real）。"""
    if req.type is not None:
        system.type = req.type
    if req.endpoint is not None:
        system.endpoint = req.endpoint
    if req.auth_config is not None:
        system.auth_config = req.auth_config
    if "adapter_config" in req.model_fields_set:
        system.adapter_config = req.adapter_config
        system.adapter_mode = "real" if req.adapter_config else "mock"
    if req.status is not None:
        system.status = req.status
    system.updated_by = principal.id
    system.updated_at = datetime.now(UTC)  # 值赋值（func.now() 会触发 async 懒加载）
    await sess.flush()
    return system


async def delete_system(sess: AsyncSession, system: System) -> None:
    """删除系统行（调用方随后触发适配器注册表重载）。"""
    await sess.delete(system)
    await sess.flush()


# ---- capabilities ----


async def create_capability(
    sess: AsyncSession, principal: Principal, req: CapabilityCreateRequest
) -> Capability:
    """注册能力（B.7；status 落 DDL 默认 ACTIVE）；同名 → 409。"""
    capability = Capability(
        capability_id=uuid4(),
        tenant_id=principal.tenant_id,
        name=req.name,
        domain=req.domain,
        input_schema=req.input_schema,
        output_schema=req.output_schema,
        risk_level=req.risk_level,
        permission=req.permission,
        endpoint=req.endpoint,
        owner=req.owner,
        status="ACTIVE",
        created_by=principal.id,
        updated_by=principal.id,
    )
    await _flush_unique(
        sess, principal.tenant_id, capability, f"同名能力已存在：{req.name}"
    )
    return capability


async def query_capabilities(
    sess: AsyncSession,
    *,
    domain: str | None = None,
    status: str | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> tuple[list[CapabilityListItem], str | None]:
    """domain/status 过滤 + 游标分页（简投影，不含 input/output_schema）。"""
    conditions = []
    if domain:
        conditions.append(Capability.domain == domain)
    if status:
        conditions.append(Capability.status == status)
    rows, next_cursor = await _query_page(
        sess,
        Capability,
        "capability_id",
        conditions=conditions,
        limit=limit,
        cursor=cursor,
    )
    return [CapabilityListItem.model_validate(row) for row in rows], next_cursor


async def get_capability(
    sess: AsyncSession, capability_id: UUID
) -> Capability | None:
    """按 capability_id 点查；RLS 下跨租户 = 不存在（None）。"""
    return await sess.get(Capability, capability_id)


async def update_capability(
    sess: AsyncSession,
    principal: Principal,
    capability_id: UUID,
    req: CapabilityUpdateRequest,
) -> Capability | None:
    """局部更新（B.7 PUT 语义）：仅覆盖请求传入字段
    （endpoint/input_schema/output_schema/status，RETIRED 可下线）；
    ORM 属性赋值使审计切面可见。

    Returns:
        更新后完整能力对象；capability_id 不存在（含跨租户）→ None。
    """
    capability = await sess.get(Capability, capability_id)
    if capability is None:
        return None
    changes = req.model_dump(exclude_unset=True)
    if changes:
        for field, value in changes.items():
            setattr(capability, field, value)
        capability.updated_by = principal.id
        capability.updated_at = func.now()
        await sess.flush()
        await sess.refresh(capability)
    return capability


# ---- skills ----


async def create_skill(
    sess: AsyncSession, principal: Principal, req: SkillCreateRequest
) -> Skill:
    """注册技能（B.7）；capability 不存在（含跨租户）→ 400 VALIDATION_ERROR。"""
    if await sess.get(Capability, req.capability_id) is None:
        raise EdpError.validation_error(f"capability_id 不存在：{req.capability_id}")
    skill = Skill(
        skill_id=uuid4(),
        tenant_id=principal.tenant_id,
        capability_id=req.capability_id,
        prompt=req.prompt,
        model_version=req.model_version,
        status=req.status,
        created_by=principal.id,
        updated_by=principal.id,
    )
    sess.add(skill)
    await sess.flush()
    await sess.refresh(skill)
    return skill


async def query_skills(
    sess: AsyncSession,
    *,
    capability_id: UUID | None = None,
    status: str | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> tuple[list[SkillListItem], str | None]:
    """capability_id/status 过滤 + 游标分页。"""
    conditions = []
    if capability_id:
        conditions.append(Skill.capability_id == capability_id)
    if status:
        conditions.append(Skill.status == status)
    rows, next_cursor = await _query_page(
        sess, Skill, "skill_id", conditions=conditions, limit=limit, cursor=cursor
    )
    return [SkillListItem.model_validate(row) for row in rows], next_cursor


# ---- 共用分页 ----


async def _query_page(
    sess: AsyncSession,
    model: type[System | Capability | Skill],
    pk_attr: str,
    *,
    conditions: list,
    limit: int,
    cursor: str | None,
) -> tuple[list, str | None]:
    """created_at DESC + 主键 DESC tiebreak 游标分页（锚 ``{"c","i"}``）；
    取 limit+1 探测下一页。"""
    limit = max(1, min(limit, MAX_LIMIT))
    pk = getattr(model, pk_attr)
    stmt = select(model).where(*conditions)

    decoded = decode_cursor(cursor)
    if decoded is not None:
        anchor = _parse_anchor(decoded)
        if anchor is not None:
            created_at, anchor_pk = anchor
            stmt = stmt.where(
                or_(
                    model.created_at < created_at,
                    and_(model.created_at == created_at, pk < anchor_pk),
                )
            )

    stmt = stmt.order_by(model.created_at.desc(), pk.desc()).limit(limit + 1)
    rows = (await sess.execute(stmt)).scalars().all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"c": last.created_at.isoformat(), "i": str(getattr(last, pk_attr))}
        )
    return page_rows, next_cursor


def _parse_anchor(decoded: dict) -> tuple[datetime, UUID] | None:
    """cursor 载荷 → (created_at, 主键)；缺字段/格式非法 → None。"""
    try:
        return datetime.fromisoformat(str(decoded["c"])), UUID(str(decoded["i"]))
    except (KeyError, TypeError, ValueError):
        return None
