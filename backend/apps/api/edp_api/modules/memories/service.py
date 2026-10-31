"""memories 服务：候选创建 / 过滤查询 / Human-Only 评审（B.11，EDP-014）。

- create_memory：capability_id 非空时校验存在（经 catalog.service，RLS 下
  跨租户与不存在同义）→ 400 VALIDATION_ERROR；
- query_memories：status/capability_id 过滤 + 游标分页（created_at DESC,
  memory_id DESC tiebreak，锚 ``{"c","i"}``，非法 cursor 视为首页）；
- review_memory：**Human-Only**——非 HUMAN 经 ``record_guard_denied``
  （独立会话提交）落 GUARD_DENIED 审计后由依赖层抛 403
  GUARD_POLICY_DENIED；HUMAN 需 ``memory:review``；非 CANDIDATE（已评审）
  → 409 CONFLICT；成功同事务写 reviewed_by/reviewed_at/review_comment。

拒绝审计走独立会话（与 tools/decisions 同一模式）：请求随后抛 403，请求
事务回滚，审计不能依赖请求会话；审计失败仅 warning，不改变 403 决策。

RLS：memory.memories FORCE RLS——会话由 tenant_scoped 预 bind_tenant；
跨租户 memory_id 与不存在同义（404 不泄露存在性）。

事务边界：本层只 flush 不 commit——请求级提交由 core.db.get_db 统一执行。
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core import db as core_db
from edp_api.core.db import bind_tenant
from edp_api.core.errors import EdpError
from edp_api.core.pagination import decode_cursor, encode_cursor
from edp_api.core.security.principal import Principal
from edp_api.modules.audit import service as audit_service
from edp_api.modules.catalog import service as catalog_service
from edp_api.modules.memories.models import Memory
from edp_api.modules.memories.schemas import (
    MemoryCreateRequest,
    MemoryListItem,
    MemoryReviewRequest,
)

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

GUARD_DENIED_ACTION = "GUARD_DENIED"
GUARD_DENIED_RESOURCE_TYPE = "memory.memories"
HUMAN_ONLY_REASON = "Human-Only"
HUMAN_ONLY_MESSAGE = "该操作仅限人工执行"


async def record_guard_denied(
    principal: Principal,
    *,
    path: str | None,
    reason: str,
    resource_id: str | None,
) -> None:
    """独立会话落 GUARD_DENIED 审计（Human-Only 拒绝路径唯一实现）。

    拒绝必然伴随控制流抛出（HTTP 请求会话 / 直接 service 调用），审计不能
    依赖调用方事务——独立会话与业务事务解耦保证拒绝留痕（审计失败仅
    warning，不改变 403 决策）。依赖层（require_memory_review）与直接调用
    服务层共用本函数。
    """
    try:
        session = core_db.get_session_local()()
        try:
            await bind_tenant(session, principal.tenant_id)
            await audit_service.record_explicit(
                session,
                action=GUARD_DENIED_ACTION,
                resource_type=GUARD_DENIED_RESOURCE_TYPE,
                resource_id=resource_id,
                detail={
                    "path": path,
                    "reason": reason,
                    "scopes": list(principal.scopes),
                },
                principal=principal,
            )
            await session.commit()
        finally:
            await session.close()
    except Exception:
        logger.warning("GUARD_DENIED 审计写入失败", exc_info=True)


async def create_memory(
    sess: AsyncSession, principal: Principal, req: MemoryCreateRequest
) -> Memory:
    """创建记忆候选（B.11）→ CANDIDATE；capability 不存在（含跨租户）→ 400。"""
    if req.capability_id is not None and (
        await catalog_service.get_capability(sess, req.capability_id) is None
    ):
        raise EdpError.validation_error(
            f"capability_id 不存在：{req.capability_id}"
        )
    memory = Memory(
        memory_id=uuid4(),
        tenant_id=principal.tenant_id,
        capability_id=req.capability_id,
        source_type=req.source_type,
        source_id=req.source_id,
        content=req.content,
        status="CANDIDATE",
        created_by=principal.id,
        updated_by=principal.id,
    )
    sess.add(memory)
    await sess.flush()
    await sess.refresh(memory)
    return memory


async def query_memories(
    sess: AsyncSession,
    *,
    status: str | None = None,
    capability_id: UUID | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> tuple[list[MemoryListItem], str | None]:
    """status/capability_id 过滤 + 游标分页（分页语义见 _query_page）。"""
    conditions = []
    if status:
        conditions.append(Memory.status == status)
    if capability_id:
        conditions.append(Memory.capability_id == capability_id)
    rows, next_cursor = await _query_page(
        sess, conditions=conditions, limit=limit, cursor=cursor
    )
    return [MemoryListItem.model_validate(row) for row in rows], next_cursor


async def get_memory(sess: AsyncSession, memory_id: UUID) -> Memory | None:
    """按 memory_id 点查；RLS 下跨租户 = 不存在（None）。"""
    return await sess.get(Memory, memory_id)


async def review_memory(
    sess: AsyncSession,
    principal: Principal,
    memory_id: UUID,
    req: MemoryReviewRequest,
) -> Memory | None:
    """人工评审（Human-Only 由依赖层把关）：写 reviewed_* + status。

    Returns:
        评审后记忆对象；memory_id 不存在（含跨租户）→ None。

    Raises:
        EdpError(CONFLICT): 已评审（status != CANDIDATE）。
    """
    memory = await sess.get(Memory, memory_id)
    if memory is None:
        return None
    if memory.status != "CANDIDATE":
        raise EdpError.conflict(f"记忆已评审：{memory.status}")
    memory.status = req.status
    memory.reviewed_by = principal.id
    memory.reviewed_at = func.now()
    memory.review_comment = req.comment
    memory.updated_by = principal.id
    memory.updated_at = func.now()
    await sess.flush()
    await sess.refresh(memory)
    return memory


# ---- 共用分页 ----


async def _query_page(
    sess: AsyncSession,
    *,
    conditions: list,
    limit: int,
    cursor: str | None,
) -> tuple[list[Memory], str | None]:
    """created_at DESC + memory_id DESC tiebreak 游标分页（锚 ``{"c","i"}``）；
    取 limit+1 探测下一页。"""
    limit = max(1, min(limit, MAX_LIMIT))
    stmt = select(Memory).where(*conditions)

    decoded = decode_cursor(cursor)
    if decoded is not None:
        anchor = _parse_anchor(decoded)
        if anchor is not None:
            created_at, anchor_pk = anchor
            stmt = stmt.where(
                or_(
                    Memory.created_at < created_at,
                    and_(
                        Memory.created_at == created_at,
                        Memory.memory_id < anchor_pk,
                    ),
                )
            )

    stmt = stmt.order_by(Memory.created_at.desc(), Memory.memory_id.desc()).limit(
        limit + 1
    )
    rows = (await sess.execute(stmt)).scalars().all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"c": last.created_at.isoformat(), "i": str(last.memory_id)}
        )
    return page_rows, next_cursor


def _parse_anchor(decoded: dict) -> tuple[datetime, UUID] | None:
    """cursor 载荷 → (created_at, memory_id)；缺字段/格式非法 → None。"""
    try:
        return datetime.fromisoformat(str(decoded["c"])), UUID(str(decoded["i"]))
    except (KeyError, TypeError, ValueError):
        return None
