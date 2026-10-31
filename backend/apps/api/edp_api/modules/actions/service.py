"""actions 服务：行动任务状态机（EDP-020，B.5 / 设计 7.4/7.5 单点实现）。

TRANSITIONS 为转移合法性唯一事实来源（应用层集中定义，设计 7.5）：
- 9 态；VERIFIED/CANCELLED/REJECTED 为终态（无出边）；
- APPROVED→EXECUTING、COMPLETED→VERIFIED 两条 **Human-Only** 边。

create_action：case_id 提供但不存在（RLS 下跨租户同义）→ 400。
query_actions/get_action：游标分页（created_at DESC, action_id DESC
tiebreak，锚 ``{"c","i"}``）/ 点查；列表与详情经 allowed_to 附当前状态
允许转移（to_status 字典序稳定）。

transition_action（PATCH /status）：
1. ``to_status`` 不在 ``TRANSITIONS[from_status]`` → 422 INVALID_TRANSITION
   （extra.allowed_to = 当前状态允许列表）；
2. Human-Only 边且 principal 非 HUMAN → 经 ``record_guard_denied`` 独立会话
   落 GUARD_DENIED 审计后抛 403 GUARD_POLICY_DENIED（与 decisions/memories
   同构的拒绝留痕模式）；
3. ``UPDATE ... WHERE action_id=:id AND status=:from_status``（乐观锁，
   设计 7.4）rowcount=0 → 409 CONFLICT；
4. comment 非空 → 同事务创建证据（source_system=``edp``、source_record_id=
   ``{action_id}#{to_status}``、ref_type=ACTION、ref_id=action_id、
   snapshot=``{"comment": ...}``——设计 7.5「审批意见落证据链」）；证据
   object 锚点经 case.source_id（事件）→ event.object_id 解析，不可得
   （无 case / 无源事件）时跳过并留痕；
5. 回填：to=COMPLETED → completion_time=now()；to=VERIFIED →
   verified_at=now() + verified_by=principal.id（与 memories.reviewed_by
   口径一致：JWT=用户 UUID、Key=principal_id，非显示名）。

审计：INSERT 走 ORM（切面自动 ACTION_CREATE）；转移 UPDATE 为纯 SQL
（切面不可见）——由本层 record_explicit 显式补点 ACTION_UPDATE（registry
乐观锁同一模式）。

RLS：会话由 tenant_scoped 预 bind_tenant（action.* FORCE RLS）——跨租户
action_id/case_id 与不存在同义（404/400 不泄露存在性）。

事务边界：本层只 flush 不 commit——请求级提交由 core.db.get_db 统一执行。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core import db as core_db
from edp_api.core.db import bind_tenant
from edp_api.core.errors import EdpError
from edp_api.core.pagination import Page, decode_cursor, encode_cursor
from edp_api.core.security.principal import Principal
from edp_api.modules.actions.models import Action
from edp_api.modules.actions.schemas import (
    ActionCreateRequest,
    ActionListItem,
    ActionTransitionRequest,
    TransitionItem,
)
from edp_api.modules.audit import service as audit_service
from edp_api.modules.events import service as events_service
from edp_api.modules.evidence import service as evidence_service
from edp_api.modules.evidence.schemas import EvidenceCreateRequest, EvidenceLinkIn

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

# 转移合法性表（设计 7.5 状态机）：from -> {to: human_only}
TRANSITIONS: dict[str, dict[str, bool]] = {
    "PROPOSED": {"ASSIGNED": False, "REJECTED": False, "CANCELLED": False},
    "ASSIGNED": {"ACCEPTED": False, "CANCELLED": False},
    "ACCEPTED": {"APPROVED": False, "CANCELLED": False},
    "APPROVED": {"EXECUTING": True, "CANCELLED": False},
    "EXECUTING": {"COMPLETED": False, "CANCELLED": False},
    "COMPLETED": {"VERIFIED": True, "CANCELLED": False},
    "VERIFIED": {},
    "CANCELLED": {},
    "REJECTED": {},
}

GUARD_DENIED_ACTION = "GUARD_DENIED"
GUARD_DENIED_RESOURCE_TYPE = "action.actions"
HUMAN_ONLY_REASON = "Human-Only"
HUMAN_ONLY_MESSAGE = "该操作仅限人工执行"

# comment 证据归属源系统（设计 7.5：审批意见落证据链）
COMMENT_EVIDENCE_SOURCE_SYSTEM = "edp"
COMMENT_EVIDENCE_REF_TYPE = "ACTION"


def allowed_to(status: str) -> list[dict]:
    """当前状态允许转移列表 [{to_status, human_only}]（to_status 字典序稳定）。"""
    return [
        {"to_status": to_status, "human_only": human_only}
        for to_status, human_only in sorted(TRANSITIONS.get(status, {}).items())
    ]


def _transition_items(status: str) -> list[TransitionItem]:
    return [TransitionItem(**item) for item in allowed_to(status)]


async def record_guard_denied(
    principal: Principal,
    *,
    path: str | None,
    reason: str,
    resource_id: str | None,
) -> None:
    """独立会话落 GUARD_DENIED 审计（Human-Only 拒绝路径，decisions/memories
    同构）：拒绝伴随事务回滚，审计不能依赖调用方事务——独立会话解耦保证
    拒绝留痕；审计失败仅 warning，不改变 403 决策。
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
        logger.warning("GUARD_DENIED 审计落库失败", exc_info=True)


async def create_action(
    sess: AsyncSession, principal: Principal, req: ActionCreateRequest
) -> Action:
    """创建行动任务 → PROPOSED（ORM 写，切面自动 ACTION_CREATE）。

    Raises:
        EdpError(VALIDATION_ERROR): case_id 提供但案例不存在（RLS 下跨租户
        与不存在同义）。
    """
    if req.case_id is not None and not await _case_exists(sess, req.case_id):
        raise EdpError.validation_error(f"case_id 不存在：{req.case_id}")

    action = Action(
        action_id=uuid4(),
        tenant_id=principal.tenant_id,
        case_id=req.case_id,
        title=req.title,
        description=req.description,
        action_type=req.action_type,
        status="PROPOSED",
        owner=req.owner,
        owner_role=req.owner_role,
        due_date=req.due_date,
        created_by=principal.id,
        updated_by=principal.id,
    )
    sess.add(action)
    await sess.flush()
    await sess.refresh(action)  # 载入 server 默认（created_at/updated_at）
    return action


async def query_actions(
    sess: AsyncSession,
    *,
    status: str | None = None,
    owner: str | None = None,
    case_id: UUID | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[ActionListItem]:
    """status/owner/case_id 过滤 + 游标分页（created_at DESC, action_id DESC
    tiebreak）；简投影附 allowed_to；非法 cursor 视为首页。"""
    limit = max(1, min(limit, MAX_LIMIT))
    conditions = []
    if status:
        conditions.append(Action.status == status)
    if owner:
        conditions.append(Action.owner == owner)
    if case_id is not None:
        conditions.append(Action.case_id == case_id)

    stmt = select(Action).where(*conditions)
    decoded = decode_cursor(cursor)
    if decoded is not None:
        anchor = _parse_anchor(decoded)
        if anchor is not None:
            created_at, action_id_anchor = anchor
            stmt = stmt.where(
                or_(
                    Action.created_at < created_at,
                    and_(
                        Action.created_at == created_at,
                        Action.action_id < action_id_anchor,
                    ),
                )
            )
    stmt = stmt.order_by(Action.created_at.desc(), Action.action_id.desc()).limit(
        limit + 1
    )
    rows = (await sess.execute(stmt)).scalars().all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"c": last.created_at.isoformat(), "i": str(last.action_id)}
        )
    return Page(
        items=[
            ActionListItem(
                action_id=row.action_id,
                title=row.title,
                status=row.status,
                owner=row.owner,
                due_date=row.due_date,
                allowed_to=_transition_items(row.status),
            )
            for row in page_rows
        ],
        next_cursor=next_cursor,
    )


async def get_action(sess: AsyncSession, action_id: UUID) -> Action | None:
    """按 action_id 点查；RLS 下跨租户 = 不存在（None）。"""
    return await sess.get(Action, action_id)


async def transition_action(
    sess: AsyncSession,
    principal: Principal,
    action_id: UUID,
    req: ActionTransitionRequest,
    *,
    path: str | None = None,
) -> Action | None:
    """状态机转移（乐观锁 from_status；Human-Only 守卫；comment 落证据）。

    Raises:
        EdpError(INVALID_TRANSITION): to_status 不在 from_status 允许列表
        （extra.allowed_to = 当前状态允许列表）；
        EdpError(GUARD_POLICY_DENIED): Human-Only 边且 principal 非 HUMAN
        （先独立会话落 GUARD_DENIED 审计）；
        EdpError(CONFLICT): UPDATE 未命中（from_status 与当前不符 / 并发抢先）。

    Returns:
        转移后行动对象；action_id 不存在（含跨租户）→ None。
    """
    action = await sess.get(Action, action_id)
    if action is None:
        return None

    targets = TRANSITIONS.get(req.from_status, {})
    if req.to_status not in targets:
        raise EdpError.invalid_transition(
            f"非法转移：{req.from_status} → {req.to_status}",
            extra={"allowed_to": allowed_to(action.status)},
        )

    if targets[req.to_status] is True and principal.kind != "HUMAN":
        await record_guard_denied(
            principal,
            path=path,
            reason=HUMAN_ONLY_REASON,
            resource_id=str(action_id),
        )
        raise EdpError.guard_policy_denied(HUMAN_ONLY_MESSAGE)

    values: dict = {
        "status": req.to_status,
        "updated_by": principal.id,
        "updated_at": func.now(),
    }
    changed = ["status"]
    if req.to_status == "COMPLETED":
        values["completion_time"] = func.now()
        changed.append("completion_time")
    elif req.to_status == "VERIFIED":
        values["verified_at"] = func.now()
        # verified_by 口径与 memories.reviewed_by 一致：principal.id
        # （JWT = 用户 UUID；API Key = principal_id），非显示名
        values["verified_by"] = principal.id
        changed.extend(["verified_at", "verified_by"])

    result = await sess.execute(
        update(Action)
        .where(Action.action_id == action_id, Action.status == req.from_status)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        raise EdpError.conflict(
            f"from_status 与当前状态不符：{req.from_status}"
        )

    if req.comment:
        await _persist_comment_evidence(sess, principal, action_id, req)

    await sess.refresh(action)  # 载入 UPDATE 后行值（status/updated_at/回填列）
    # SQL UPDATE 不经 ORM 状态（切面不可见）——显式补审计 ACTION_UPDATE
    # （registry 乐观锁同一模式；resource_type 用 fullname，与 GUARD_DENIED 一致）
    await audit_service.record_explicit(
        sess,
        action="ACTION_UPDATE",
        resource_type="action.actions",
        resource_id=str(action_id),
        detail={
            "before": {"status": req.from_status},
            "after": {"status": req.to_status},
            "changed": changed,
        },
        principal=principal,
    )
    return action


async def _persist_comment_evidence(
    sess: AsyncSession,
    principal: Principal,
    action_id: UUID,
    req: ActionTransitionRequest,
) -> None:
    """comment 非空 → 同事务创建证据（设计 7.5「审批意见落证据链」）。

    证据 object 锚点经 case.source_id（事件）→ event.object_id 解析；不可得
    （行动未关联案例 / 案例无源事件）时跳过并留痕——转移本身不受影响。
    """
    object_id = await _comment_object_id(sess, action_id)
    if object_id is None:
        logger.info("comment 证据缺少 object 锚点，跳过落证：%s", action_id)
        return
    await evidence_service.create_record(
        sess,
        principal,
        EvidenceCreateRequest(
            source_system=COMMENT_EVIDENCE_SOURCE_SYSTEM,
            source_record_id=f"{action_id}#{req.to_status}",
            object_id=object_id,
            snapshot={"comment": req.comment},
            captured_at=datetime.now(UTC),
            links=[
                EvidenceLinkIn(ref_type=COMMENT_EVIDENCE_REF_TYPE, ref_id=action_id)
            ],
        ),
    )


async def _comment_object_id(sess: AsyncSession, action_id: UUID) -> UUID | None:
    """comment 证据的 object 锚点：action.case_id → case.source_id（事件）
    → event.object_id；任一环节缺失 → None。"""
    source_id = (
        await sess.execute(
            text(
                "SELECT c.source_id FROM decision.cases c"
                " JOIN action.actions a ON a.case_id = c.case_id"
                " WHERE a.action_id = :id"
            ),
            {"id": action_id},
        )
    ).scalar_one_or_none()
    if not source_id:
        return None
    try:
        event_id = UUID(str(source_id))
    except ValueError:
        return None
    event = await events_service.get_event(sess, event_id)
    return event.object_id if event is not None else None


async def _case_exists(sess: AsyncSession, case_id: UUID) -> bool:
    """案例存在性（RLS 下跨租户 = 不存在）；跨模块读表走轻量 SQL
    （events/_BUSINESS_OBJECTS 同惯例，不 import 对方 models）。"""
    return (
        await sess.execute(
            text("SELECT 1 FROM decision.cases WHERE case_id = :c"), {"c": case_id}
        )
    ).scalar_one_or_none() is not None


def _parse_anchor(decoded: dict) -> tuple[datetime, UUID] | None:
    """cursor 载荷 → (created_at, action_id)；缺字段/格式非法 → None。"""
    try:
        return datetime.fromisoformat(str(decoded["c"])), UUID(str(decoded["i"]))
    except (KeyError, TypeError, ValueError):
        return None
