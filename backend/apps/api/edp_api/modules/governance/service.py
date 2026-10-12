"""governance 服务（V1.2 Phase 2）：规则/别名/分类注册 + 准入状态机 + 审核。

分层：
- 注册面（T10~T12）：cleaning_rules / entity_aliases / dimensions /
  taxonomies / tags / object_classifications 的 CRUD（版本化生效区间）；
- 管道面（T07/T08）：ingest 经 ``ensure_admission_pipeline`` 把对象推进至
  CLASSIFIED（RAW→清洗→标准化→分类 同步管线，无 worker 调度）；
- 审核面（T13/T14/T15）：source_review（A2）/ management_review（A3）/
  archive（A4）——Human-Only，机器检查 + 人工决策，六结果映射状态；
  机器 FAIL → DataQuality.Exception 事件（T16 门禁）阻断 APPROVED 推进。

状态机：TRANSITIONS 与契约 contracts/governance/admission-state.schema.json
definitions.transitions 一致（契约未覆盖的异常态出边：RETURNED→CLEANED/
STANDARDIZED/CLASSIFIED、SUSPENDED→SOURCE_REVIEW/MANAGEMENT_REVIEW——
阶段一裁定，见方案 T05 注 1）。任何状态推进写 ``governance.admission.
{State}`` 事件（events.ingest_batch internal=True 写通道）；审核动作
record_explicit ADMISSION_REVIEW 审计；ORM 行变更由审计切面自动捕获。

RLS：governance.* 全表 FORCE RLS——调用方会话需 bind_tenant；跨租户行
不可见（读 API 与不存在同义 404/空列表）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core import db as core_db
from edp_api.core.db import bind_tenant
from edp_api.core.errors import EdpError
from edp_api.core.pagination import Page, decode_cursor, encode_cursor
from edp_api.core.security.principal import Principal
from edp_api.modules.audit import service as audit_service
from edp_api.modules.events import service as events_service
from edp_api.modules.events.schemas import EventIn
from edp_api.modules.governance import cleaning
from edp_api.modules.governance.models import (
    AdmissionRecord,
    CleaningRule,
    CleanRecord,
    Dimension,
    EntityAlias,
    ObjectClassification,
    ObjectTag,
    RawRecord,
    ReviewRecord,
    Tag,
    Taxonomy,
)
from edp_api.modules.governance.schemas import (
    ClassificationCreate,
    CleaningRuleCreate,
    DimensionCreate,
    EntityAliasCreate,
    ReviewRequest,
    TagCreate,
    TaxonomyCreate,
)
from edp_api.modules.lineage import service as lineage_service

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

EVENT_SOURCE_SYSTEM = "edp-governance"
EVENT_ACTOR_ID = "service:governance"
DQ_EXCEPTION_EVENT_TYPE = "DataQuality.Exception"
REVIEW_AUDIT_ACTION = "ADMISSION_REVIEW"
GUARD_DENIED_RESOURCE_TYPE = "governance.admission_records"

# 状态机（与契约 definitions.transitions 一致 + 异常态出边，见模块 docstring）
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "RECEIVED": ("PROFILED", "REJECTED"),
    "PROFILED": ("CLEANED", "RETURNED", "SUSPENDED"),
    "CLEANED": ("STANDARDIZED", "RETURNED"),
    "STANDARDIZED": ("CLASSIFIED", "RETURNED"),
    "CLASSIFIED": ("SOURCE_REVIEW", "RETURNED"),
    "SOURCE_REVIEW": ("SOURCE_APPROVED", "REJECTED", "RETURNED", "SUSPENDED", "ESCALATED"),
    "SOURCE_APPROVED": ("MANAGEMENT_REVIEW", "SUSPENDED"),
    "MANAGEMENT_REVIEW": (
        "MANAGEMENT_APPROVED",
        "REJECTED",
        "RETURNED",
        "SUSPENDED",
        "ESCALATED",
    ),
    "MANAGEMENT_APPROVED": ("OFFICIAL", "SUSPENDED"),
    "OFFICIAL": ("ARCHIVED", "RETURNED"),
    "ARCHIVED": (),
    "RETURNED": ("CLEANED", "STANDARDIZED", "CLASSIFIED"),
    "REJECTED": (),
    "SUSPENDED": ("SOURCE_REVIEW", "MANAGEMENT_REVIEW"),
    "ESCALATED": (),
}

# 人工决策 → 目标状态（A2/A3 共用映射；FAIL 门禁在调用方先行阻断）
_DECISION_TARGET: dict[str, dict[str, str]] = {
    "SOURCE_REVIEW": {
        "APPROVED": "SOURCE_APPROVED",
        "APPROVED_WITH_WARNING": "SOURCE_APPROVED",
        "RETURN_FOR_CORRECTION": "RETURNED",
        "REJECTED": "REJECTED",
        "SUSPENDED": "SUSPENDED",
        "ESCALATED": "ESCALATED",
    },
    "MANAGEMENT_REVIEW": {
        "APPROVED": "MANAGEMENT_APPROVED",
        "APPROVED_WITH_WARNING": "MANAGEMENT_APPROVED",
        "RETURN_FOR_CORRECTION": "RETURNED",
        "REJECTED": "REJECTED",
        "SUSPENDED": "SUSPENDED",
        "ESCALATED": "ESCALATED",
    },
}


# ---- 管道面（T07/T08） ----


async def ensure_admission_pipeline(
    sess: AsyncSession, tenant_id: UUID, object_id: UUID
) -> AdmissionRecord | None:
    """管道同步推进：建行（RECEIVED，幂等）→ 走到 CLASSIFIED。

    逐边推进（RECEIVED→PROFILED→CLEANED→STANDARDIZED→CLASSIFIED）；当前态
    不在路径上（已审核/异常态）即停——不倒退、不覆盖人工状态。同步段不发
    状态事件（记录级审计由切面自动留痕，防 SNAPSHOT 语义污染事件计数基线），
    事件自人工审核段（SOURCE_REVIEW 起）产生。
    """
    admission = await _ensure_row(sess, tenant_id, object_id)
    if admission is None:
        return None
    for target in ("PROFILED", "CLEANED", "STANDARDIZED", "CLASSIFIED"):
        if target not in TRANSITIONS.get(admission.state, ()):
            break
        await _transition(
            sess, tenant_id, admission, target, actor=EVENT_ACTOR_ID, emit_event=False
        )
    return admission


async def _ensure_row(
    sess: AsyncSession, tenant_id: UUID, object_id: UUID
) -> AdmissionRecord | None:
    """查/建 admission 行（(tenant_id, object_id) 唯一；ON CONFLICT 幂等）。

    RLS 会话下跨租户 INSERT 无冲突可能；INSERT 前 SELECT 亦被 RLS 收敛。
    """
    admission = (
        await sess.execute(
            select(AdmissionRecord).where(
                AdmissionRecord.tenant_id == tenant_id,
                AdmissionRecord.object_id == object_id,
            )
        )
    ).scalar_one_or_none()
    if admission is not None:
        return admission
    admission = AdmissionRecord(
        admission_id=uuid4(),
        tenant_id=tenant_id,
        object_id=object_id,
        state="RECEIVED",
        created_by=EVENT_ACTOR_ID,
        updated_by=EVENT_ACTOR_ID,
    )
    sess.add(admission)
    await sess.flush()
    return admission


async def _transition(
    sess: AsyncSession,
    tenant_id: UUID,
    admission: AdmissionRecord,
    target: str,
    *,
    actor: str,
    emit_event: bool = True,
) -> None:
    """状态推进（边校验 + ORM 更新 + 可选事件）。调用方负责 target 合法性。"""
    if target not in TRANSITIONS.get(admission.state, ()):
        raise EdpError.invalid_transition(
            f"非法状态转移：{admission.state} → {target}",
            extra={"allowed_to": list(TRANSITIONS.get(admission.state, ()))},
        )
    admission.state = target
    admission.version += 1
    admission.updated_by = actor
    admission.updated_at = datetime.now(UTC)  # Python 值：响应直接读取（func.now() 会触发同步 IO）
    await sess.flush()
    if emit_event:
        await _record_transition_event(sess, tenant_id, admission, target)


async def _record_transition_event(
    sess: AsyncSession, tenant_id: UUID, admission: AdmissionRecord, state: str
) -> None:
    """状态推进事件：governance.admission.{State}（UUIDv5 幂等——
    occurred_at 取推进时刻，同 (admission_id, state, occurred_at) 重放恒
    同 event_id；幂等键稳定）。object 锚点 = admission.object_id。"""
    occurred_at = datetime.now(UTC)
    await events_service.ingest_batch(
        sess,
        Principal(id=EVENT_ACTOR_ID, kind="SERVICE", tenant_id=tenant_id),
        f"governance-admission:{admission.admission_id}:{state}:{occurred_at.isoformat()}",
        [
            EventIn(
                event_type=f"governance.admission.{state}",
                object_id=admission.object_id,
                source_system=EVENT_SOURCE_SYSTEM,
                occurred_at=occurred_at,
                actor_type="SERVICE",
                actor_id=EVENT_ACTOR_ID,
                data={
                    "admission_id": str(admission.admission_id),
                    "state": state,
                },
            )
        ],
        internal=True,
    )


# ---- 注册面（T10~T12） ----


async def create_cleaning_rule(
    sess: AsyncSession, principal: Principal, req: CleaningRuleCreate
) -> CleaningRule:
    """规则注册：同 (object_type, field, rule_name) 新版本——旧版本收
    effective_to = 新版本 effective_from（版本化生效区间）。"""
    effective_from = req.effective_from or datetime.now(UTC)
    previous = (
        await sess.execute(
            select(CleaningRule)
            .where(
                CleaningRule.tenant_id == principal.tenant_id,
                CleaningRule.object_type == req.object_type,
                func.coalesce(CleaningRule.field, "") == (req.field or ""),
                CleaningRule.rule_name == req.rule_name,
                CleaningRule.effective_to.is_(None),
            )
            .order_by(CleaningRule.version.desc())
        )
    ).scalars().first()
    if previous is not None:
        previous.effective_to = effective_from
        previous.updated_by = principal.id
        previous.updated_at = func.now()
    rule = CleaningRule(
        rule_id=uuid4(),
        tenant_id=principal.tenant_id,
        rule_name=req.rule_name,
        object_type=req.object_type,
        field=req.field,
        rule_type=req.rule_type,
        condition=req.condition,
        transformation=req.transformation,
        severity=req.severity,
        owner=req.owner,
        version=(previous.version + 1) if previous is not None else 1,
        effective_from=effective_from,
        auto_fix=req.auto_fix,
        review_required=req.review_required,
        created_by=principal.id,
        updated_by=principal.id,
    )
    sess.add(rule)
    await sess.flush()
    return rule


async def query_cleaning_rules(
    sess: AsyncSession,
    *,
    object_type: str | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[CleaningRule]:
    """规则列表（object_type 过滤 + 游标分页 effective_from DESC tiebreak）。"""
    limit = max(1, min(limit, MAX_LIMIT))
    stmt = select(CleaningRule)
    if object_type:
        stmt = stmt.where(CleaningRule.object_type == object_type)
    decoded = decode_cursor(cursor)
    if decoded is not None:
        try:
            anchor_from = datetime.fromisoformat(str(decoded["f"]))
            anchor_id = UUID(str(decoded["i"]))
            stmt = stmt.where(
                or_(
                    CleaningRule.effective_from < anchor_from,
                    and_(
                        CleaningRule.effective_from == anchor_from,
                        CleaningRule.rule_id < anchor_id,
                    ),
                )
            )
        except (KeyError, TypeError, ValueError):
            pass
    stmt = stmt.order_by(
        CleaningRule.effective_from.desc(), CleaningRule.rule_id.desc()
    ).limit(limit + 1)
    rows = (await sess.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"f": last.effective_from.isoformat(), "i": str(last.rule_id)}
        )
    return Page(items=list(page_rows), next_cursor=next_cursor)


async def create_alias(
    sess: AsyncSession, principal: Principal, req: EntityAliasCreate
) -> EntityAlias:
    """别名注册（(tenant, object_type, alias) 唯一 → 409 CONFLICT）。"""
    exists = (
        await sess.execute(
            select(EntityAlias.alias_id).where(
                EntityAlias.tenant_id == principal.tenant_id,
                EntityAlias.object_type == req.object_type,
                EntityAlias.alias == req.alias,
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise EdpError.conflict(f"别名已存在：{req.alias}")
    alias = EntityAlias(
        alias_id=uuid4(),
        tenant_id=principal.tenant_id,
        object_type=req.object_type,
        alias=req.alias,
        canonical_ref=req.canonical_ref,
        source=req.source,
        confidence=req.confidence,
        approved_by=principal.id if req.source == "HUMAN_MAINTAINED" else None,
        approved_at=datetime.now(UTC) if req.source == "HUMAN_MAINTAINED" else None,
        created_by=principal.id,
        updated_by=principal.id,
    )
    sess.add(alias)
    await sess.flush()
    return alias


async def query_aliases(
    sess: AsyncSession,
    *,
    object_type: str | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[EntityAlias]:
    """别名列表（object_type 过滤 + 游标分页 created_at DESC tiebreak）。"""
    limit = max(1, min(limit, MAX_LIMIT))
    stmt = select(EntityAlias)
    if object_type:
        stmt = stmt.where(EntityAlias.object_type == object_type)
    decoded = decode_cursor(cursor)
    if decoded is not None:
        try:
            anchor_created = datetime.fromisoformat(str(decoded["c"]))
            anchor_id = UUID(str(decoded["i"]))
            stmt = stmt.where(
                or_(
                    EntityAlias.created_at < anchor_created,
                    and_(
                        EntityAlias.created_at == anchor_created,
                        EntityAlias.alias_id < anchor_id,
                    ),
                )
            )
        except (KeyError, TypeError, ValueError):
            pass
    stmt = stmt.order_by(EntityAlias.created_at.desc(), EntityAlias.alias_id.desc()).limit(
        limit + 1
    )
    rows = (await sess.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"c": last.created_at.isoformat(), "i": str(last.alias_id)}
        )
    return Page(items=list(page_rows), next_cursor=next_cursor)


async def create_dimension(
    sess: AsyncSession, principal: Principal, req: DimensionCreate
) -> Dimension:
    dimension = Dimension(
        dimension_id=uuid4(),
        tenant_id=principal.tenant_id,
        code=req.code,
        name=req.name,
        created_by=principal.id,
        updated_by=principal.id,
    )
    sess.add(dimension)
    await sess.flush()
    return dimension


async def list_dimensions(sess: AsyncSession) -> list[Dimension]:
    return list(
        (
            await sess.execute(
                select(Dimension).order_by(Dimension.code.asc(), Dimension.dimension_id.asc())
            )
        ).scalars().all()
    )


async def create_taxonomy(
    sess: AsyncSession, principal: Principal, req: TaxonomyCreate
) -> Taxonomy:
    if not await _dimension_exists(sess, principal.tenant_id, req.dimension_id):
        raise EdpError.validation_error(f"维度不存在：{req.dimension_id}")
    if req.parent_id is not None and not await _taxonomy_exists(
        sess, principal.tenant_id, req.parent_id
    ):
        raise EdpError.validation_error(f"父节点不存在：{req.parent_id}")
    node = Taxonomy(
        taxonomy_id=uuid4(),
        tenant_id=principal.tenant_id,
        dimension_id=req.dimension_id,
        parent_id=req.parent_id,
        label=req.label,
        created_by=principal.id,
        updated_by=principal.id,
    )
    sess.add(node)
    await sess.flush()
    return node


async def list_taxonomies(
    sess: AsyncSession, *, dimension_id: UUID | None = None
) -> list[Taxonomy]:
    stmt = select(Taxonomy)
    if dimension_id is not None:
        stmt = stmt.where(Taxonomy.dimension_id == dimension_id)
    return list(
        (
            await sess.execute(
                stmt.order_by(Taxonomy.label.asc(), Taxonomy.taxonomy_id.asc())
            )
        ).scalars().all()
    )


async def create_tag(sess: AsyncSession, principal: Principal, req: TagCreate) -> Tag:
    tag = Tag(
        tag_id=uuid4(),
        tenant_id=principal.tenant_id,
        code=req.code,
        name=req.name,
        created_by=principal.id,
        updated_by=principal.id,
    )
    sess.add(tag)
    await sess.flush()
    return tag


async def list_tags(sess: AsyncSession) -> list[Tag]:
    return list(
        (
            await sess.execute(select(Tag).order_by(Tag.code.asc(), Tag.tag_id.asc()))
        ).scalars().all()
    )


async def create_classification(
    sess: AsyncSession, principal: Principal, req: ClassificationCreate
) -> ObjectClassification:
    """对象分类挂接：同 (object, dimension, label) 新版本——旧版本收
    effective_to；source=AI_ASSISTED 仅作建议（approved_* 置空）。"""
    effective_from = datetime.now(UTC)
    previous = (
        await sess.execute(
            select(ObjectClassification)
            .where(
                ObjectClassification.tenant_id == principal.tenant_id,
                ObjectClassification.object_id == req.object_id,
                func.coalesce(ObjectClassification.dimension_id, UUID(int=0))
                == (req.dimension_id or UUID(int=0)),
                ObjectClassification.label == req.label,
                ObjectClassification.effective_to.is_(None),
            )
            .order_by(ObjectClassification.version.desc())
        )
    ).scalars().first()
    if previous is not None:
        previous.effective_to = effective_from
        previous.updated_by = principal.id
        previous.updated_at = func.now()
    classification = ObjectClassification(
        classification_id=uuid4(),
        tenant_id=principal.tenant_id,
        object_id=req.object_id,
        dimension_id=req.dimension_id,
        taxonomy_id=req.taxonomy_id,
        label=req.label,
        source=req.source,
        rule_ref=req.rule_ref,
        confidence=req.confidence,
        version=(previous.version + 1) if previous is not None else 1,
        effective_from=effective_from,
        approved_by=principal.id if req.source != "AI_ASSISTED" else None,
        approved_at=effective_from if req.source != "AI_ASSISTED" else None,
        created_by=principal.id,
        updated_by=principal.id,
    )
    sess.add(classification)
    await sess.flush()
    return classification


async def list_classifications(
    sess: AsyncSession, *, object_id: UUID | None = None
) -> list[ObjectClassification]:
    stmt = select(ObjectClassification).where(ObjectClassification.effective_to.is_(None))
    if object_id is not None:
        stmt = stmt.where(ObjectClassification.object_id == object_id)
    return list(
        (
            await sess.execute(
                stmt.order_by(
                    ObjectClassification.label.asc(),
                    ObjectClassification.classification_id.asc(),
                )
            )
        ).scalars().all()
    )


async def query_raw_records(
    sess: AsyncSession,
    *,
    object_type: str | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[RawRecord]:
    """RAW 只读列表（object_type 过滤 + 游标分页 received_at DESC）。"""
    limit = max(1, min(limit, MAX_LIMIT))
    stmt = select(RawRecord)
    if object_type:
        stmt = stmt.where(RawRecord.object_type == object_type)
    decoded = decode_cursor(cursor)
    if decoded is not None:
        try:
            anchor_received = datetime.fromisoformat(str(decoded["r"]))
            anchor_id = UUID(str(decoded["i"]))
            stmt = stmt.where(
                or_(
                    RawRecord.received_at < anchor_received,
                    and_(
                        RawRecord.received_at == anchor_received,
                        RawRecord.raw_record_id < anchor_id,
                    ),
                )
            )
        except (KeyError, TypeError, ValueError):
            pass
    stmt = stmt.order_by(RawRecord.received_at.desc(), RawRecord.raw_record_id.desc()).limit(
        limit + 1
    )
    rows = (await sess.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"r": last.received_at.isoformat(), "i": str(last.raw_record_id)}
        )
    return Page(items=list(page_rows), next_cursor=next_cursor)


async def _dimension_exists(sess: AsyncSession, tenant_id: UUID, dimension_id: UUID) -> bool:
    return (
        await sess.execute(
            select(Dimension.dimension_id).where(
                Dimension.tenant_id == tenant_id,
                Dimension.dimension_id == dimension_id,
            )
        )
    ).scalar_one_or_none() is not None


async def _taxonomy_exists(sess: AsyncSession, tenant_id: UUID, taxonomy_id: UUID) -> bool:
    return (
        await sess.execute(
            select(Taxonomy.taxonomy_id).where(
                Taxonomy.tenant_id == tenant_id, Taxonomy.taxonomy_id == taxonomy_id
            )
        )
    ).scalar_one_or_none() is not None


# ---- 审核面（T13/T14/T15） ----


async def attach_tag(
    sess: AsyncSession,
    principal: Principal,
    *,
    object_id: UUID,
    tag_id: UUID,
) -> ObjectTag:
    """对象标签挂接（(tenant, object, tag) 唯一 → 已挂返回既有行）。"""
    existing = (
        await sess.execute(
            select(ObjectTag).where(
                ObjectTag.tenant_id == principal.tenant_id,
                ObjectTag.object_id == object_id,
                ObjectTag.tag_id == tag_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    tag = (
        await sess.execute(
            select(Tag.tag_id).where(
                Tag.tenant_id == principal.tenant_id, Tag.tag_id == tag_id
            )
        )
    ).scalar_one_or_none()
    if tag is None:
        raise EdpError.validation_error(f"标签不存在：{tag_id}")
    object_row = (
        await sess.execute(
            text("SELECT 1 FROM master.business_objects WHERE object_id = :oid"),
            {"oid": object_id},
        )
    ).scalar_one_or_none()
    if object_row is None:
        raise EdpError.validation_error(f"对象不存在：{object_id}")
    link = ObjectTag(
        object_tag_id=uuid4(),
        tenant_id=principal.tenant_id,
        object_id=object_id,
        tag_id=tag_id,
        created_by=principal.id,
    )
    sess.add(link)
    await sess.flush()
    return link


async def list_object_tags(
    sess: AsyncSession, *, object_id: UUID | None = None
) -> list[ObjectTag]:
    stmt = select(ObjectTag)
    if object_id is not None:
        stmt = stmt.where(ObjectTag.object_id == object_id)
    return list(
        (
            await sess.execute(
                stmt.order_by(ObjectTag.created_at.asc(), ObjectTag.object_tag_id.asc())
            )
        ).scalars().all()
    )


async def auto_source_machine_review(
    sess: AsyncSession, tenant_id: UUID, *, batch_size: int = 100
) -> dict[str, int]:
    """worker 调度入口（T32）：CLASSIFIED 自动机器预审。

    PASS/WARNING → 推进 SOURCE_REVIEW（machine_result/quality_score 落库，
    事件留痕）；FAIL → 留 CLASSIFIED + DataQuality.Exception（独立会话）。
    返回 {advanced, blocked}。
    """
    rows = (
        (
            await sess.execute(
                select(AdmissionRecord)
                .where(
                    AdmissionRecord.tenant_id == tenant_id,
                    AdmissionRecord.state == "CLASSIFIED",
                )
                .order_by(
                    AdmissionRecord.updated_at.asc(), AdmissionRecord.admission_id.asc()
                )
                .limit(batch_size)
            )
        )
        .scalars()
        .all()
    )
    advanced = 0
    blocked = 0
    for admission in rows:
        machine = await _source_machine_check(sess, admission)
        if machine["verdict"] == "FAIL":
            blocked += 1
            await _record_dq_exception(sess, admission, machine)
            continue
        admission.machine_result = machine
        admission.quality_score = machine["quality_score"]
        await _transition(
            sess, tenant_id, admission, "SOURCE_REVIEW", actor=EVENT_ACTOR_ID
        )
        advanced += 1
    await sess.flush()
    return {"advanced": advanced, "blocked": blocked}


async def get_admission(
    sess: AsyncSession, admission_id: UUID
) -> AdmissionRecord | None:
    """准入记录详情；不存在（含跨租户，RLS）→ None。"""
    return (
        await sess.execute(
            select(AdmissionRecord).where(AdmissionRecord.admission_id == admission_id)
        )
    ).scalar_one_or_none()


async def query_admissions(
    sess: AsyncSession,
    *,
    state: str | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[AdmissionRecord]:
    """准入列表（state 过滤 + 游标分页 updated_at DESC tiebreak）。"""
    limit = max(1, min(limit, MAX_LIMIT))
    stmt = select(AdmissionRecord)
    if state:
        stmt = stmt.where(AdmissionRecord.state == state)
    decoded = decode_cursor(cursor)
    if decoded is not None:
        try:
            anchor_updated = datetime.fromisoformat(str(decoded["u"]))
            anchor_id = UUID(str(decoded["i"]))
            stmt = stmt.where(
                or_(
                    AdmissionRecord.updated_at < anchor_updated,
                    and_(
                        AdmissionRecord.updated_at == anchor_updated,
                        AdmissionRecord.admission_id < anchor_id,
                    ),
                )
            )
        except (KeyError, TypeError, ValueError):
            pass
    stmt = stmt.order_by(
        AdmissionRecord.updated_at.desc(), AdmissionRecord.admission_id.desc()
    ).limit(limit + 1)
    rows = (await sess.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"u": last.updated_at.isoformat(), "i": str(last.admission_id)}
        )
    return Page(items=list(page_rows), next_cursor=next_cursor)


async def list_reviews(
    sess: AsyncSession, admission_id: UUID
) -> list[ReviewRecord]:
    return list(
        (
            await sess.execute(
                select(ReviewRecord)
                .where(ReviewRecord.admission_id == admission_id)
                .order_by(ReviewRecord.reviewed_at.asc(), ReviewRecord.review_id.asc())
            )
        ).scalars().all()
    )


async def record_guard_denied(
    principal: Principal,
    *,
    path: str | None,
    reason: str,
    resource_id: str | None,
) -> None:
    """独立会话落 GUARD_DENIED 审计（Human-Only 拒绝路径；与 decisions.
    record_guard_denied 同构——模块间不引 decisions 避免环）。"""
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


async def source_review(
    sess: AsyncSession,
    principal: Principal,
    admission_id: UUID,
    req: ReviewRequest,
    *,
    path: str | None = None,
) -> AdmissionRecord | None:
    """A2 本系统人机共审：机器预审 → 人工决策 → 状态推进。

    状态要求 CLASSIFIED；机器 FAIL（T16 门禁）→ 400 阻断不推进并写
    DataQuality.Exception 事件；WARNING 允许人工裁决推进。Human-Only。
    """
    if principal.kind != "HUMAN":
        await record_guard_denied(
            principal, path=path, reason="Human-Only", resource_id=str(admission_id)
        )
        raise EdpError.guard_policy_denied("该操作仅限人工执行")
    admission = await get_admission(sess, admission_id)
    if admission is None:
        return None
    if admission.state not in ("CLASSIFIED", "SOURCE_REVIEW"):
        raise EdpError.conflict(f"当前状态不可本系统审核：{admission.state}")

    if admission.state == "CLASSIFIED":
        # API 直审路径：内联机器预审
        machine = await _source_machine_check(sess, admission)
        if machine["verdict"] == "FAIL":
            await _record_dq_exception(sess, admission, machine)
            raise EdpError.validation_error(
                "机器预审未通过（DataQuality.Exception 已产生）",
                extra={"verdict": "FAIL", "quality_score": machine["quality_score"]},
            )
    else:
        # worker 预审路径（T32）：SOURCE_REVIEW 起态——沿用已落库的机器结果
        machine = admission.machine_result or await _source_machine_check(sess, admission)
        if machine.get("verdict") == "FAIL":
            raise EdpError.validation_error(
                "机器预审未通过（DataQuality.Exception 已产生）",
                extra={"verdict": "FAIL", "quality_score": machine.get("quality_score")},
            )

    await _apply_review(
        sess, principal, admission, "SOURCE_REVIEW", req, machine
    )
    return admission


async def management_review(
    sess: AsyncSession,
    principal: Principal,
    admission_id: UUID,
    req: ReviewRequest,
    *,
    path: str | None = None,
) -> AdmissionRecord | None:
    """A3 管理系统人机复审：机器复审 → 人工确认 → 状态推进。

    状态要求 SOURCE_APPROVED；机器 FAIL → 阻断同上；APPROVED/
    APPROVED_WITH_WARNING → MANAGEMENT_APPROVED → OFFICIAL（OFFICIAL 时
    回填归档要素快照）。Human-Only。
    """
    if principal.kind != "HUMAN":
        await record_guard_denied(
            principal, path=path, reason="Human-Only", resource_id=str(admission_id)
        )
        raise EdpError.guard_policy_denied("该操作仅限人工执行")
    admission = await get_admission(sess, admission_id)
    if admission is None:
        return None
    if admission.state != "SOURCE_APPROVED":
        raise EdpError.conflict(f"当前状态不可管理系统复审：{admission.state}")

    machine = await _management_machine_check(sess, admission)
    if machine["verdict"] == "FAIL":
        await _record_dq_exception(sess, admission, machine)
        raise EdpError.validation_error(
            "机器复审未通过（DataQuality.Exception 已产生）",
            extra={"verdict": "FAIL", "quality_score": machine["quality_score"]},
        )

    await _apply_review(
        sess, principal, admission, "MANAGEMENT_REVIEW", req, machine
    )
    if admission.state == "MANAGEMENT_APPROVED":
        await _transition(sess, admission.tenant_id, admission, "OFFICIAL", actor=principal.id)
        await _mark_official(sess, principal, admission)
    return admission


async def archive(
    sess: AsyncSession,
    principal: Principal,
    admission_id: UUID,
    *,
    path: str | None = None,
) -> AdmissionRecord | None:
    """A4 归档：OFFICIAL → ARCHIVED，回填归档要素快照（各层版本引用）。"""
    if principal.kind != "HUMAN":
        await record_guard_denied(
            principal, path=path, reason="Human-Only", resource_id=str(admission_id)
        )
        raise EdpError.guard_policy_denied("该操作仅限人工执行")
    admission = await get_admission(sess, admission_id)
    if admission is None:
        return None
    if admission.state != "OFFICIAL":
        raise EdpError.conflict(f"当前状态不可归档：{admission.state}")
    await _fill_archive_snapshot(sess, admission)
    await _transition(sess, admission.tenant_id, admission, "ARCHIVED", actor=principal.id)
    admission.archived_at = datetime.now(UTC)
    await sess.flush()
    # 对象层回写（T19）：ARCHIVED 状态指针 + 显式审计（raw SQL 切面不可见）
    await sess.execute(
        text(
            "UPDATE master.business_objects SET layer_status = 'ARCHIVED'"
            " WHERE object_id = :oid"
        ),
        {"oid": admission.object_id},
    )
    await audit_service.record_explicit(
        sess,
        action="OBJECT_ARCHIVED",
        resource_type="master.business_objects",
        resource_id=str(admission.object_id),
        detail={"admission_id": str(admission.admission_id)},
        principal=principal,
    )
    return admission


async def _mark_official(
    sess: AsyncSession, principal: Principal, admission: AdmissionRecord
) -> None:
    """OFFICIAL 回写（T19/T20）：lineage 落行 → business_objects 三列回写
    （layer_status/official_version/lineage_id）→ 显式审计 OBJECT_OFFICIAL
    （raw SQL 更新切面不可见）。"""
    source_id = (
        await sess.execute(
            text(
                "SELECT source_id FROM master.business_objects WHERE object_id = :oid"
            ),
            {"oid": admission.object_id},
        )
    ).scalar_one_or_none()
    lineage = await lineage_service.record_official(
        sess,
        admission.tenant_id,
        source_record_id=source_id or f"object:{admission.object_id}",
        source_review_ref=await _latest_review_id(
            sess, admission.admission_id, "SOURCE_REVIEW"
        ),
        management_review_ref=await _latest_review_id(
            sess, admission.admission_id, "MANAGEMENT_REVIEW"
        ),
        official_version=str(admission.admission_id),
        operator=principal.id,
        classification_version=admission.classification_version,
    )
    await sess.execute(
        text(
            "UPDATE master.business_objects SET layer_status = 'CURATED',"
            " official_version = :v, lineage_id = :l WHERE object_id = :oid"
        ),
        {
            "v": str(admission.admission_id),
            "l": lineage.lineage_id,
            "oid": admission.object_id,
        },
    )
    await audit_service.record_explicit(
        sess,
        action="OBJECT_OFFICIAL",
        resource_type="master.business_objects",
        resource_id=str(admission.object_id),
        detail={
            "admission_id": str(admission.admission_id),
            "lineage_id": str(lineage.lineage_id),
        },
        principal=principal,
    )


async def _latest_review_id(
    sess: AsyncSession, admission_id: UUID, stage: str
) -> UUID | None:
    """准入记录最近一次指定阶段审核记录 id（lineage 引用）。"""
    return (
        await sess.execute(
            select(ReviewRecord.review_id)
            .where(
                ReviewRecord.admission_id == admission_id, ReviewRecord.stage == stage
            )
            .order_by(ReviewRecord.reviewed_at.desc(), ReviewRecord.review_id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _apply_review(
    sess: AsyncSession,
    principal: Principal,
    admission: AdmissionRecord,
    stage: str,
    req: ReviewRequest,
    machine: dict,
) -> None:
    """审核通用：推进进入审核态（CLASSIFIED→SOURCE_REVIEW /
    SOURCE_APPROVED→MANAGEMENT_REVIEW）→ 写 review_records + 回填审核字段
    → 按人工决策推进目标态。"""
    target = _DECISION_TARGET[stage][req.decision]
    review = ReviewRecord(
        review_id=uuid4(),
        tenant_id=admission.tenant_id,
        admission_id=admission.admission_id,
        stage=stage,
        machine_result=machine,
        human_decision=req.decision,
        human_reviewer=principal.id,
        comment=req.comment,
        evidence_refs=req.evidence_ids,
    )
    sess.add(review)
    admission.machine_result = machine
    admission.quality_score = machine["quality_score"]
    admission.review_result = req.decision
    if req.evidence_ids:
        admission.evidence_refs = [
            *admission.evidence_refs,
            *[e for e in req.evidence_ids if e not in admission.evidence_refs],
        ]
    if stage == "SOURCE_REVIEW":
        admission.source_human_reviewer = principal.id
        admission.source_reviewed_at = datetime.now(UTC)
    else:
        admission.management_human_reviewer = principal.id
        admission.management_reviewed_at = datetime.now(UTC)
    await sess.flush()
    await audit_service.record_explicit(
        sess,
        action=REVIEW_AUDIT_ACTION,
        resource_type="governance.admission_records",
        resource_id=str(admission.admission_id),
        detail={
            "stage": stage,
            "decision": req.decision,
            "quality_score": machine["quality_score"],
            "reviewer": principal.id,
        },
        principal=principal,
    )
    # 进入审核态（worker 预审已推进到 SOURCE_REVIEW 时跳过——自环不在
    # TRANSITIONS 内），随后按人工决策推进目标态
    if admission.state != stage:
        await _transition(sess, admission.tenant_id, admission, stage, actor=principal.id)
    await _transition(sess, admission.tenant_id, admission, target, actor=principal.id)


async def _source_machine_check(sess: AsyncSession, admission: AdmissionRecord) -> dict:
    """A2 机器预审（最小可执行版，spec §6）：完整性 / 清洗违规 / 重复 /
    主数据匹配（清洗规则 REFERENTIAL 覆盖）/ 分类与标签 / 质量分。"""
    violations: list[dict] = []
    raw = await _latest_raw(sess, admission)
    attributes = await _object_attributes(sess, admission.object_id)

    if raw is None or not attributes:
        violations.append({"code": "COMPLETENESS", "message": "对象或 RAW 缺失"})
    if raw is not None:
        cleaning_result = await cleaning.apply_cleaning(
            sess, admission.tenant_id, raw.object_type, raw.raw_payload
        )
        for v in cleaning_result.violations:
            violations.append(
                {
                    "code": v.rule_type,
                    "field": v.field,
                    "severity": v.severity,
                    "message": v.message,
                    "review_required": v.review_required,
                }
            )
    classifications = await list_classifications(sess, object_id=admission.object_id)
    if not classifications:
        violations.append(
            {
                "code": "CLASSIFICATION",
                "severity": "WARN",
                "message": "对象未挂接多维分类",
                "review_required": True,
            }
        )
    return _score_machine(violations)


async def _management_machine_check(
    sess: AsyncSession, admission: AdmissionRecord
) -> dict:
    """A3 机器复审（spec §6）：跨系统一致性（引用检查）/ Evidence 完整性 /
    历史合理性。"""
    violations: list[dict] = []
    evidence_count = (
        await sess.execute(
            text(
                "SELECT count(*) FROM evidence.records"
                " WHERE tenant_id = :tid AND object_id = :oid"
            ),
            {"tid": admission.tenant_id, "oid": admission.object_id},
        )
    ).scalar_one()
    if not evidence_count:
        violations.append(
            {"code": "EVIDENCE", "severity": "BLOCK", "message": "对象无 Evidence"}
        )
    raw = await _latest_raw(sess, admission)
    if raw is not None:
        if raw.source_timestamp > datetime.now(UTC):
            violations.append(
                {"code": "HISTORY", "severity": "WARN", "message": "occurred_at 晚于当前时间"}
            )
        if "delivery_date" in raw.raw_payload and isinstance(
            raw.raw_payload["delivery_date"], str
        ):
            try:
                delivery_date = datetime.fromisoformat(
                    raw.raw_payload["delivery_date"]
                ).replace(tzinfo=UTC)
                if delivery_date < datetime.now(UTC):
                    violations.append(
                        {
                            "code": "CROSS_SYSTEM",
                            "severity": "WARN",
                            "message": "交付窗口已过期（delivery_date 早于当前时间）",
                        }
                    )
            except ValueError:
                pass
    return _score_machine(violations)


def _score_machine(violations: list[dict]) -> dict:
    """质量分 = 100 − 5×WARN − 10×BLOCK（下限 0）；verdict 判定：
    BLOCK 存在或分数 < 60 → FAIL；WARN 存在 → WARNING；否则 PASS。"""
    block = sum(1 for v in violations if v.get("severity") == "BLOCK")
    warn = sum(1 for v in violations if v.get("severity") == "WARN")
    score = max(0, 100 - 5 * warn - 10 * block)
    if block or score < 60:
        verdict = "FAIL"
    elif warn:
        verdict = "WARNING"
    else:
        verdict = "PASS"
    return {
        "verdict": verdict,
        "quality_score": score,
        "exception_list": violations,
        "suggested_fix": [
            v.get("message") for v in violations if v.get("review_required")
        ],
    }


async def record_cleaning(
    sess: AsyncSession,
    tenant_id: UUID,
    object_id: UUID,
    raw_record_id: UUID | None,
    result,
) -> None:
    """清洗留痕落库（ingest 管道在对象 upsert 后调用）：每条 fix 一行
    clean_records（before/after 为字段级字典 + rule_refs [{rule_id,
    rule_version}]）；无 fix 不落行（零规则/恒等管道零开销）。"""
    if not result.fixes:
        return
    for fix in result.fixes:
        sess.add(
            CleanRecord(
                clean_record_id=uuid4(),
                tenant_id=tenant_id,
                object_id=object_id,
                raw_record_id=raw_record_id,
                before={fix.field: fix.before_value} if fix.field is not None else {},
                after={fix.field: fix.after_value} if fix.field is not None else {},
                rule_refs=[
                    {"rule_id": fix.rule_id, "rule_version": fix.rule_version}
                ],
                confidence=fix.confidence,
            )
        )
    await sess.flush()


async def record_dq_exception_independent(
    tenant_id: UUID,
    object_id: UUID,
    admission_id: UUID,
    version: int,
    machine: dict,
) -> None:
    """T16 门禁：机器 FAIL → DataQuality.Exception 事件（独立会话，防随
    请求事务回滚丢失——拒绝路径与 GUARD_DENIED 同构解耦）。"""
    try:
        session = core_db.get_session_local()()
        try:
            await bind_tenant(session, tenant_id)
            await events_service.ingest_batch(
                session,
                Principal(id=EVENT_ACTOR_ID, kind="SERVICE", tenant_id=tenant_id),
                f"governance-dq:{admission_id}:{version}",
                [
                    EventIn(
                        event_type=DQ_EXCEPTION_EVENT_TYPE,
                        object_id=object_id,
                        source_system=EVENT_SOURCE_SYSTEM,
                        occurred_at=datetime.now(UTC),
                        actor_type="SERVICE",
                        actor_id=EVENT_ACTOR_ID,
                        data={
                            "admission_id": str(admission_id),
                            "quality_score": machine["quality_score"],
                            "exception_list": machine["exception_list"],
                        },
                    )
                ],
                internal=True,
            )
            await session.commit()
        finally:
            await session.close()
    except Exception:
        logger.warning("DataQuality.Exception 事件落库失败", exc_info=True)


async def _record_dq_exception(
    sess: AsyncSession, admission: AdmissionRecord, machine: dict
) -> None:
    """独立会话写 DataQuality.Exception（失败仅告警，不改变 400 决策）。"""
    await record_dq_exception_independent(
        admission.tenant_id,
        admission.object_id,
        admission.admission_id,
        admission.version,
        machine,
    )


async def _latest_raw(sess: AsyncSession, admission: AdmissionRecord) -> RawRecord | None:
    """对象的最新 RAW 行：RAW 无 object_id 列（先留存后投影），经
    business_objects (source_system, source_id) 关联取该对象来源记录。"""
    raw_id = (
        await sess.execute(
            text(
                "SELECT rr.raw_record_id FROM governance.raw_records rr"
                " JOIN master.business_objects bo"
                "   ON bo.source_system = rr.source_system"
                "  AND bo.source_id = rr.source_record_id"
                "  AND bo.tenant_id = rr.tenant_id"
                " WHERE bo.object_id = :oid"
                " ORDER BY rr.received_at DESC, rr.raw_record_id DESC LIMIT 1"
            ),
            {"oid": admission.object_id},
        )
    ).scalar_one_or_none()
    if raw_id is None:
        return None
    return await sess.get(RawRecord, raw_id)


async def _object_attributes(sess: AsyncSession, object_id: UUID) -> dict | None:
    return (
        await sess.execute(
            text(
                "SELECT attributes FROM master.business_objects WHERE object_id = :oid"
            ),
            {"oid": object_id},
        )
    ).scalar_one_or_none()


async def _fill_archive_snapshot(
    sess: AsyncSession, admission: AdmissionRecord
) -> None:
    """A4 归档要素快照：raw/clean/standard/classification 版本引用 +
    分类标签 + 证据引用（已挂）+ checksum（最新 RAW 校验和）。"""
    raw = await _latest_raw(sess, admission)
    if raw is not None:
        admission.raw_version = str(raw.raw_record_id)
        admission.checksum = raw.checksum
        admission.standard_version = str(admission.version)
    classifications = await list_classifications(sess, object_id=admission.object_id)
    if classifications:
        admission.classification_version = str(classifications[-1].version)
        admission.classifications = [
            {
                "dimension_id": str(c.dimension_id) if c.dimension_id else None,
                "label": c.label,
                "source": c.source,
            }
            for c in classifications
        ]
