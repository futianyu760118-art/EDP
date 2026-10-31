"""租户域服务：tenants / tenant_members 查询（模块间共享经由本文件）+
W2 生命周期（EDP-024）：单事务开通 / 状态机（暂停-恢复-注销强确认）/
清单与详情 + W5 B.14 补齐（EDP-501）：PATCH 更新 / context 切换重签 /
members CRUD（最后 ACTIVE ADMIN 保护）/ quotas 读改（reason 留痕）。

RLS 要点：tenants / tenant_quotas 为控制面表（不受 RLS）；users /
tenant_members FORCE RLS——create_tenant 在租户行落库后 bind_tenant 到
新租户再写初始管理员，members 读写同样先 bind_tenant 目标租户（事务级
set_config，请求提交自动失效）。状态/成员/配额写回一律 ORM 属性赋值
（before_flush 审计切面自动落 TENANTS_UPDATE / TENANT_MEMBERS_UPDATE /
TENANT_QUOTAS_UPDATE，勿改 SQL update）。
"""

import secrets
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.core.db import bind_tenant
from edp_api.core.errors import EdpError
from edp_api.core.pagination import Page, decode_cursor, encode_cursor
from edp_api.core.security.jwt import create_access_token
from edp_api.core.security.password import hash_password
from edp_api.core.security.principal import Principal
from edp_api.core.tenant_context import ensure_tenant_usable
from edp_api.modules.audit import service as audit_service
from edp_api.modules.tenantmgmt.models import (
    Tenant,
    TenantMember,
    TenantQuota,
    TenantUsageDaily,
    UserRow,
)
from edp_api.modules.tenantmgmt.schemas import (
    AdminUserItem,
    TenantCreateRequest,
    TenantDetail,
    TenantMemberCreateRequest,
    TenantMemberItem,
    TenantMemberUpdateRequest,
    TenantQuotaDetail,
    TenantQuotaInfo,
    TenantQuotaUpdateRequest,
    TenantSummary,
    TenantUpdateRequest,
    TenantUsage,
    UsageItem,
)

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

# 注销数据保留窗口（天）：cancel 时写 cancel_scheduled_at = now + N
CANCEL_RETENTION_DAYS = 30

# 计划默认配额（EDP-024 / 3.5 防护配置）：开通时整行落 tenant_quotas
PLAN_QUOTAS: dict[str, dict] = {
    "TRIAL": {
        "storage_gb": 10,
        "events_per_month": 50_000,
        "api_rate_limit": 50,
        "batch_max_events": 500,
        "query_timeout_ms": 5000,
        "pool_share": Decimal("1.0"),
    },
    "STANDARD": {
        "storage_gb": 50,
        "events_per_month": 1_000_000,
        "api_rate_limit": 100,
        "batch_max_events": 1000,
        "query_timeout_ms": 5000,
        "pool_share": Decimal("2.0"),
    },
    "PREMIUM": {
        "storage_gb": 200,
        "events_per_month": 5_000_000,
        "api_rate_limit": 300,
        "batch_max_events": 5000,
        "query_timeout_ms": 3000,
        "pool_share": Decimal("5.0"),
    },
    "DEDICATED": {
        "storage_gb": 2000,
        "events_per_month": 20_000_000,
        "api_rate_limit": 1000,
        "batch_max_events": 20_000,
        "query_timeout_ms": 10_000,
        "pool_share": Decimal("20.0"),
    },
}

# 生命周期状态机：(operation, target) → 允许的来源状态集合。
# cancel 自任意未注销状态（含 PROVISIONING）受理；其余按单向转移。
_LIFECYCLE_RULES: dict[tuple[str, str], frozenset[str]] = {
    ("suspend", "SUSPENDED"): frozenset({"ACTIVE"}),
    ("resume", "ACTIVE"): frozenset({"SUSPENDED"}),
    ("cancel", "CANCELLED"): frozenset({"ACTIVE", "SUSPENDED", "PROVISIONING"}),
}


# ---- W1 查询（模块间共享入口） ----


async def get_tenant_by_slug(sess: AsyncSession, slug: str) -> Tenant | None:
    """按 slug 查租户（tenants 为控制面表，不受 RLS 约束）。"""
    return (
        await sess.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()


async def get_tenant(sess: AsyncSession, tenant_id: UUID) -> Tenant | None:
    """按 tenant_id 查租户。"""
    return await sess.get(Tenant, tenant_id)


async def get_tenant_status(sess: AsyncSession, tenant_id: UUID) -> str | None:
    """租户当前状态；租户不存在 → None（status 列 NOT NULL，无歧义）。"""
    return (
        await sess.execute(select(Tenant.status).where(Tenant.tenant_id == tenant_id))
    ).scalar_one_or_none()


async def get_quota(sess: AsyncSession, tenant_id: UUID) -> TenantQuota:
    """租户配额（tenant_quotas 控制面表）；缺行 → DDL 默认值临时实例（不入库）。

    注意：列 ``default=`` 仅在 INSERT 时生效——缺省实例必须显式赋默认值，
    否则属性为 None（EDP-025 限流读取会 TypeError）。

    EDP-025 限流/批量限额/statement_timeout 读取入口（每请求一次，演示量级
    可接受；W6 性能评估时可加进程内缓存）。
    """
    quota = await sess.get(TenantQuota, tenant_id)
    if quota is not None:
        return quota
    return TenantQuota(
        tenant_id=tenant_id,
        api_rate_limit=100,
        batch_max_events=1000,
        query_timeout_ms=5000,
        pool_share=Decimal("2.0"),
        storage_gb=50,
        events_per_month=1_000_000,
    )


async def member_roles_for_user(
    sess: AsyncSession, tenant_id: UUID, user_id: UUID
) -> list[str]:
    """用户在租户内的角色（tenant_members.member_roles）；无成员关系 → []。

    tenant_members 受 FORCE RLS 约束：调用方需已 bind_tenant（登录流程在
    租户解析后绑定）。
    """
    roles = (
        await sess.execute(
            select(TenantMember.member_roles).where(
                TenantMember.tenant_id == tenant_id,
                TenantMember.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    return list(roles or [])


async def active_tenant_ids(sess: AsyncSession) -> list[UUID]:
    """活跃（ACTIVE）租户 id 列表（tenant_id 升序）。

    worker 调度清单数据源（模块间仅 service：worker 经本函数读租户表，
    不直连 platform.tenants）；控制面表不受 RLS，edp_app 角色可读。
    """
    return list(
        (
            await sess.execute(
                select(Tenant.tenant_id)
                .where(Tenant.status == "ACTIVE")
                .order_by(Tenant.tenant_id)
            )
        )
        .scalars()
        .all()
    )


# ---- W3 演示时间锚（EDP-016，T6） ----


def _demo_seed_anchor(attributes: dict | None) -> datetime | None:
    """attributes["demo_seed"]["anchor"] ISO 字符串 → aware datetime；非法 → None。"""
    raw = (attributes or {}).get("demo_seed")
    anchor = raw.get("anchor") if isinstance(raw, dict) else None
    if not isinstance(anchor, str):
        return None
    try:
        parsed = datetime.fromisoformat(anchor)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


async def get_demo_anchor(sess: AsyncSession, tenant_id: UUID) -> datetime | None:
    """演示时间锚（tenants.attributes.demo_seed.anchor）；未设置/非法 → None。

    tenants 为控制面表（无 RLS），仍以显式 tenant_id 定位（双保险）；
    None 由调用方（ingest/适配器）回退 DEMO_ANCHOR 兜底。
    """
    tenant = await get_tenant(sess, tenant_id)
    return _demo_seed_anchor(tenant.attributes) if tenant is not None else None


async def set_demo_anchor(
    sess: AsyncSession, tenant_id: UUID, anchor: datetime
) -> None:
    """写演示时间锚（ISO 字符串，读改 attributes 后 flush；租户不存在 → 404）。

    ORM 属性赋值路径（切面可见 TENANTS_UPDATE）；demo_seed.version 缺失时
    补 1（spec §3.3 结构）。
    """
    tenant = await get_tenant(sess, tenant_id)
    if tenant is None:
        raise EdpError.not_found("租户不存在")
    attributes = dict(tenant.attributes or {})
    demo_seed = dict(attributes.get("demo_seed") or {})
    demo_seed["anchor"] = anchor.isoformat()
    demo_seed.setdefault("version", 1)
    attributes["demo_seed"] = demo_seed
    tenant.attributes = attributes
    await sess.flush()


# ---- W3 用量计量（T9：events 批量入库 / ingest 管道共用入口） ----


async def bump_usage_daily(
    sess: AsyncSession,
    tenant_id: UUID,
    *,
    events_in: int = 0,
    events_duplicated: int = 0,
    api_calls: int = 0,
    throttled_429: int = 0,
) -> None:
    """按 (tenant_id, usage_date=UTC 今日) upsert 累加计量列。

    事件口径（spec §5.1）：``events_in`` = 实际入库事件数、
    ``events_duplicated`` = 幂等去重数（调用方 events.ingest_batch /
    ingest.process_record 与事件写入同事务调用——失败请求不计入，语义为
    「受理调用数」，docstring 留痕）；EDP-025 计量：``api_calls`` 每请求
    +1（**独立短会话**立即提交，见 ``ratelimit.record_api_call``——同请求
    事务写法下 usage 行锁持续到请求结束，并发请求串行互等；语义随之为
    「全部请求（含失败）」，W3R-02）、``throttled_429`` 限流拒绝 +1（429 路径
    同经独立会话提交）。控制面表（platform schema，不受 RLS）。
    ON CONFLICT (tenant_id, usage_date) 并发安全。
    """
    if not any((events_in, events_duplicated, api_calls, throttled_429)):
        return
    stmt = (
        pg_insert(TenantUsageDaily)
        .values(
            id=uuid4(),
            tenant_id=tenant_id,
            usage_date=datetime.now(UTC).date(),
            events_in=events_in,
            events_duplicated=events_duplicated,
            api_calls=api_calls,
            throttled_429=throttled_429,
        )
        .on_conflict_do_update(
            index_elements=["tenant_id", "usage_date"],
            set_={
                "events_in": TenantUsageDaily.events_in + events_in,
                "events_duplicated": (
                    TenantUsageDaily.events_duplicated + events_duplicated
                ),
                "api_calls": TenantUsageDaily.api_calls + api_calls,
                "throttled_429": TenantUsageDaily.throttled_429 + throttled_429,
                "updated_at": func.now(),
            },
        )
    )
    await sess.execute(stmt)


# ---- W2 生命周期（EDP-024） ----


async def next_tenant_code(
    sess: AsyncSession, year: int | None = None
) -> str:
    """原子取号生成租户编码 ten-<year>-<NNNN>（按年重置，>9999 自然 5 位）。

    计数表（迁移 0020）单条 upsert-returning 取号：同年初次 INSERT、
    已有行行锁递增——事务内串行化，不重号、无竞态、无重试。行锁随
    请求事务持有至提交，编号消耗与租户落库同生共死（请求失败回滚即
    让号，不留空洞）。

    ``year`` 仅供测试注入跨年语义，业务路径缺省取当前 UTC 年（与
    created_at 同源）。
    """
    if year is None:
        year = datetime.now(UTC).year
    no = (
        await sess.execute(
            text("""
                INSERT INTO platform.tenant_code_seq (year, last_no)
                VALUES (:year, 1)
                ON CONFLICT (year) DO UPDATE
                    SET last_no = platform.tenant_code_seq.last_no + 1,
                        updated_at = now()
                RETURNING last_no
            """),
            {"year": year},
        )
    ).scalar_one()
    return f"ten-{year}-{no:04d}"


async def create_tenant(
    sess: AsyncSession, req: TenantCreateRequest, actor_id: str
) -> tuple[Tenant, UserRow, str | None]:
    """单事务开通租户：tenants(ACTIVE) + tenant_quotas(PLAN_QUOTAS[plan]) +
    初始管理员 users + tenant_members(member_roles=["ADMIN"])。

    - 编码自动生成（ten-YYYY-NNNN，next_tenant_code 原子取号）；slug
      唯一索引 IntegrityError 兜底 409（计数表被外部改坏时的防御）；
    - users / tenant_members FORCE RLS：租户行 flush 落库后 bind_tenant 到
      新租户再写管理员（username/email 租户内唯一由索引保证，同样先查
      再插 + 兜底）；
    - admin.password 未携带时生成 secrets.token_urlsafe(12) 临时口令并随
      返回值回传（B.14：仅本次响应可见，不落任何日志）。

    Returns:
        (租户, 初始管理员用户, 临时口令)；请求已携带密码时第三项为 None。
    """
    slug = await next_tenant_code(sess)
    now = datetime.now(UTC)
    tenant = Tenant(
        tenant_id=uuid4(),
        slug=slug,
        name=req.name,
        plan=req.plan,
        status="ACTIVE",
        created_at=now,
        updated_at=now,
        created_by=actor_id,
        updated_by=actor_id,
    )
    sess.add(tenant)
    try:
        await sess.flush()  # slug 唯一索引兜底（计数表异常时的最后防线）
    except IntegrityError:
        await sess.rollback()
        raise EdpError.conflict("租户编码生成冲突，请重试") from None
    sess.add(
        TenantQuota(
            tenant_id=tenant.tenant_id,
            created_at=now,
            updated_at=now,
            created_by=actor_id,
            updated_by=actor_id,
            **PLAN_QUOTAS[req.plan],
        )
    )
    # RLS：users / tenant_members FORCE——绑定新租户后再写初始管理员
    await bind_tenant(sess, tenant.tenant_id)
    if await _admin_account_taken(sess, tenant.tenant_id, req):
        raise EdpError.conflict("管理员用户名或邮箱已存在")
    temporary_password: str | None = None
    if req.admin.password is None:
        temporary_password = secrets.token_urlsafe(12)
    admin_user = UserRow(
        user_id=uuid4(),
        tenant_id=tenant.tenant_id,
        username=req.admin.username,
        email=req.admin.email,
        password_hash=hash_password(req.admin.password or temporary_password),
        display_name=req.admin.display_name,
        principal_type="HUMAN",
        is_platform_admin=False,
        status="ACTIVE",
        created_by=actor_id,
        updated_by=actor_id,
    )
    sess.add(admin_user)
    try:
        # UOW 不按表级外键排序插入（沿 evidence 显式分步先例）：users 先
        # 落库，再写 tenant_members（DB 外键 tenant_members_user_id_fkey）
        await sess.flush()
        sess.add(
            TenantMember(
                member_id=uuid4(),
                tenant_id=tenant.tenant_id,
                user_id=admin_user.user_id,
                member_roles=["ADMIN"],
                status="ACTIVE",
                created_at=now,
                updated_at=now,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await sess.flush()
    except IntegrityError:
        await sess.rollback()
        raise EdpError.conflict("管理员用户名或邮箱已存在") from None
    return tenant, admin_user, temporary_password


async def _admin_account_taken(
    sess: AsyncSession, tenant_id: UUID, req: TenantCreateRequest
) -> bool:
    """初始管理员用户名/邮箱在租户内是否已占用（已 bind_tenant，查询天然
    限新租户；并发竞争由 uq_users_username / uq_users_email 兜底）。"""
    row = (
        await sess.execute(
            select(UserRow.user_id).where(
                UserRow.tenant_id == tenant_id,
                or_(
                    UserRow.username == req.admin.username,
                    UserRow.email == req.admin.email,
                ),
            )
        )
    ).scalar_one_or_none()
    return row is not None


async def set_tenant_status(
    sess: AsyncSession,
    tenant_id: UUID,
    target: str,
    operation: str,
    *,
    confirm: bool | None = None,
    reason: str | None = None,
    actor_id: str | None = None,
) -> Tenant:
    """生命周期状态机：ACTIVE→SUSPENDED（suspend）/ SUSPENDED→ACTIVE
    （resume）/ 任意未注销→CANCELLED（cancel）。

    - cancel 为强确认操作：confirm 非 True 或 reason 缺失 → 400
      VALIDATION_ERROR（HTTP_FOR_CODE 全局映射 400，与请求体校验一致）；
    - 非法转移（重复注销、suspend 非 ACTIVE 等）→ 422 INVALID_TRANSITION；
    - cancel 写 cancel_scheduled_at = now + 30 天（数据保留窗口起算）；
    - 状态写回走 ORM 属性赋值：before_flush 切面自动落 TENANTS_UPDATE
      审计行（勿改成 SQL update——切面对纯 SQL 不可见）；
    - 控制面表无 RLS——不依赖隔离键，显式 tenant_id 定位双保险。
    """
    tenant = await get_tenant(sess, tenant_id)
    if tenant is None:
        raise EdpError.not_found("租户不存在")
    if operation == "cancel" and (confirm is not True or not (reason or "").strip()):
        raise EdpError.validation_error("需要 confirm=true 与注销原因")
    allowed_sources = _LIFECYCLE_RULES.get((operation, target))
    if allowed_sources is None or tenant.status not in allowed_sources:
        raise EdpError.invalid_transition(
            f"租户状态不支持该操作：{tenant.status} → {target}（{operation}）"
        )
    now = datetime.now(UTC)
    if operation == "cancel":
        tenant.cancel_scheduled_at = now + timedelta(days=CANCEL_RETENTION_DAYS)
    tenant.status = target
    tenant.updated_at = now
    tenant.updated_by = actor_id
    await sess.flush()
    return tenant


async def list_tenants(
    sess: AsyncSession,
    *,
    status: str | None = None,
    plan: str | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[TenantSummary]:
    """平台级租户清单：status/plan 过滤 + 游标分页（created_at DESC,
    tenant_id DESC tiebreak，锚 {"o","i"} 与 audit 同构；非法 cursor 视为首页）。"""
    limit = max(1, min(limit, MAX_LIMIT))
    stmt = select(Tenant)
    if status:
        stmt = stmt.where(Tenant.status == status)
    if plan:
        stmt = stmt.where(Tenant.plan == plan)
    decoded = decode_cursor(cursor)
    if decoded is not None:
        anchor = _parse_anchor(decoded)
        if anchor is not None:
            created_at, anchor_tenant_id = anchor
            stmt = stmt.where(
                or_(
                    Tenant.created_at < created_at,
                    and_(
                        Tenant.created_at == created_at,
                        Tenant.tenant_id < anchor_tenant_id,
                    ),
                )
            )
    stmt = stmt.order_by(Tenant.created_at.desc(), Tenant.tenant_id.desc()).limit(
        limit + 1
    )
    rows = (await sess.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"o": last.created_at.isoformat(), "i": str(last.tenant_id)}
        )
    return Page(
        items=[TenantSummary.model_validate(row) for row in page_rows],
        next_cursor=next_cursor,
    )


def _parse_anchor(decoded: dict) -> tuple[datetime, UUID] | None:
    """cursor 载荷 → (created_at, tenant_id)；缺字段/格式非法 → None。"""
    try:
        return datetime.fromisoformat(str(decoded["o"])), UUID(str(decoded["i"]))
    except (KeyError, TypeError, ValueError):
        return None


async def query_usage(
    sess: AsyncSession,
    tenant_id: UUID,
    *,
    since: date | None = None,
    until: date | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> tuple[list[UsageItem], str | None]:
    """使用量日报（B.14 最小版，EDP-025）：usage_date 闭区间 + 游标分页
    （usage_date DESC, id DESC tiebreak，锚 ``{"d","i"}``；非法 cursor 视为首页）。"""
    limit = max(1, min(limit, MAX_LIMIT))
    stmt = select(TenantUsageDaily).where(
        TenantUsageDaily.tenant_id == tenant_id
    )
    if since is not None:
        stmt = stmt.where(TenantUsageDaily.usage_date >= since)
    if until is not None:
        stmt = stmt.where(TenantUsageDaily.usage_date <= until)
    decoded = decode_cursor(cursor)
    if decoded is not None:
        anchor = _parse_usage_anchor(decoded)
        if anchor is not None:
            usage_date, anchor_id = anchor
            stmt = stmt.where(
                or_(
                    TenantUsageDaily.usage_date < usage_date,
                    and_(
                        TenantUsageDaily.usage_date == usage_date,
                        TenantUsageDaily.id < anchor_id,
                    ),
                )
            )
    stmt = stmt.order_by(
        TenantUsageDaily.usage_date.desc(), TenantUsageDaily.id.desc()
    ).limit(limit + 1)
    rows = (await sess.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"d": last.usage_date.isoformat(), "i": str(last.id)}
        )
    return [UsageItem.model_validate(row) for row in page_rows], next_cursor


def _parse_usage_anchor(decoded: dict) -> tuple[date, UUID] | None:
    """cursor 载荷 → (usage_date, id)；缺字段/格式非法 → None。"""
    try:
        return date.fromisoformat(str(decoded["d"])), UUID(str(decoded["i"]))
    except (KeyError, TypeError, ValueError):
        return None


async def get_tenant_detail(sess: AsyncSession, tenant_id: UUID) -> TenantDetail:
    """租户详情：基本字段 + quotas 行（缺失容忍为 None）+ usage 聚合
    （MVP 恒 None 字段——W3 计量接入后由 tenant_usage_daily 聚合回填）。"""
    tenant = await get_tenant(sess, tenant_id)
    if tenant is None:
        raise EdpError.not_found("租户不存在")
    quota = await sess.get(TenantQuota, tenant_id)
    return TenantDetail(
        tenant_id=tenant.tenant_id,
        slug=tenant.slug,
        name=tenant.name,
        plan=tenant.plan,
        status=tenant.status,
        cancel_scheduled_at=tenant.cancel_scheduled_at,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
        quotas=TenantQuotaInfo.model_validate(quota) if quota is not None else None,
        usage=TenantUsage(),
    )


# ---- W5 B.14 租户 API 补齐（EDP-501 后端，T2） ----

# context 切换响应 note 文案（B.14 逐字）
CONTEXT_SWITCH_NOTE = "所有后续请求将以该租户执行，操作全程审计"

# 显式审计动作名（B.14 平台面留痕；切面自动行之外的业务语义补点）
ACTION_CONTEXT_SWITCH = "TENANT_CONTEXT_SWITCH"
ACTION_QUOTA_ADJUST = "TENANT_QUOTAS_ADJUST"


async def update_tenant(
    sess: AsyncSession, tenant_id: UUID, req: TenantUpdateRequest, *, actor_id: str
) -> None:
    """PATCH /tenants/{id}：name / plan 局部更新（ORM 赋值 → 切面自动
    TENANTS_UPDATE 审计行）。

    plan 变更**仅记录不调配额**：开通默认值只在 POST /tenants 按
    PLAN_QUOTAS 落库一次，后续配额调整唯一入口是 PATCH /quotas
    （显式 reason 留痕）——避免 plan 字段变化静默改写运维调过的配额。
    """
    tenant = await get_tenant(sess, tenant_id)
    if tenant is None:
        raise EdpError.not_found("租户不存在")
    now = datetime.now(UTC)
    if req.name is not None:
        tenant.name = req.name
    if req.plan is not None:
        tenant.plan = req.plan
    tenant.updated_at = now
    tenant.updated_by = actor_id
    await sess.flush()


async def switch_tenant_context(
    sess: AsyncSession, principal: Principal, tenant_id: UUID
) -> tuple[Tenant, str]:
    """POST /tenants/{id}/context：校验并重签平台 ADMIN 会话的目标租户。

    - 目标租户不存在 → 404；非 ACTIVE 复用既有租户状态墙
      ensure_tenant_usable（SUSPENDED/CANCELLED → 403 TENANT_SUSPENDED，
      PROVISIONING → 403 TENANT_FORBIDDEN）；
    - 重签复用 create_access_token 既有签发参数与过期语义（exp = now +
      access_ttl），仅在 claims 上附加 act_tenant——tenant_id 保持用户
      绑定租户（身份归属），act_tenant 为执行租户（tenant_scoped 解析
      优先级 act_tenant > 绑定租户）；roles / principal_type /
      is_platform_admin 原样保留；
    - 平台面审计行（record_explicit，action=TENANT_CONTEXT_SWITCH，
      detail 含 from_tenant/to_tenant，actor 归因平台 ADMIN 本人）；
      from_tenant 记 `principal.effective_tenant_id`（act_tenant 优先）
      ——已切换再切换场景下记当前执行租户，而非身份归属租户；
    - **token 经响应体返回是最小可行口径**（B.14 未定义通道）——前端
      TenantSwitchModal 持有后替换本地凭据并全站重拉（13.8）。
    """
    tenant = await get_tenant(sess, tenant_id)
    if tenant is None:
        raise EdpError.not_found("租户不存在")
    ensure_tenant_usable(tenant.status)
    token = create_access_token(
        principal.id,
        principal.tenant_id,
        principal.roles,
        principal.kind,
        principal.is_platform_admin,
        act_tenant=tenant.tenant_id,
    )
    await audit_service.record_explicit(
        sess,
        action=ACTION_CONTEXT_SWITCH,
        resource_type="tenants",
        resource_id=str(tenant.tenant_id),
        detail={
            "from_tenant": str(principal.effective_tenant_id),
            "to_tenant": str(tenant.tenant_id),
        },
        principal=principal,
    )
    return tenant, token


async def list_members(
    sess: AsyncSession,
    tenant_id: UUID,
    *,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[TenantMemberItem]:
    """GET /tenants/{id}/members：joined_at（= created_at）DESC 游标分页
    （member_id tiebreak，锚 {"o","i"} 与租户清单同构）；投影含
    display_name（join platform.users）。

    tenant_members / users 均 FORCE RLS——先 bind_tenant 目标租户再查；
    租户不存在 → 404。
    """
    if await get_tenant(sess, tenant_id) is None:
        raise EdpError.not_found("租户不存在")
    await bind_tenant(sess, tenant_id)
    limit = max(1, min(limit, MAX_LIMIT))
    stmt = (
        select(TenantMember, UserRow.display_name)
        .join(UserRow, TenantMember.user_id == UserRow.user_id)
        .where(TenantMember.tenant_id == tenant_id)
    )
    decoded = decode_cursor(cursor)
    if decoded is not None:
        anchor = _parse_anchor(decoded)
        if anchor is not None:
            joined_at, anchor_member_id = anchor
            stmt = stmt.where(
                or_(
                    TenantMember.created_at < joined_at,
                    and_(
                        TenantMember.created_at == joined_at,
                        TenantMember.member_id < anchor_member_id,
                    ),
                )
            )
    stmt = stmt.order_by(
        TenantMember.created_at.desc(), TenantMember.member_id.desc()
    ).limit(limit + 1)
    rows = (await sess.execute(stmt)).all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last_member, _ = page_rows[-1]
        next_cursor = encode_cursor(
            {"o": last_member.created_at.isoformat(), "i": str(last_member.member_id)}
        )
    items = [
        TenantMemberItem(
            member_id=member.member_id,
            user_id=member.user_id,
            display_name=display_name,
            member_roles=list(member.member_roles or []),
            status=member.status,
            joined_at=member.created_at,
        )
        for member, display_name in page_rows
    ]
    return Page(items=items, next_cursor=next_cursor)


async def add_member(
    sess: AsyncSession,
    tenant_id: UUID,
    req: TenantMemberCreateRequest,
    *,
    actor_id: str,
) -> TenantMemberItem:
    """POST members：bind_tenant 后写 tenant_members（ORM → 切面
    TENANT_MEMBERS_CREATE 审计行）。

    - 租户不存在 → 404；member_roles 空数组 → 400 VALIDATION_ERROR
      （语义拒绝与请求体校验同口径，W5 评审裁定）；
    - user_id 须为目标租户内 ACTIVE 用户（users FORCE RLS，绑定后 0 行
      即 404，不泄露存在性）；已在册 → 409（uq_tenant_member 先查再插
      + IntegrityError 兜底）。
    """
    if await get_tenant(sess, tenant_id) is None:
        raise EdpError.not_found("租户不存在")
    if not req.member_roles:
        raise EdpError.validation_error("member_roles 不能为空数组")
    await bind_tenant(sess, tenant_id)
    user = await sess.get(UserRow, req.user_id)
    if user is None or user.status != "ACTIVE":
        raise EdpError.not_found("用户不存在")
    existing = (
        await sess.execute(
            select(TenantMember.member_id).where(
                TenantMember.tenant_id == tenant_id,
                TenantMember.user_id == req.user_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise EdpError.conflict("用户已是该租户成员")
    now = datetime.now(UTC)
    member = TenantMember(
        member_id=uuid4(),
        tenant_id=tenant_id,
        user_id=req.user_id,
        member_roles=list(req.member_roles),
        status="ACTIVE",
        invited_by=actor_id,
        created_at=now,
        updated_at=now,
        created_by=actor_id,
        updated_by=actor_id,
    )
    sess.add(member)
    try:
        await sess.flush()
    except IntegrityError:
        await sess.rollback()
        raise EdpError.conflict("用户已是该租户成员") from None
    return TenantMemberItem(
        member_id=member.member_id,
        user_id=member.user_id,
        display_name=user.display_name,
        member_roles=list(member.member_roles),
        status=member.status,
        joined_at=member.created_at,
    )


async def update_member(
    sess: AsyncSession,
    tenant_id: UUID,
    member_id: UUID,
    req: TenantMemberUpdateRequest,
    *,
    actor_id: str,
) -> TenantMemberItem:
    """PATCH member（改角色/禁用；ORM 赋值 → 切面 TENANT_MEMBERS_UPDATE）。

    - bind_tenant 后 RLS 天然收敛：跨租户/不存在 member_id 统一 404；
    - member_roles 提供且为空数组 → 400 VALIDATION_ERROR（同 add_member
      口径，W5 评审裁定）；
    - 最后 ACTIVE ADMIN 保护：本次变更会使租户内 ACTIVE ADMIN 数归零
      （禁用该成员或移除其 ADMIN 角色，且无其他 ACTIVE ADMIN）→
      400 VALIDATION_ERROR。
    """
    if await get_tenant(sess, tenant_id) is None:
        raise EdpError.not_found("租户不存在")
    if req.member_roles is not None and not req.member_roles:
        raise EdpError.validation_error("member_roles 不能为空数组")
    await bind_tenant(sess, tenant_id)
    member = await sess.get(TenantMember, member_id)
    if member is None or member.tenant_id != tenant_id:
        raise EdpError.not_found("成员不存在")
    new_roles = (
        list(req.member_roles)
        if req.member_roles is not None
        else list(member.member_roles or [])
    )
    new_status = req.status if req.status is not None else member.status
    await _ensure_last_active_admin_preserved(sess, member, new_roles, new_status)
    now = datetime.now(UTC)
    if req.member_roles is not None:
        member.member_roles = new_roles
    if req.status is not None:
        member.status = new_status
    member.updated_at = now
    member.updated_by = actor_id
    await sess.flush()
    display_name = (
        await sess.execute(
            select(UserRow.display_name).where(UserRow.user_id == member.user_id)
        )
    ).scalar_one_or_none()
    return TenantMemberItem(
        member_id=member.member_id,
        user_id=member.user_id,
        display_name=display_name,
        member_roles=list(member.member_roles or []),
        status=member.status,
        joined_at=member.created_at,
    )


async def _ensure_last_active_admin_preserved(
    sess: AsyncSession, member: TenantMember, new_roles: list[str], new_status: str
) -> None:
    """禁用/降级守卫：变更成员原为 ACTIVE ADMIN、变更后不再是，且租户内
    无其他 ACTIVE ADMIN → 400 VALIDATION_ERROR（不可禁用最后一个
    ACTIVE ADMIN）。非 ADMIN 成员的普通变更不受限。

    check-then-act 竞态窗口登记：count 查询与写回 flush 非原子，并发
    变更两个 ADMIN 可能双双通过守卫——单副本部署语义可接受，分布式锁
    （Redis）评估 T17 覆盖。
    """
    was_admin = "ADMIN" in (member.member_roles or []) and member.status == "ACTIVE"
    still_admin = "ADMIN" in new_roles and new_status == "ACTIVE"
    if not was_admin or still_admin:
        return
    others = (
        await sess.execute(
            select(func.count())
            .select_from(TenantMember)
            .where(
                TenantMember.tenant_id == member.tenant_id,
                TenantMember.member_id != member.member_id,
                TenantMember.status == "ACTIVE",
                TenantMember.member_roles.contains(["ADMIN"]),
            )
        )
    ).scalar_one()
    if others == 0:
        raise EdpError.validation_error("不能禁用或降级租户内最后一个 ACTIVE ADMIN")


async def get_quota_detail(sess: AsyncSession, tenant_id: UUID) -> TenantQuotaDetail:
    """GET quotas：B.14 七字段完整配额对象（+tenant_id）；租户不存在 → 404；
    配额行缺失容忍为默认值实例（updated_at 为 None）。"""
    if await get_tenant(sess, tenant_id) is None:
        raise EdpError.not_found("租户不存在")
    quota = await get_quota(sess, tenant_id)
    return TenantQuotaDetail.model_validate(quota)


async def update_quota(
    sess: AsyncSession,
    tenant_id: UUID,
    req: TenantQuotaUpdateRequest,
    *,
    actor_id: str,
    principal: Principal,
) -> TenantQuotaDetail:
    """PATCH quotas（B.14 临时提额）：仅 api_rate_limit / storage_gb /
    events_per_month 三字段可调（batch_max_events / query_timeout_ms /
    pool_share 不在本端点口径内）。

    - reason 必填非空 → 缺失/空白 400 VALIDATION_ERROR（W5 评审裁定，
      与请求体校验同口径）；
    - 审计留痕双行：ORM 赋值触发切面 TENANT_QUOTAS_UPDATE（before/after
      diff）+ record_explicit 补 TENANT_QUOTAS_ADJUST（detail 携带
      reason 与变更清单——「临时提额留痕」的业务语义行）；
    - 配额行缺失时以默认值实例补落库（健康租户不应出现，防御性口径）；
    - check-then-act 竞态窗口登记：读配额行 → 属性赋值 → flush 非原子，
      并发 PATCH 后写覆盖前写（丢失更新）——单副本部署语义可接受，
      分布式锁（Redis）评估 T17 覆盖。
    """
    if await get_tenant(sess, tenant_id) is None:
        raise EdpError.not_found("租户不存在")
    if not (req.reason or "").strip():
        raise EdpError.validation_error("调整配额必须填写 reason（临时提额留痕）")
    quota = await sess.get(TenantQuota, tenant_id)
    now = datetime.now(UTC)
    if quota is None:
        quota = await get_quota(sess, tenant_id)
        quota.created_at = now
        quota.created_by = actor_id
        sess.add(quota)
    changes: dict[str, dict[str, int]] = {}
    for field in ("api_rate_limit", "storage_gb", "events_per_month"):
        value = getattr(req, field)
        if value is not None:
            changes[field] = {"before": getattr(quota, field), "after": value}
            setattr(quota, field, value)
    quota.updated_at = now
    quota.updated_by = actor_id
    if changes:
        await audit_service.record_explicit(
            sess,
            action=ACTION_QUOTA_ADJUST,
            resource_type="tenant_quotas",
            resource_id=str(tenant_id),
            detail={"reason": req.reason, "changes": changes},
            principal=principal,
        )
    await sess.flush()
    return TenantQuotaDetail.model_validate(quota)


# ---- W6 平台用户目录（W5-11 收口：GET /api/v1/admin/users） ----


def _parse_user_anchor(decoded: dict) -> tuple[str, UUID] | None:
    """cursor 载荷 → (username, user_id)；缺字段/格式非法 → None。"""
    try:
        return str(decoded["u"]), UUID(str(decoded["i"]))
    except (KeyError, TypeError, ValueError):
        return None


async def list_users(
    sess: AsyncSession,
    principal: Principal,
    *,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> Page[AdminUserItem]:
    """GET /admin/users：username ASC keyset 游标（user_id tiebreak，锚
    ``{"u","i"}``；非法 cursor 视为首页）简投影——邀请成员下拉真数据源。

    RLS：platform.users FORCE RLS——bind_tenant 到平台管理员主租户
    （principal.tenant_id）。**W6 最小口径留痕**：目录范围 = 平台管理员
    主租户内用户（B.14 未定义平台用户目录，跨租户目录与 RLS 语义待后续
    契约裁定）；display_name 可空透传。
    """
    await bind_tenant(sess, principal.tenant_id)
    limit = max(1, min(limit, MAX_LIMIT))
    stmt = select(UserRow).where(UserRow.tenant_id == principal.tenant_id)
    decoded = decode_cursor(cursor)
    if decoded is not None:
        anchor = _parse_user_anchor(decoded)
        if anchor is not None:
            username, anchor_user_id = anchor
            stmt = stmt.where(
                or_(
                    UserRow.username > username,
                    and_(
                        UserRow.username == username,
                        UserRow.user_id > anchor_user_id,
                    ),
                )
            )
    stmt = stmt.order_by(UserRow.username.asc(), UserRow.user_id.asc()).limit(
        limit + 1
    )
    rows = (await sess.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor({"u": last.username, "i": str(last.user_id)})
    return Page(
        items=[
            AdminUserItem(
                user_id=row.user_id,
                username=row.username,
                display_name=row.display_name,
            )
            for row in page_rows
        ],
        next_cursor=next_cursor,
    )
