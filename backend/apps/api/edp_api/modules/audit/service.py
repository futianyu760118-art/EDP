"""audit 服务：显式审计补点（record_explicit）+ 审计查询（query_logs）。

record_explicit 供不经 ORM 状态的写路径补审计（registry 乐观锁 SQL UPDATE、
events 批量 pg_insert、T12 verify 告警）；actor/tenant/request_id 与切面
（aspect.py）同一取法——请求内已由 tenant_scoped 写入 contextvar。

query_logs：audit_logs 为控制面表（不启用 RLS），租户收敛靠显式条件——
非平台管理员仅见本租户（is_platform_admin 见全量）；游标分页与 events
同构（occurred_at DESC, audit_id DESC tiebreak，锚 {"o","i"}）。
"""

from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.pagination import Page, decode_cursor, encode_cursor
from edp_api.core.security.principal import Principal
from edp_api.modules.audit.aspect import make_entry
from edp_api.modules.audit.models import AuditLog
from edp_api.modules.audit.schemas import AuditLogItem

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


async def record_explicit(
    sess: AsyncSession,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None,
    detail: dict,
    risk: str | None = None,
    principal: Principal | None = None,
) -> AuditLog:
    """显式审计补点：构造审计行并入本次事务（仅 add，不 flush——同事务
    原子落库，提交归请求级 get_db / 调用方事务；需要回填 audit_id 的调用
    方自行 flush/refresh）。

    detail 在调用处构造（对象状态随后可能变化，须在 flush 前取值）；risk
    非空时并入 detail（verify 告警等风险语义，T12 用）。
    """
    if risk is not None:
        detail = {**detail, "risk": risk}
    entry = make_entry(
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        detail=detail,
        principal=principal,
    )
    sess.add(entry)
    return entry


async def query_logs(
    sess: AsyncSession,
    principal: Principal,
    *,
    actor_id: str | None = None,
    resource_type: str | None = None,
    action: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[AuditLogItem]:
    """过滤（actor_id/resource_type/action/since/until 闭区间）+ 游标分页
    （occurred_at DESC, audit_id DESC tiebreak）；非法 cursor 视为首页；
    非 is_platform_admin 仅见本租户行。"""
    limit = max(1, min(limit, MAX_LIMIT))
    stmt = select(AuditLog)
    if not principal.is_platform_admin:
        stmt = stmt.where(AuditLog.tenant_id == principal.tenant_id)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if since is not None:
        stmt = stmt.where(AuditLog.occurred_at >= since)
    if until is not None:
        stmt = stmt.where(AuditLog.occurred_at <= until)

    decoded = decode_cursor(cursor)
    if decoded is not None:
        anchor = _parse_anchor(decoded)
        if anchor is not None:
            occurred_at, audit_id = anchor
            stmt = stmt.where(
                or_(
                    AuditLog.occurred_at < occurred_at,
                    and_(
                        AuditLog.occurred_at == occurred_at,
                        AuditLog.audit_id < audit_id,
                    ),
                )
            )

    stmt = stmt.order_by(
        AuditLog.occurred_at.desc(), AuditLog.audit_id.desc()
    ).limit(limit + 1)
    rows = (await sess.execute(stmt)).scalars().all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"o": last.occurred_at.isoformat(), "i": last.audit_id}
        )
    return Page(
        items=[AuditLogItem.model_validate(row) for row in page_rows],
        next_cursor=next_cursor,
    )


def _parse_anchor(decoded: dict) -> tuple[datetime, int] | None:
    """cursor 载荷 → (occurred_at, audit_id)；缺字段/格式非法 → None。"""
    try:
        return datetime.fromisoformat(str(decoded["o"])), int(decoded["i"])
    except (KeyError, TypeError, ValueError):
        return None
