"""search 服务（W6 T1）：全局搜索三组聚合（对象/事件/证据）。

命中口径：
- objects：master.business_objects 的 ``source_id``/``object_type`` ILIKE
  ``%q%``——``attributes`` JSONB 不参与（无 GIN 索引的全表扫描成本高，
  本轮明确不搜，需要时再以索引 + 专用端点承接）；
- events：``event_type`` ILIKE 或 ``data->>'summary'`` ILIKE（data 为
  JSONB，仅取 summary 键——能力结果事件的摘要主显示字段）；
- evidence：``source_record_id``（源记录 ref）/``source_system``（来源
  kind）ILIKE；
- 每组按各自时间序 DESC（objects.updated_at / events.occurred_at /
  evidence.captured_at，均以主键 id DESC tiebreak）LIMIT limit；
  total = 三组返回行数合计（非全表命中计数，前端空态/分页依据）。

跨模块表（registry/events/evidence）不可直接引用对方 ORM（import-linter
仅放行 service）——以核心表构造参与查询（口径同 events.service 的
_BUSINESS_OBJECTS）；会话由 tenant_scoped 预 bind_tenant，三表 FORCE RLS
天然限本租户，本层不做租户过滤。``q`` 中的 %/_ 按 LIKE 通配符原样传递。
"""

from sqlalchemy import DateTime, Text, Uuid, column, or_, select, table
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.modules.search.schemas import (
    EventHit,
    EvidenceHit,
    ObjectHit,
    SearchResponse,
)

DEFAULT_LIMIT = 10
MAX_LIMIT = 50

_BUSINESS_OBJECTS = table(
    "business_objects",
    column("object_id", Uuid),
    column("object_type", Text),
    column("source_id", Text),
    column("updated_at", DateTime(timezone=True)),
    schema="master",
)

_EVENTS = table(
    "events",
    column("event_id", Uuid),
    column("event_type", Text),
    column("occurred_at", DateTime(timezone=True)),
    column("data", JSONB),
    schema="event",
)

_RECORDS = table(
    "records",
    column("evidence_id", Uuid),
    column("source_record_id", Text),
    column("source_system", Text),
    column("captured_at", DateTime(timezone=True)),
    schema="evidence",
)


async def search_all(sess: AsyncSession, q: str, limit: int) -> SearchResponse:
    """关键词三组聚合搜索；同请求内三查询，每组各自时间序 DESC LIMIT limit
    （默认 10、上限 50 由路由 Query 约束）。"""
    pattern = f"%{q}%"

    objects = (
        (
            await sess.execute(
                select(
                    _BUSINESS_OBJECTS.c.object_id,
                    _BUSINESS_OBJECTS.c.source_id,
                    _BUSINESS_OBJECTS.c.object_type,
                    _BUSINESS_OBJECTS.c.updated_at,
                )
                .where(
                    or_(
                        _BUSINESS_OBJECTS.c.source_id.ilike(pattern),
                        _BUSINESS_OBJECTS.c.object_type.ilike(pattern),
                    )
                )
                .order_by(
                    _BUSINESS_OBJECTS.c.updated_at.desc(),
                    _BUSINESS_OBJECTS.c.object_id.desc(),
                )
                .limit(limit)
            )
        )
        .mappings()
        .all()
    )
    events = (
        (
            await sess.execute(
                select(
                    _EVENTS.c.event_id,
                    _EVENTS.c.event_type,
                    _EVENTS.c.occurred_at,
                )
                .where(
                    or_(
                        _EVENTS.c.event_type.ilike(pattern),
                        _EVENTS.c.data["summary"].astext.ilike(pattern),
                    )
                )
                .order_by(_EVENTS.c.occurred_at.desc(), _EVENTS.c.event_id.desc())
                .limit(limit)
            )
        )
        .mappings()
        .all()
    )
    evidence = (
        (
            await sess.execute(
                select(
                    _RECORDS.c.evidence_id,
                    _RECORDS.c.source_record_id,
                    _RECORDS.c.source_system,
                    _RECORDS.c.captured_at,
                )
                .where(
                    or_(
                        _RECORDS.c.source_record_id.ilike(pattern),
                        _RECORDS.c.source_system.ilike(pattern),
                    )
                )
                .order_by(
                    _RECORDS.c.captured_at.desc(),
                    _RECORDS.c.evidence_id.desc(),
                )
                .limit(limit)
            )
        )
        .mappings()
        .all()
    )

    return SearchResponse(
        query=q,
        objects=[ObjectHit(**dict(row)) for row in objects],
        events=[EventHit(**dict(row)) for row in events],
        evidence=[EvidenceHit(**dict(row)) for row in evidence],
        total=len(objects) + len(events) + len(evidence),
    )
