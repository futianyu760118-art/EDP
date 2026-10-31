"""decisions 服务：决策案例创建/查询 + Human-Only 决策记录（EDP-018 最小版）
+ 闭环案例聚合（W4 EDP-028）。

create_case（B.5）：
- case_no = ``DC-{YYYYMMDD}-{当日同租户序号:03d}``（当日已有行数 + 1；唯一
  索引 uq_case_no 兜底并发——IntegrityError 经 savepoint 回滚后重算重试一次）；
- source_id 重复（uq_cases_tenant_source，0012 部分唯一索引）→ 409 CONFLICT
  「该来源事件已建案例」（与 ebms exceptions 标量子查询双保险）；
- evidence_ids → CASE links（经 evidence_service.ensure_link 幂等：同
  (ref_type=CASE, ref_id=case_id, evidence_id) 已存在跳过；证据不存在 → 400）；
- source_id 可解析为 UUID 时校验事件存在（不存在/跨租户 → 400）。

submit_record（B.5，Human-Only）：
- ``principal.kind != "HUMAN"`` → 经 ``record_guard_denied`` 独立会话落
  GUARD_DENIED 审计（resource_type=decision.records）再抛
  GUARD_POLICY_DENIED（HTTP 路径由依赖层先行拦截，同函数落审计；直调
  service 同样留痕）；HUMAN 的 ``decision:decide`` 由依赖层判定；
- 案例非 OPEN → 409 CONFLICT；成功同事务写 decision.records + case 置
  DECIDED/decided_at（updated_at 显式刷新）。

find_case_by_source：seed 幂等查询口（demo 服务消费，替代 T7 raw SQL 直写）。
query_cases/get_case_detail：游标分页（created_at DESC, case_id DESC tiebreak，
锚 ``{"c","i"}``）；详情含 evidence_refs（links join 证据投影）+ decisions。

get_case_detail 闭环聚合（W4 EDP-028，设计 7.6 逆向追溯 / 13.6.5）：
- event：source 事件摘要（cases.source_id join event.events，summary 复用
  ebms coalesce 派生）；
- steps：时间升序时间线（EVENT/CASE_CREATED/DECISION/ACTION——每个行动
  两个节点：创建 + 当前状态快照，快照 human_only 按当前 status 是否存在
  Human-Only 出边（actions.TRANSITIONS，仅 APPROVED/COMPLETED 为 True；
  逐转移明细经审计页 ACTION_UPDATE 可查，最小版留痕）；
- actions：关联行动全量（allowed_to 经 actions_service.allowed_to 单点）；
- evidence_chain：RESULT（ref_id=source 事件）/ DECISION（ref_id=case）/
  EVIDENCE（ref_type=CASE 集合）/ SOURCE（(source_system, source_record_id)
  投影去重）四层。

RLS：会话由 tenant_scoped 预 bind_tenant（decision.*/evidence.* FORCE RLS）
——跨租户 case_id/evidence_id/event_id 与不存在同义（404/400 不泄露存在性）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Text,
    Uuid,
    and_,
    column,
    func,
    or_,
    select,
    table,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core import db as core_db
from edp_api.core.db import bind_tenant
from edp_api.core.errors import EdpError
from edp_api.core.pagination import Page, decode_cursor, encode_cursor
from edp_api.core.security.principal import Principal
from edp_api.modules.actions import service as actions_service
from edp_api.modules.audit import service as audit_service
from edp_api.modules.decisions.models import Case, DecisionRecord
from edp_api.modules.decisions.schemas import (
    ActionTransitionRef,
    CaseActionItem,
    CaseCreateRequest,
    CaseDetailResponse,
    CaseEventSummary,
    CaseListItem,
    CaseStepItem,
    DecisionCreateRequest,
    DecisionItem,
    EvidenceChainItem,
    EvidenceRefItem,
)
from edp_api.modules.events import service as events_service
from edp_api.modules.evidence import service as evidence_service

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

CASE_NO_PREFIX = "DC"
CASE_REF_TYPE = "CASE"
RESULT_REF_TYPE = "RESULT"
DECISION_REF_TYPE = "DECISION"
SOURCE_DUPLICATE_CONSTRAINT = "uq_cases_tenant_source"
SOURCE_DUPLICATE_MESSAGE = "该来源事件已建案例，不可重复创建案例"
GUARD_DENIED_ACTION = "GUARD_DENIED"
GUARD_DENIED_RESOURCE_TYPE = "decision.records"
HUMAN_ONLY_REASON = "Human-Only"
HUMAN_ONLY_MESSAGE = "该操作仅限人工执行"

# 跨模块表参与读（action.actions 归 actions 模块——模块间仅可 import 对方
# service，ORM 不可直接引用）：以核心 table() 构造参与纯 SQL 读（口径同
# ebms/tools 的跨模块读）；RLS 会话已 bind_tenant，跨租户行不可见。
_ACTIONS = table(
    "actions",
    column("action_id", Uuid),
    column("tenant_id", Uuid),
    column("case_id", Uuid),
    column("title", Text),
    column("action_type", Text),
    column("status", Text),
    column("owner", Text),
    column("due_date", DateTime(timezone=True)),
    column("created_at", DateTime(timezone=True)),
    column("updated_at", DateTime(timezone=True)),
    column("created_by", Text),
    column("updated_by", Text),
    schema="action",
)


async def record_guard_denied(
    principal: Principal,
    *,
    path: str | None,
    reason: str,
    resource_id: str | None,
) -> None:
    """独立会话落 GUARD_DENIED 审计（Human-Only 拒绝路径唯一实现）。

    拒绝必然伴随事务回滚（HTTP 请求会话 / 直调 service 的事务），审计不能
    依赖调用方事务——独立会话与业务事务解耦保证拒绝留痕；审计失败仅
    warning，不改变 403 决策。依赖层（require_decision_decide）与服务层
    守卫共用本函数。
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


async def create_case(
    sess: AsyncSession, principal: Principal, req: CaseCreateRequest
) -> Case:
    """创建决策案例：source 事件校验 → INSERT（case_no 日序号）→ CASE links。

    Raises:
        EdpError(VALIDATION_ERROR): source_id 为 UUID 但事件不存在；或
        evidence_ids 中存在本租户不可见的证据（RLS 下跨租户与不存在同义）；
        EdpError(CONFLICT): source_id 已建案例（uq_cases_tenant_source，
        W4/0012——「该来源事件已建案例」）。
    """
    if req.source_id is not None:
        source_event_id = _as_uuid(req.source_id)
        if (
            source_event_id is not None
            and await events_service.get_event(sess, source_event_id) is None
        ):
            raise EdpError.validation_error(f"source_id 事件不存在：{req.source_id}")

    case = await _insert_case(sess, principal, req)
    for evidence_id in dict.fromkeys(req.evidence_ids):
        link = await evidence_service.ensure_link(
            sess,
            principal,
            evidence_id=evidence_id,
            ref_type=CASE_REF_TYPE,
            ref_id=case.case_id,
        )
        if link is None:
            raise EdpError.validation_error(f"evidence_id 不存在：{evidence_id}")
    return case


async def _insert_case(
    sess: AsyncSession, principal: Principal, req: CaseCreateRequest
) -> Case:
    """case_no 冲突（并发）经 savepoint 回滚后重算重试一次（唯一索引兜底）；
    source_id 重复（uq_cases_tenant_source）→ 409 CONFLICT（不重试）。"""
    for attempt in range(2):
        case = Case(
            case_id=uuid4(),
            tenant_id=principal.tenant_id,
            case_no=await _next_case_no(sess, principal.tenant_id),
            question=req.question,
            context=req.context,
            options=[option.model_dump() for option in req.options],
            risk_level=req.risk_level,
            source_type=req.source_type,
            source_id=req.source_id,
            status="OPEN",
            created_by=principal.id,
            updated_by=principal.id,
        )
        try:
            async with sess.begin_nested():
                sess.add(case)
                await sess.flush()
            return case
        except IntegrityError as exc:
            if _is_duplicate_source(exc):
                raise EdpError.conflict(SOURCE_DUPLICATE_MESSAGE) from exc
            if attempt == 1:
                raise
            logger.warning("case_no 冲突，重试一次：%s", case.case_no)
    raise AssertionError("unreachable")  # pragma: no cover


def _is_duplicate_source(exc: IntegrityError) -> bool:
    """IntegrityError 是否源于 uq_cases_tenant_source（0012 部分唯一索引）。

    asyncpg 的 UniqueViolationError 带 constraint_name；取不到时以消息文本
    兜底（索引名出现在 PG 错误详情里）。
    """
    orig = getattr(exc, "orig", None)
    constraint = getattr(orig, "constraint_name", None)
    if constraint is not None:
        return constraint == SOURCE_DUPLICATE_CONSTRAINT
    return SOURCE_DUPLICATE_CONSTRAINT in str(orig or exc)


async def _next_case_no(sess: AsyncSession, tenant_id: UUID) -> str:
    """DC-{YYYYMMDD}-{当日同租户序号:03d}（当日已有行数 + 1）。"""
    prefix = f"{CASE_NO_PREFIX}-{datetime.now(UTC):%Y%m%d}-"
    count = (
        await sess.execute(
            select(func.count())
            .select_from(Case)
            .where(Case.tenant_id == tenant_id, Case.case_no.like(f"{prefix}%"))
        )
    ).scalar_one()
    return f"{prefix}{count + 1:03d}"


async def find_case_by_source(
    sess: AsyncSession, source_type: str, source_id: str
) -> Case | None:
    """按 (source_type, source_id) 查案例（seed 幂等口；RLS 限本租户）。"""
    return (
        await sess.execute(
            select(Case)
            .where(Case.source_type == source_type, Case.source_id == source_id)
            .order_by(Case.created_at, Case.case_id)
            .limit(1)
        )
    ).scalar_one_or_none()


async def query_cases(
    sess: AsyncSession,
    *,
    status: str | None = None,
    risk_level: str | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[CaseListItem]:
    """status/risk_level 过滤 + 游标分页（created_at DESC, case_id DESC
    tiebreak）；非法 cursor 视为首页。"""
    limit = max(1, min(limit, MAX_LIMIT))
    conditions = []
    if status:
        conditions.append(Case.status == status)
    if risk_level:
        conditions.append(Case.risk_level == risk_level)

    stmt = select(Case).where(*conditions)
    decoded = decode_cursor(cursor)
    if decoded is not None:
        anchor = _parse_anchor(decoded)
        if anchor is not None:
            created_at, case_id_anchor = anchor
            stmt = stmt.where(
                or_(
                    Case.created_at < created_at,
                    and_(
                        Case.created_at == created_at,
                        Case.case_id < case_id_anchor,
                    ),
                )
            )
    stmt = stmt.order_by(Case.created_at.desc(), Case.case_id.desc()).limit(limit + 1)
    rows = (await sess.execute(stmt)).scalars().all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"c": last.created_at.isoformat(), "i": str(last.case_id)}
        )
    return Page(
        items=[CaseListItem.model_validate(row) for row in page_rows],
        next_cursor=next_cursor,
    )


async def get_case_detail(
    sess: AsyncSession, case_id: UUID
) -> CaseDetailResponse | None:
    """案例详情（B.5 + W4 EDP-028 闭环聚合）：evidence_refs（links 关联证据
    全量）+ decisions + event/steps/actions/evidence_chain；case_id 不存在
    （含跨租户）→ None。"""
    case = await sess.get(Case, case_id)
    if case is None:
        return None

    case_evidence = await _all_linked_evidence(sess, CASE_REF_TYPE, case_id)
    evidence_refs = [
        EvidenceRefItem(
            evidence_id=item.evidence_id,
            checksum=item.checksum,
            source_system=item.source_system,
        )
        for item in case_evidence
    ]

    records = (
        (
            await sess.execute(
                select(DecisionRecord)
                .where(DecisionRecord.case_id == case_id)
                .order_by(DecisionRecord.decision_time, DecisionRecord.decision_id)
            )
        )
        .scalars()
        .all()
    )

    event = await _source_event(sess, case.source_id)
    actions, action_steps = await _case_actions(sess, case_id)
    steps = _sort_steps(_build_steps(case, event, records) + action_steps)
    return CaseDetailResponse(
        case_id=case.case_id,
        question=case.question,
        context=case.context,
        options=case.options,
        risk_level=case.risk_level,
        status=case.status,
        evidence_refs=evidence_refs,
        decisions=[DecisionItem.model_validate(record) for record in records],
        event=None if event is None else _event_summary(event),
        steps=steps,
        actions=actions,
        evidence_chain=await _evidence_chain(sess, case_id, case_evidence, event),
    )


# ---- W4 EDP-028 闭环聚合辅助 ----


async def _all_linked_evidence(sess: AsyncSession, ref_type: str, ref_id: UUID):
    """按 (ref_type, ref_id) 取全量关联证据（游标翻页至尽；与既有
    evidence_refs 的 links 语义一致）。"""
    items = []
    cursor: str | None = None
    while True:
        page = await evidence_service.query_records(
            sess, ref_type=ref_type, ref_id=ref_id, limit=MAX_LIMIT, cursor=cursor
        )
        items.extend(page.items)
        cursor = page.next_cursor
        if cursor is None:
            return items


async def _source_event(sess: AsyncSession, source_id: str | None):
    """source_id → 源事件 ORM 行；空/非 UUID/事件不可见（RLS）→ None。"""
    if not source_id:
        return None
    event_id = _as_uuid(source_id)
    if event_id is None:
        return None
    return await events_service.get_event(sess, event_id)


def _event_summary(event) -> CaseEventSummary:
    """事件摘要：summary 复用 ebms exceptions 的 coalesce 派生
    （data.summary → data.reason → event_type）。"""
    summary = event.data.get("summary") or event.data.get("reason") or event.event_type
    return CaseEventSummary(
        event_id=event.event_id,
        event_type=event.event_type,
        result_type=event.result_type,
        risk_level=event.risk_level,
        summary=str(summary),
        occurred_at=event.occurred_at,
    )


def _has_human_only_edge(status: str) -> bool:
    """当前 status 的出边是否存在 Human-Only 转移（actions.TRANSITIONS 单点；
    仅 APPROVED/COMPLETED 为 True——对应 EXECUTING/VERIFIED 两条 Human-Only
    边；逐转移明细经审计页 ACTION_UPDATE 可查，最小版留痕）。"""
    return any(actions_service.TRANSITIONS.get(status, {}).values())


async def _case_actions(
    sess: AsyncSession, case_id: UUID
) -> tuple[list[CaseActionItem], list[CaseStepItem]]:
    """案例关联行动全量（创建时间升序）：actions 投影（allowed_to 经
    actions_service 单点）+ 每行动两个步骤节点（创建 + 当前状态快照）。"""
    rows = (
        (
            await sess.execute(
                select(
                    _ACTIONS.c.action_id,
                    _ACTIONS.c.title,
                    _ACTIONS.c.action_type,
                    _ACTIONS.c.status,
                    _ACTIONS.c.owner,
                    _ACTIONS.c.due_date,
                    _ACTIONS.c.created_at,
                    _ACTIONS.c.updated_at,
                    _ACTIONS.c.created_by,
                    _ACTIONS.c.updated_by,
                )
                .where(_ACTIONS.c.case_id == case_id)
                .order_by(_ACTIONS.c.created_at.asc(), _ACTIONS.c.action_id.asc())
            )
        )
        .mappings()
        .all()
    )

    actions: list[CaseActionItem] = []
    steps: list[CaseStepItem] = []
    for row in rows:
        status = row["status"]
        actions.append(
            CaseActionItem(
                action_id=row["action_id"],
                title=row["title"],
                status=status,
                owner=row["owner"],
                due_date=row["due_date"],
                allowed_to=[
                    ActionTransitionRef(**item)
                    for item in actions_service.allowed_to(status)
                ],
            )
        )
        steps.append(
            CaseStepItem(
                step_type="ACTION",
                occurred_at=row["created_at"],
                actor=row["created_by"] or "system",
                title=row["title"],
                detail=f"创建行动（{row['action_type']}）",
            )
        )
        steps.append(
            CaseStepItem(
                step_type="ACTION",
                occurred_at=row["updated_at"],
                actor=row["updated_by"] or row["created_by"] or "system",
                title=f"当前状态：{status}",
                human_only=_has_human_only_edge(status),
            )
        )
    return actions, steps


def _decision_title(options: list, chosen_option: str) -> str:
    """决策步骤标题（含 chosen_option）：选项 key 可解析 label 时并入展示。"""
    for option in options:
        if isinstance(option, dict) and option.get("key") == chosen_option:
            return f"决策：{option.get('label', chosen_option)}（{chosen_option}）"
    return f"决策：{chosen_option}"


def _build_steps(case: Case, event, records) -> list[CaseStepItem]:
    """EVENT / CASE_CREATED / DECISION 节点（ACTION 节点由 _case_actions 附）。"""
    steps: list[CaseStepItem] = []
    if event is not None:
        steps.append(
            CaseStepItem(
                step_type="EVENT",
                occurred_at=event.occurred_at,
                actor=event.source_system or "system",
                title=_event_summary(event).summary,
                detail=event.event_type,
            )
        )
    steps.append(
        CaseStepItem(
            step_type="CASE_CREATED",
            occurred_at=case.created_at,
            actor=case.created_by or "system",
            title=(
                f"创建决策案例 {case.case_no}" if case.case_no else "创建决策案例"
            ),
            detail=case.question,
        )
    )
    for record in records:
        steps.append(
            CaseStepItem(
                step_type="DECISION",
                occurred_at=record.decision_time,
                actor=record.decided_by,
                title=_decision_title(case.options, record.chosen_option),
                detail=record.comment,
                human_only=True,
            )
        )
    return steps


def _sort_steps(steps: list[CaseStepItem]) -> list[CaseStepItem]:
    """时间升序（occurred_at，插入序 tiebreak——同刻节点保持构造顺序）。"""
    return [
        step
        for _, step in sorted(
            enumerate(steps), key=lambda pair: (pair[1].occurred_at, pair[0])
        )
    ]


async def _evidence_chain(
    sess: AsyncSession,
    case_id: UUID,
    case_evidence,
    event,
) -> list[EvidenceChainItem]:
    """四层证据链（设计 7.6）：RESULT（ref_id=source 事件）/ DECISION
    （ref_id=case）/ EVIDENCE（ref_type=CASE 集合，复用详情既有查询）/
    SOURCE（(source_system, source_record_id) 投影去重，无 evidence_id）。"""
    source_event_id = _as_uuid(str(event.event_id)) if event is not None else None
    layers: list[tuple[str, list]] = [
        (
            "RESULT",
            (
                await _all_linked_evidence(sess, RESULT_REF_TYPE, source_event_id)
                if source_event_id is not None
                else []
            ),
        ),
        (
            "DECISION",
            await _all_linked_evidence(sess, DECISION_REF_TYPE, case_id),
        ),
        ("EVIDENCE", case_evidence),
    ]

    chain: list[EvidenceChainItem] = []
    source_keys: list[tuple[str, str]] = []
    seen_sources: set[tuple[str, str]] = set()
    for layer, items in layers:
        for item in items:
            chain.append(
                EvidenceChainItem(
                    layer=layer,
                    evidence_id=item.evidence_id,
                    checksum=item.checksum,
                    source_system=item.source_system,
                    source_record_id=item.source_record_id,
                    title=f"{item.source_system}:{item.source_record_id}",
                )
            )
            key = (item.source_system, item.source_record_id)
            if key not in seen_sources:
                seen_sources.add(key)
                source_keys.append(key)
    chain.extend(
        EvidenceChainItem(
            layer="SOURCE",
            source_system=source_system,
            source_record_id=source_record_id,
            title=f"{source_system}:{source_record_id}",
        )
        for source_system, source_record_id in source_keys
    )
    return chain


async def submit_record(
    sess: AsyncSession,
    principal: Principal,
    case_id: UUID,
    req: DecisionCreateRequest,
) -> tuple[DecisionRecord, Case] | None:
    """提交决策记录（Human-Only）。

    Raises:
        EdpError(GUARD_POLICY_DENIED): principal.kind != HUMAN（先落
        GUARD_DENIED 审计）；
        EdpError(CONFLICT): 案例非 OPEN。

    Returns:
        (决策记录, 案例)；case_id 不存在（含跨租户）→ None。
    """
    if principal.kind != "HUMAN":
        await record_guard_denied(
            principal,
            path=None,
            reason=HUMAN_ONLY_REASON,
            resource_id=str(case_id),
        )
        raise EdpError.guard_policy_denied(HUMAN_ONLY_MESSAGE)

    case = await sess.get(Case, case_id)
    if case is None:
        return None
    if case.status != "OPEN":
        raise EdpError.conflict(f"案例非 OPEN 状态：{case.status}")

    decided_at = datetime.now(UTC)
    record = DecisionRecord(
        decision_id=uuid4(),
        tenant_id=principal.tenant_id,
        case_id=case.case_id,
        chosen_option=req.chosen_option,
        decision_type=req.decision_type,
        decided_by=principal.id,
        decision_time=decided_at,
        comment=req.comment,
        created_by=principal.id,
        updated_by=principal.id,
    )
    sess.add(record)
    case.status = "DECIDED"
    case.decided_at = decided_at
    case.updated_by = principal.id
    case.updated_at = func.now()
    await sess.flush()
    return record, case


def _as_uuid(value: str) -> UUID | None:
    """宽松解析：非 UUID 形态 → None（source_id 允许任意文本）。"""
    try:
        return UUID(value)
    except (TypeError, ValueError):
        return None


def _parse_anchor(decoded: dict) -> tuple[datetime, UUID] | None:
    """cursor 载荷 → (created_at, case_id)；缺字段/格式非法 → None。"""
    try:
        return datetime.fromisoformat(str(decoded["c"])), UUID(str(decoded["i"]))
    except (KeyError, TypeError, ValueError):
        return None
