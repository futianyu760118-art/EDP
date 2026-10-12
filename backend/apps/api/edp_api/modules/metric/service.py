"""metric 服务（V1.2 T23）：指标口径注册（版本化）+ 计量值。

- create_metric：同 code 新版本——旧版本收 effective_to（口径变更必须
  版本化、留审计；EDP 不裁决口径，definition_owner 由请求方声明）；
- record_value：period 唯一 upsert（同 period 覆盖）；EBMS 报表数据源
  （T26 起 _latest_kpis 改读本 schema）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.errors import EdpError
from edp_api.core.pagination import Page, decode_cursor, encode_cursor
from edp_api.core.security.principal import Principal
from edp_api.modules.metric.models import Metric, MetricValue
from edp_api.modules.metric.schemas import MetricCreateRequest, MetricValueCreate

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


async def create_metric(
    sess: AsyncSession, principal: Principal, req: MetricCreateRequest
) -> Metric:
    """注册口径：同 code 生效中新版本 → 旧版本收 effective_to。"""
    effective_from = datetime.now(UTC)
    previous = (
        await sess.execute(
            select(Metric)
            .where(
                Metric.tenant_id == principal.tenant_id,
                Metric.code == req.code,
                Metric.effective_to.is_(None),
            )
            .order_by(Metric.version.desc())
        )
    ).scalars().first()
    if previous is not None:
        previous.effective_to = effective_from
        previous.updated_by = principal.id
        previous.updated_at = datetime.now(UTC)
    metric = Metric(
        metric_id=uuid4(),
        tenant_id=principal.tenant_id,
        code=req.code,
        name=req.name,
        business_definition=req.business_definition,
        formula=req.formula,
        source=req.source,
        owner=req.owner,
        definition_owner=req.definition_owner,
        definition_source=req.definition_source,
        target_owner=req.target_owner,
        snapshot_policy=req.snapshot_policy,
        period_rule=req.period_rule,
        dimension=req.dimension,
        unit=req.unit,
        version=(previous.version + 1) if previous is not None else 1,
        effective_from=effective_from,
        created_by=principal.id,
        updated_by=principal.id,
    )
    sess.add(metric)
    await sess.flush()
    return metric


async def get_metric(sess: AsyncSession, metric_id: UUID) -> Metric | None:
    return (
        await sess.execute(select(Metric).where(Metric.metric_id == metric_id))
    ).scalar_one_or_none()


async def query_metrics(
    sess: AsyncSession,
    *,
    code: str | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[Metric]:
    """列表（code 过滤 + 游标分页 effective_from DESC tiebreak）。"""
    limit = max(1, min(limit, MAX_LIMIT))
    stmt = select(Metric)
    if code:
        stmt = stmt.where(Metric.code == code)
    decoded = decode_cursor(cursor)
    if decoded is not None:
        try:
            anchor_from = datetime.fromisoformat(str(decoded["f"]))
            anchor_id = UUID(str(decoded["i"]))
            stmt = stmt.where(
                or_(
                    Metric.effective_from < anchor_from,
                    and_(
                        Metric.effective_from == anchor_from,
                        Metric.metric_id < anchor_id,
                    ),
                )
            )
        except (KeyError, TypeError, ValueError):
            pass
    stmt = stmt.order_by(Metric.effective_from.desc(), Metric.metric_id.desc()).limit(
        limit + 1
    )
    rows = (await sess.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"f": last.effective_from.isoformat(), "i": str(last.metric_id)}
        )
    return Page(items=list(page_rows), next_cursor=next_cursor)


async def record_value(
    sess: AsyncSession,
    principal: Principal,
    metric_id: UUID,
    req: MetricValueCreate,
) -> MetricValue:
    """计量值 upsert（(tenant, metric, period) 唯一——同周期覆盖）。"""
    metric = await get_metric(sess, metric_id)
    if metric is None:
        raise EdpError.validation_error(f"metric_id 不存在：{metric_id}")
    existing = (
        await sess.execute(
            select(MetricValue).where(
                MetricValue.tenant_id == principal.tenant_id,
                MetricValue.metric_id == metric_id,
                MetricValue.period == req.period,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.value = req.value
        existing.source = req.source
        existing.computed_at = datetime.now(UTC)
        existing.updated_by = principal.id
        existing.updated_at = datetime.now(UTC)
        await sess.flush()
        return existing
    value = MetricValue(
        value_id=uuid4(),
        tenant_id=principal.tenant_id,
        metric_id=metric_id,
        period=req.period,
        value=req.value,
        source=req.source,
        computed_at=datetime.now(UTC),
        created_by=principal.id,
        updated_by=principal.id,
    )
    sess.add(value)
    await sess.flush()
    return value


async def list_values(
    sess: AsyncSession, metric_id: UUID
) -> list[MetricValue]:
    return list(
        (
            await sess.execute(
                select(MetricValue)
                .where(MetricValue.metric_id == metric_id)
                .order_by(MetricValue.period.desc(), MetricValue.value_id.desc())
            )
        ).scalars().all()
    )


async def latest_by_code(sess: AsyncSession, code: str) -> Metric | None:
    """生效中口径（code 过滤；EBMS 校验用）。"""
    return (
        await sess.execute(
            select(Metric)
            .where(Metric.code == code, Metric.effective_to.is_(None))
            .order_by(Metric.version.desc())
        )
    ).scalars().first()
