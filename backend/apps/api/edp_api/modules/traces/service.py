"""traces 服务：轨迹写入（trace_id 幂等）/ 明细随行 / 游标查询 / 点查。

写入路径（B.10 POST /traces）：
- ``trace_id`` 客户端提供 = 天然幂等键：``INSERT ... ON CONFLICT DO NOTHING``
  （无目标子句覆盖 trace_id 主键）——新 trace → 201 并同事务批量写入
  tool_calls；同 trace_id 重发 → 200 幂等返回既有 {trace_id, status,
  created_at}，**不重写 tool_calls**（Agent 重试安全）。跨租户撞 trace_id
  主键（RLS 下不可见）→ 409 CONFLICT；
- capability_id 存在性校验经 catalog.service（模块间仅 service；RLS 下
  跨租户与不存在同义）→ 400 VALIDATION_ERROR；
- tool_calls 批量随行：``call_id=uuid4()``、``called_at`` 取请求值（缺省
  now()），单条多行 INSERT 同事务落库；
- pg_insert 不经 ORM 状态（切面不可见）——按 events 同法 record_explicit
  显式补审计（每条新 trace 一行 TRACE_CREATE；幂等重发不补）。

RLS：trace.traces / trace.tool_calls 均 FORCE RLS——会话由 tenant_scoped
预 bind_tenant；跨租户读取恒表现为"不存在"（详情 404 / 列表空）。

事务边界：本层只 flush 不 commit——请求级提交由 core.db.get_db 统一执行。
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.errors import EdpError
from edp_api.core.pagination import decode_cursor, encode_cursor
from edp_api.core.security.principal import Principal
from edp_api.modules.audit import service as audit_service
from edp_api.modules.catalog import service as catalog_service
from edp_api.modules.traces.models import ToolCall, Trace
from edp_api.modules.traces.schemas import (
    ToolCallItem,
    TraceCreatedResponse,
    TraceCreateRequest,
    TraceDetail,
    TraceListItem,
)

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def _utc(value: datetime) -> datetime:
    """TIMESTAMPTZ 归一化：naive 视为 UTC，aware 转 UTC（口径同 events）。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


# ---- 写入（B.10；trace_id 幂等） ----


async def create_trace(
    sess: AsyncSession, principal: Principal, req: TraceCreateRequest
) -> tuple[TraceCreatedResponse, bool]:
    """写入一条轨迹 + 随行 tool_calls（B.10）。

    Returns:
        (响应体, created)：新建 → (201 载荷, True)；同 trace_id 重发 →
        (既有 {trace_id, status, created_at}, False)，不重写 tool_calls。

    Raises:
        EdpError: capability_id 不存在（含跨租户）→ 400；跨租户撞
        trace_id 主键 → 409。
    """
    if req.capability_id is not None:
        if await catalog_service.get_capability(sess, req.capability_id) is None:
            raise EdpError.validation_error(
                f"capability_id 不存在：{req.capability_id}"
            )

    stmt = (
        pg_insert(Trace)
        .values(
            trace_id=req.trace_id,
            tenant_id=principal.tenant_id,
            agent_id=req.agent_id,
            task_id=req.task_id,
            capability_id=req.capability_id,
            started_at=_utc(req.started_at),
            finished_at=_utc(req.finished_at) if req.finished_at else None,
            status=req.status,
            input_context=req.input_context,
            output_structured=req.output_structured,
            token_usage=req.token_usage,
            evidence_refs=req.evidence_refs,
            created_by=principal.id,
            updated_by=principal.id,
        )
        .on_conflict_do_nothing()
        .returning(Trace.trace_id, Trace.status, Trace.created_at)
    )
    row = (await sess.execute(stmt)).one_or_none()
    if row is None:
        existing = (
            await sess.execute(
                select(Trace.trace_id, Trace.status, Trace.created_at).where(
                    Trace.trace_id == req.trace_id
                )
            )
        ).one_or_none()
        if existing is None:
            # 主键冲突但本租户不可见 = 跨租户撞 trace_id（不泄露对方详情）
            raise EdpError.conflict(f"trace_id 已被占用：{req.trace_id}")
        return (
            TraceCreatedResponse(
                trace_id=existing.trace_id,
                status=existing.status,
                created_at=existing.created_at,
            ),
            False,
        )

    if req.tool_calls:
        await sess.execute(
            pg_insert(ToolCall).values(
                [
                    {
                        "call_id": uuid4(),
                        "tenant_id": principal.tenant_id,
                        "trace_id": req.trace_id,
                        "seq": tc.seq,
                        "tool_name": tc.tool_name,
                        "input": tc.input,
                        "output": tc.output,
                        "status_code": tc.status_code,
                        "error": tc.error,
                        "latency_ms": tc.latency_ms,
                        "called_at": _utc(tc.called_at) if tc.called_at else func.now(),
                    }
                    for tc in req.tool_calls
                ]
            )
        )

    # pg_insert 不经 ORM 状态（切面不可见）——显式补审计（模块间仅 service）
    await audit_service.record_explicit(
        sess,
        action="TRACE_CREATE",
        resource_type="traces",
        resource_id=str(req.trace_id),
        detail={
            "agent_id": req.agent_id,
            "task_id": req.task_id,
            "capability_id": str(req.capability_id) if req.capability_id else None,
            "status": req.status,
            "tool_calls": len(req.tool_calls),
        },
        principal=principal,
    )
    return (
        TraceCreatedResponse(
            trace_id=row.trace_id, status=row.status, created_at=row.created_at
        ),
        True,
    )


# ---- 查询（B.10；简投影 + 游标） ----


async def query_traces(
    sess: AsyncSession,
    *,
    agent_id: str | None = None,
    task_id: str | None = None,
    capability_id: UUID | None = None,
    since: datetime | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> tuple[list[TraceListItem], str | None]:
    """agent_id/task_id/capability_id/since（started_at >= since）过滤 +
    游标分页（started_at DESC, trace_id DESC tiebreak，锚 ``{"s","i"}``）；
    取 limit+1 探测下一页；非法 cursor 视为首页；列表为简投影。"""
    limit = max(1, min(limit, MAX_LIMIT))
    conditions = []
    if agent_id:
        conditions.append(Trace.agent_id == agent_id)
    if task_id:
        conditions.append(Trace.task_id == task_id)
    if capability_id is not None:
        conditions.append(Trace.capability_id == capability_id)
    if since is not None:
        conditions.append(Trace.started_at >= _utc(since))

    stmt = select(Trace).where(*conditions)

    decoded = decode_cursor(cursor)
    if decoded is not None:
        anchor = _parse_anchor(decoded)
        if anchor is not None:
            started_at, trace_id_anchor = anchor
            stmt = stmt.where(
                or_(
                    Trace.started_at < started_at,
                    and_(Trace.started_at == started_at, Trace.trace_id < trace_id_anchor),
                )
            )

    stmt = stmt.order_by(Trace.started_at.desc(), Trace.trace_id.desc()).limit(limit + 1)
    rows = (await sess.execute(stmt)).scalars().all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"s": last.started_at.isoformat(), "i": str(last.trace_id)}
        )
    return [TraceListItem.model_validate(row) for row in page_rows], next_cursor


async def get_trace(sess: AsyncSession, trace_id: UUID) -> TraceDetail | None:
    """完整轨迹点查（含 tool_calls[] seq 升序）；RLS 下跨租户 = 不存在
    （None，不泄露存在性）。"""
    trace = await sess.get(Trace, trace_id)
    if trace is None:
        return None
    calls = (
        (
            await sess.execute(
                select(ToolCall)
                .where(ToolCall.trace_id == trace_id)
                .order_by(ToolCall.seq.asc())
            )
        )
        .scalars()
        .all()
    )
    detail = TraceDetail.model_validate(trace)
    detail.tool_calls = [ToolCallItem.model_validate(call) for call in calls]
    return detail


def _parse_anchor(decoded: dict) -> tuple[datetime, UUID] | None:
    """cursor 载荷 → (started_at, trace_id)；缺字段/格式非法 → None。"""
    try:
        return datetime.fromisoformat(str(decoded["s"])), UUID(str(decoded["i"]))
    except (KeyError, TypeError, ValueError):
        return None
