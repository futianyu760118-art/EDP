"""value 服务（V1.2 T25）：价值账本基础版（复用 metric 权限轨道）。

- create：改善前后价值事实（delta 未传时按 after-before 派生）；
- verify：Human-Only 人工核验（verified_by/verified_at）；
- evidence_refs 为引用数组（校验证据存在性）；links 机制不加 VALUE ref_type
  （证据 links 枚举维持六值，记偏差）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core import db as core_db
from edp_api.core.db import bind_tenant
from edp_api.core.errors import EdpError
from edp_api.core.pagination import Page, decode_cursor, encode_cursor
from edp_api.core.security.principal import Principal
from edp_api.modules.audit import service as audit_service
from edp_api.modules.value.models import ValueLedger
from edp_api.modules.value.schemas import ValueLedgerCreate

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
GUARD_DENIED_RESOURCE_TYPE = "value.value_ledger"


async def create_entry(
    sess: AsyncSession, principal: Principal, req: ValueLedgerCreate
) -> ValueLedger:
    """创建价值事实；evidence_refs 逐条校验存在（不可见 → 400）。"""
    for evidence_id in dict.fromkeys(req.evidence_refs):
        hit = (
            await sess.execute(
                text("SELECT 1 FROM evidence.records WHERE evidence_id = :e"),
                {"e": evidence_id},
            )
        ).scalar_one_or_none()
        if hit is None:
            raise EdpError.validation_error(f"evidence_id 不存在：{evidence_id}")
    delta = req.delta
    if delta is None and req.before_value is not None and req.after_value is not None:
        delta = round(req.after_value - req.before_value, 4)
    entry = ValueLedger(
        value_id=uuid4(),
        tenant_id=principal.tenant_id,
        baseline_ref=req.baseline_ref,
        initiative_ref=req.initiative_ref,
        metric_ref=req.metric_ref,
        before_value=req.before_value,
        after_value=req.after_value,
        delta=delta,
        financial_value=req.financial_value,
        evidence_refs=list(dict.fromkeys(req.evidence_refs)),
        created_by=principal.id,
        updated_by=principal.id,
    )
    sess.add(entry)
    await sess.flush()
    return entry


async def get_entry(sess: AsyncSession, value_id: UUID) -> ValueLedger | None:
    return (
        await sess.execute(select(ValueLedger).where(ValueLedger.value_id == value_id))
    ).scalar_one_or_none()


async def query_entries(
    sess: AsyncSession,
    *,
    metric_ref: str | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[ValueLedger]:
    limit = max(1, min(limit, MAX_LIMIT))
    stmt = select(ValueLedger)
    if metric_ref:
        stmt = stmt.where(ValueLedger.metric_ref == metric_ref)
    decoded = decode_cursor(cursor)
    if decoded is not None:
        try:
            anchor_created = datetime.fromisoformat(str(decoded["c"]))
            anchor_id = UUID(str(decoded["i"]))
            stmt = stmt.where(
                or_(
                    ValueLedger.created_at < anchor_created,
                    and_(
                        ValueLedger.created_at == anchor_created,
                        ValueLedger.value_id < anchor_id,
                    ),
                )
            )
        except (KeyError, TypeError, ValueError):
            pass
    stmt = stmt.order_by(ValueLedger.created_at.desc(), ValueLedger.value_id.desc()).limit(
        limit + 1
    )
    rows = (await sess.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"c": last.created_at.isoformat(), "i": str(last.value_id)}
        )
    return Page(items=list(page_rows), next_cursor=next_cursor)


async def record_guard_denied(
    principal: Principal,
    *,
    path: str | None,
    reason: str,
    resource_id: str | None,
) -> None:
    try:
        session = core_db.get_session_local()()
        try:
            await bind_tenant(session, principal.tenant_id)
            await audit_service.record_explicit(
                session,
                action="GUARD_DENIED",
                resource_type=GUARD_DENIED_RESOURCE_TYPE,
                resource_id=resource_id,
                detail={"path": path, "reason": reason},
                principal=principal,
            )
            await session.commit()
        finally:
            await session.close()
    except Exception:
        logger.warning("GUARD_DENIED 审计落库失败", exc_info=True)


async def verify_entry(
    sess: AsyncSession,
    principal: Principal,
    value_id: UUID,
    *,
    path: str | None = None,
) -> ValueLedger | None:
    """人工核验（Human-Only）。"""
    if principal.kind != "HUMAN":
        await record_guard_denied(
            principal, path=path, reason="Human-Only", resource_id=str(value_id)
        )
        raise EdpError.guard_policy_denied("该操作仅限人工执行")
    entry = await get_entry(sess, value_id)
    if entry is None:
        return None
    entry.verified_by = principal.id
    entry.verified_at = datetime.now(UTC)
    entry.updated_by = principal.id
    entry.updated_at = datetime.now(UTC)
    await sess.flush()
    return entry
