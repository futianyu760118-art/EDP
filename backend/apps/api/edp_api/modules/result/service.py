"""result 服务（V1.2 T17）：经营结果创建/查询/核验 + RESULT 证据关联。

- create_result：对象存在性校验（RLS 下跨租户与不存在同义 400）+
  evidence_refs 非空硬约束（无 Evidence 的 Result 不得创建——先数据可信）
  + 逐条 ensure RESULT links（幂等）；
- verify：Human-Only 核验——证据链重校验（evidence 行存在性）后落
  verified_status/verified_by/verified_at；
- 跨模块读（evidence links / 事件）经 service 路径（口径同 decisions）。
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
from edp_api.modules.evidence import service as evidence_service
from edp_api.modules.result.models import Result
from edp_api.modules.result.schemas import ResultCreateRequest

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

RESULT_REF_TYPE = "RESULT"
GUARD_DENIED_RESOURCE_TYPE = "result.results"


async def create_result(
    sess: AsyncSession, principal: Principal, req: ResultCreateRequest
) -> Result:
    """创建经营结果：对象存在 + evidence 非空 → INSERT → RESULT links。

    Raises:
        EdpError(VALIDATION_ERROR): object_id 不存在（含跨租户）；或
        evidence_refs 中存在不可见证据。
    """
    object_id = (
        await sess.execute(
            text("SELECT 1 FROM master.business_objects WHERE object_id = :oid"),
            {"oid": req.object_id},
        )
    ).scalar_one_or_none()
    if object_id is None:
        raise EdpError.validation_error(f"object_id 不存在：{req.object_id}")

    result = Result(
        result_id=uuid4(),
        tenant_id=principal.tenant_id,
        result_type=req.result_type,
        object_id=req.object_id,
        domain=req.domain,
        period=req.period,
        metric_refs=req.metric_refs,
        value=req.value,
        status=req.status,
        source_refs=req.source_refs,
        evidence_refs=list(dict.fromkeys(req.evidence_refs)),
        generated_by=req.generated_by,
        generated_at=datetime.now(UTC),
        created_by=principal.id,
        updated_by=principal.id,
    )
    sess.add(result)
    await sess.flush()

    for evidence_id in result.evidence_refs:
        link = await evidence_service.ensure_link(
            sess,
            principal,
            evidence_id=evidence_id,
            ref_type=RESULT_REF_TYPE,
            ref_id=result.result_id,
        )
        if link is None:
            raise EdpError.validation_error(f"evidence_id 不存在：{evidence_id}")
    return result


async def get_result(sess: AsyncSession, result_id: UUID) -> Result | None:
    """详情；不存在（含跨租户，RLS）→ None。"""
    return (
        await sess.execute(select(Result).where(Result.result_id == result_id))
    ).scalar_one_or_none()


async def query_results(
    sess: AsyncSession,
    *,
    result_type: str | None = None,
    status: str | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[Result]:
    """列表（result_type/status 过滤 + 游标分页 generated_at DESC tiebreak）。"""
    limit = max(1, min(limit, MAX_LIMIT))
    stmt = select(Result)
    if result_type:
        stmt = stmt.where(Result.result_type == result_type)
    if status:
        stmt = stmt.where(Result.status == status)
    decoded = decode_cursor(cursor)
    if decoded is not None:
        try:
            anchor_generated = datetime.fromisoformat(str(decoded["g"]))
            anchor_id = UUID(str(decoded["i"]))
            stmt = stmt.where(
                or_(
                    Result.generated_at < anchor_generated,
                    and_(
                        Result.generated_at == anchor_generated,
                        Result.result_id < anchor_id,
                    ),
                )
            )
        except (KeyError, TypeError, ValueError):
            pass
    stmt = stmt.order_by(Result.generated_at.desc(), Result.result_id.desc()).limit(
        limit + 1
    )
    rows = (await sess.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"g": last.generated_at.isoformat(), "i": str(last.result_id)}
        )
    return Page(items=list(page_rows), next_cursor=next_cursor)


async def record_guard_denied(
    principal: Principal,
    *,
    path: str | None,
    reason: str,
    resource_id: str | None,
) -> None:
    """独立会话落 GUARD_DENIED 审计（Human-Only 拒绝路径，同 governance/
    decisions 解耦先例）。"""
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


async def verify_result(
    sess: AsyncSession,
    principal: Principal,
    result_id: UUID,
    *,
    path: str | None = None,
) -> Result | None:
    """核验（Human-Only）：证据链存在性重校验后落 verified_*。

    Raises:
        EdpError(GUARD_POLICY_DENIED): 非 HUMAN；
        EdpError(VALIDATION_ERROR): 证据链残缺（行被删）。
    """
    if principal.kind != "HUMAN":
        await record_guard_denied(
            principal, path=path, reason="Human-Only", resource_id=str(result_id)
        )
        raise EdpError.guard_policy_denied("该操作仅限人工执行")
    result = await get_result(sess, result_id)
    if result is None:
        return None
    for evidence_id in result.evidence_refs:
        if await evidence_service.get_record(sess, evidence_id) is None:
            raise EdpError.validation_error(f"证据链残缺：{evidence_id}")
    result.verified_status = "VERIFIED"
    result.verified_by = principal.id
    result.verified_at = datetime.now(UTC)
    result.updated_by = principal.id
    result.updated_at = datetime.now(UTC)
    await sess.flush()
    return result
