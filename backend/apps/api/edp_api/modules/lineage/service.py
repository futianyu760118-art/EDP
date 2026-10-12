"""lineage 服务（V1.2 T20）：血缘写入（准入 OFFICIAL 转换）+ 只读查询。

写入口唯一：governance 服务在 MANAGEMENT_APPROVED → OFFICIAL 转换时经
``record_official`` 落行（本模块不对外提供写 API——血缘是准入副产物，
人工不可篡改）；查询经 governance:read 权限轨道（血缘属数据治理读面）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.modules.lineage.models import Lineage

# business_objects 按 lineage_id 反查对象（读 API 组装：lineage → object）
_OBJECT_BY_LINEAGE_SQL = text("""
    SELECT object_id, source_system, object_type FROM master.business_objects
    WHERE tenant_id = :tid AND lineage_id = :lid
""")


async def record_official(
    sess: AsyncSession,
    tenant_id: UUID,
    *,
    source_record_id: str,
    source_review_ref: UUID | None,
    management_review_ref: UUID | None,
    official_version: str,
    operator: str,
    classification_version: str | None = None,
) -> Lineage:
    """OFFICIAL 转换时落血缘行（governance 服务调用；同事务）。"""
    lineage = Lineage(
        lineage_id=uuid4(),
        tenant_id=tenant_id,
        source_record_id=source_record_id,
        source_review_ref=source_review_ref,
        management_review_ref=management_review_ref,
        official_version=official_version,
        classification_version=classification_version,
        timestamp=datetime.now(UTC),
        operator=operator,
    )
    sess.add(lineage)
    await sess.flush()
    return lineage


async def get_lineage(sess: AsyncSession, lineage_id: UUID) -> Lineage | None:
    return (
        await sess.execute(select(Lineage).where(Lineage.lineage_id == lineage_id))
    ).scalar_one_or_none()


async def query_by_source_record(
    sess: AsyncSession, tenant_id: UUID, source_record_id: str
) -> list[Lineage]:
    """按源记录查询血缘链（新→旧）。RLS 会话限租户。"""
    return list(
        (
            await sess.execute(
                select(Lineage)
                .where(
                    Lineage.tenant_id == tenant_id,
                    Lineage.source_record_id == source_record_id,
                )
                .order_by(Lineage.timestamp.desc(), Lineage.lineage_id.desc())
            )
        ).scalars().all()
    )


async def object_ref_for(
    sess: AsyncSession, tenant_id: UUID, lineage_id: UUID
) -> dict | None:
    row = (
        await sess.execute(
            _OBJECT_BY_LINEAGE_SQL, {"tid": tenant_id, "lid": lineage_id}
        )
    ).mappings().first()
    return dict(row) if row is not None else None
