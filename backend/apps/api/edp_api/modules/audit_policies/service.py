"""audit_policies 服务：策略 CRUD + ACTIVE 策略进程内缓存 + 三维命中匹配
（EDP-032 最小版）。

- create：租户内重名（uq_audit_policy_name）→ 409 CONFLICT
  （IntegrityError 经回滚重绑租户，catalog._flush_unique 同一手法）；
- query：status 过滤 + 游标分页（created_at DESC, policy_id DESC
  tiebreak，锚 ``{"c","i"}``，非法 cursor 视为首页）；
- update：局部更新（exclude_unset；name 不可改由 schemas 层约束），
  ORM 属性赋值使审计切面可见；
- delete/get：RLS 下跨租户 = 不存在（None → 路由 404）；
- active_policies/matching：**进程内缓存** ``_ACTIVE_POLICIES``
  （tenant_id → ACTIVE 策略投影），本模块写路径（create/update/delete）
  flush 后 ``_invalidate(tenant_id)``；缓存未命中且有 sync_session 时
  惰性加载（同请求读 DB）并回填。

**单副本语义（W3-41 同类）**：缓存为模块级 dict，仅本进程可见——多副本/
多 worker 部署下写路径失效不同步，需外置（Redis 等，W5+ 评估）；单副本
（dev / 单 api pod）语义正确，多副本前外置。

matching 三维全匹配才命中（空数组=通配）：
- resource 维（``_resource_hit``）：切面传入 fullname（schema.table，如
  decision.records）或裸表名（如 records）皆可——策略项 fullname 精确 /
  裸名精确 / ``{prefix}_*`` 前缀通配任一命中即算；fullname 项与 fullname
  事件精确比对（不同 schema 同裸名不互配：evidence.records ≠
  decision.records），裸名项按尾段回退匹配 fullname 事件；
- action 维（``_action_hit``）：精确或 ``{PREFIX}_*`` 后缀通配（保留
  下划线按前缀匹配，如 ACTION_* 命中 ACTION_CREATE）；
- actor 维（``_actor_hit``）：HUMAN/AI/SERVICE 精确。

惰性加载在审计切面 before_flush 内同步 SELECT（flush 过程中 autoflush
关闭，无递归）；匹配调用方（aspect）以 try/except 包裹，异常不影响
审计写入。

RLS：audit.policies FORCE RLS——会话由 tenant_scoped 预 bind_tenant；
惰性加载与业务写同租户视图。

事务边界：本层只 flush 不 commit——请求级提交由 core.db.get_db 统一执行
（create 的 409 路径例外：回滚重绑，与 catalog 一致）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from edp_api.core.db import bind_tenant
from edp_api.core.errors import EdpError
from edp_api.core.pagination import Page, decode_cursor, encode_cursor
from edp_api.core.security.principal import Principal
from edp_api.modules.audit_policies.models import AuditPolicy
from edp_api.modules.audit_policies.schemas import (
    PolicyCreateRequest,
    PolicyItem,
    PolicyUpdateRequest,
)

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

WILDCARD_SUFFIX = "_*"


@dataclass(frozen=True)
class ActivePolicy:
    """ACTIVE 策略匹配投影（缓存值对象；仅保留命中判定所需四列）。"""

    policy_id: UUID
    resource_types: tuple[str, ...]
    actions: tuple[str, ...]
    actor_types: tuple[str, ...]


# 进程内 ACTIVE 策略缓存（单副本语义：见模块 docstring）
_ACTIVE_POLICIES: dict[UUID, list[ActivePolicy]] = {}


def _invalidate(tenant_id: UUID) -> None:
    """写路径缓存失效（本模块 create/update/delete 调用；单副本语义）。"""
    _ACTIVE_POLICIES.pop(tenant_id, None)


# ---- CRUD ----


async def create_policy(
    sess: AsyncSession, principal: Principal, req: PolicyCreateRequest
) -> AuditPolicy:
    """创建策略（→ ACTIVE）；租户内重名 → 409 CONFLICT。"""
    policy = AuditPolicy(
        policy_id=uuid4(),
        tenant_id=principal.tenant_id,
        name=req.name,
        description=req.description,
        resource_types=list(req.resource_types),
        actions=list(req.actions),
        actor_types=list(req.actor_types),
        notify_channel=req.notify_channel,
        status="ACTIVE",
        created_by=principal.id,
        updated_by=principal.id,
    )
    sess.add(policy)
    try:
        await sess.flush()
    except IntegrityError:
        await sess.rollback()
        await bind_tenant(sess, principal.tenant_id)
        raise EdpError.conflict(f"同名策略已存在：{req.name}") from None
    await sess.refresh(policy)  # 载入 server 默认（created_at/updated_at）
    _invalidate(principal.tenant_id)
    return policy


async def query_policies(
    sess: AsyncSession,
    *,
    status: str | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[PolicyItem]:
    """status 过滤 + 游标分页（created_at DESC, policy_id DESC tiebreak）；
    非法 cursor 视为首页。"""
    limit = max(1, min(limit, MAX_LIMIT))
    stmt = select(AuditPolicy)
    if status:
        stmt = stmt.where(AuditPolicy.status == status)

    decoded = decode_cursor(cursor)
    if decoded is not None:
        anchor = _parse_anchor(decoded)
        if anchor is not None:
            created_at, policy_id_anchor = anchor
            stmt = stmt.where(
                or_(
                    AuditPolicy.created_at < created_at,
                    and_(
                        AuditPolicy.created_at == created_at,
                        AuditPolicy.policy_id < policy_id_anchor,
                    ),
                )
            )
    stmt = stmt.order_by(
        AuditPolicy.created_at.desc(), AuditPolicy.policy_id.desc()
    ).limit(limit + 1)
    rows = (await sess.execute(stmt)).scalars().all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"c": last.created_at.isoformat(), "i": str(last.policy_id)}
        )
    return Page(
        items=[PolicyItem.model_validate(row) for row in page_rows],
        next_cursor=next_cursor,
    )


async def get_policy(sess: AsyncSession, policy_id: UUID) -> AuditPolicy | None:
    """按 policy_id 点查；RLS 下跨租户 = 不存在（None）。"""
    return await sess.get(AuditPolicy, policy_id)


async def update_policy(
    sess: AsyncSession,
    principal: Principal,
    policy_id: UUID,
    req: PolicyUpdateRequest,
) -> AuditPolicy | None:
    """局部更新（exclude_unset：description/resource_types/actions/
    actor_types/notify_channel/status；name 不可改）；启停经 status。

    Returns:
        更新后完整策略对象；policy_id 不存在（含跨租户）→ None。
    """
    policy = await sess.get(AuditPolicy, policy_id)
    if policy is None:
        return None
    changes = req.model_dump(exclude_unset=True)
    if changes:
        for field, value in changes.items():
            setattr(policy, field, value)
        policy.updated_by = principal.id
        policy.updated_at = func.now()
        await sess.flush()
        await sess.refresh(policy)
    _invalidate(policy.tenant_id)
    return policy


async def delete_policy(sess: AsyncSession, policy_id: UUID) -> bool:
    """删除策略（ORM delete 使审计切面可见）。

    Returns:
        是否删除；policy_id 不存在（含跨租户）→ False。
    """
    policy = await sess.get(AuditPolicy, policy_id)
    if policy is None:
        return False
    tenant_id = policy.tenant_id
    await sess.delete(policy)
    await sess.flush()
    _invalidate(tenant_id)
    return True


# ---- 命中打标（供审计切面调用） ----


def active_policies(
    tenant_id: UUID, *, sync_session: Session | None = None
) -> list[ActivePolicy]:
    """租户 ACTIVE 策略投影（进程内缓存优先；未命中且有 sync_session 时
    惰性加载并回填——同请求读 DB）。

    单副本语义（W3-41 同类）：缓存仅本进程可见，多副本部署写路径失效
    不同步，需外置（W5+ 评估）；惰性加载在审计切面 before_flush 内同步
    SELECT（flush 过程中 autoflush 关闭，无递归）。
    """
    cached = _ACTIVE_POLICIES.get(tenant_id)
    if cached is not None:
        return cached
    if sync_session is None:
        return []
    rows = (
        sync_session.execute(
            select(AuditPolicy).where(
                AuditPolicy.tenant_id == tenant_id,
                AuditPolicy.status == "ACTIVE",
            )
        )
        .scalars()
        .all()
    )
    projections = [
        ActivePolicy(
            policy_id=row.policy_id,
            resource_types=tuple(row.resource_types or []),
            actions=tuple(row.actions or []),
            actor_types=tuple(row.actor_types or []),
        )
        for row in rows
    ]
    _ACTIVE_POLICIES[tenant_id] = projections
    return projections


def matching(
    tenant_id: UUID,
    *,
    resource_type: str,
    action: str,
    actor_type: str,
    sync_session: Session | None = None,
) -> list[UUID]:
    """三维命中匹配（供审计切面打标）：ACTIVE 策略三维全匹配才命中，
    空数组=通配（维度语义见模块 docstring）；resource 维 fullname/裸名
    两形态在 ``_resource_hit`` 内归一处理。

    Returns:
        命中策略 policy_id 列表（升序稳定）。
    """
    hits = [
        projection.policy_id
        for projection in active_policies(tenant_id, sync_session=sync_session)
        if _resource_hit(projection.resource_types, resource_type)
        and _action_hit(projection.actions, action)
        and _actor_hit(projection.actor_types, actor_type)
    ]
    return sorted(hits)


def _resource_hit(items: tuple[str, ...], resource_type: str) -> bool:
    """resource 维：空数组=通配；fullname 精确 / 裸名精确 / ``{prefix}_*``
    前缀通配任一命中即算。

    fullname 项（含 "."）与裸名事件比对尾段（record_explicit 等裸名形态）；
    fullname 事件与 fullname 项精确比对（不同 schema 同裸名不互配）；
    ``{prefix}_*`` 项按前缀匹配两形态（'decision_*' 覆盖 'decision.records'
    与 'decision_records' 形态）。
    """
    if not items:
        return True
    bare = resource_type.rsplit(".", 1)[-1]
    for item in items:
        if item == resource_type or item == bare:
            return True
        if item.endswith(WILDCARD_SUFFIX):
            stem = item[: -len(WILDCARD_SUFFIX)]
            if (
                resource_type.startswith(f"{stem}.")
                or resource_type.startswith(f"{stem}_")
                or bare.startswith(f"{stem}_")
                or bare == stem
            ):
                return True
        elif "." in item and item.rsplit(".", 1)[-1] == resource_type:
            return True
    return False


def _action_hit(items: tuple[str, ...], action: str) -> bool:
    """action 维：空数组=通配；精确或 ``{PREFIX}_*`` 后缀通配（保留下划线
    按前缀匹配：'ACTION_*' → startswith('ACTION_')）。"""
    if not items:
        return True
    for item in items:
        if item == action:
            return True
        if item.endswith(WILDCARD_SUFFIX) and action.startswith(item[:-1]):
            return True
    return False


def _actor_hit(items: tuple[str, ...], actor_type: str) -> bool:
    """actor 维：空数组=通配（HUMAN/AI/SERVICE）。"""
    return not items or actor_type in items


def _parse_anchor(decoded: dict) -> tuple[datetime, UUID] | None:
    """cursor 载荷 → (created_at, policy_id)；缺字段/格式非法 → None。"""
    try:
        return datetime.fromisoformat(str(decoded["c"])), UUID(str(decoded["i"]))
    except (KeyError, TypeError, ValueError):
        return None
