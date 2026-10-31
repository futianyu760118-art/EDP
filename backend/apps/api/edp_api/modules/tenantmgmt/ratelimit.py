"""租户限流（EDP-025，设计 3.5 应用层令牌桶）。

- 进程内 per-tenant 令牌桶：capacity = ``tenant_quotas.api_rate_limit``
  （默认 100 req/min），惰性补充（refill = limit/60 每秒）；
- 取不到令牌 → ``check_rate_limit`` 返回 Retry-After 秒数，调用方
  （tenant_scoped）经独立会话落 ``RATE_LIMITED`` 审计 + ``throttled_429``
  计数（请求随后 429，请求事务回滚，审计不能依赖请求会话）；
- 水位首次 ≤20% → 一次性告警审计（``RATE_LIMIT_WARNING``），桶回升到
  阈值以上后重置标记（每耗尽窗口一次）。注意：水位回升过 20% 即重置告警
  标记（非回满重置）——边界震荡流量下同窗口可能多次告警，噪音有界；
- 单副本语义：多副本部署下实际速率 ≈ limit×副本数，网关层全局限流兜底
  （设计 3.5「网关 + 应用双层」的应用侧实现；租户维度需鉴权后信息，网关
  侧无法按租户分键，全局样例见 deploy/nginx-limit-req.conf.example）。

测试接缝：``reset_buckets()`` 清空进程内桶（集成测试 conftest 每用例调用）。
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from uuid import UUID

from edp_api.core import db as core_db
from edp_api.core.db import bind_tenant
from edp_api.core.security.principal import Principal
from edp_api.modules.audit import service as audit_service
from edp_api.modules.tenantmgmt import service as tenantmgmt_service

logger = logging.getLogger(__name__)

RATE_LIMITED_ACTION = "RATE_LIMITED"
RATE_LIMIT_WARNING_ACTION = "RATE_LIMIT_WARNING"
RESOURCE_TYPE = "ratelimit"

_WARN_RATIO = 0.2


@dataclass(slots=True)
class _Bucket:
    tokens: float
    last_refill: float
    warned: bool = False


_buckets: dict[UUID, _Bucket] = {}


def reset_buckets() -> None:
    """清空进程内令牌桶（集成测试隔离接缝）。"""
    _buckets.clear()


def check_rate_limit(
    tenant_id: UUID, limit_per_min: int, *, now: float | None = None
) -> tuple[int, bool]:
    """取一个令牌（惰性补充）。

    Returns:
        ``(retry_after_seconds, near_limit)``——成功 ``(0, 是否首次触及
        80% 告警)``；拒绝 ``(>=1 的 Retry-After 秒数, False)``。
        配额 <=0 视为不限流。
    """
    if limit_per_min <= 0:
        return 0, False
    clock = time.monotonic() if now is None else now
    rate = limit_per_min / 60.0
    bucket = _buckets.get(tenant_id)
    if bucket is None:
        bucket = _Bucket(tokens=float(limit_per_min), last_refill=clock)
        _buckets[tenant_id] = bucket

    elapsed = max(0.0, clock - bucket.last_refill)
    bucket.tokens = min(float(limit_per_min), bucket.tokens + elapsed * rate)
    bucket.last_refill = clock

    if bucket.tokens < 1.0:
        retry_after = max(1, math.ceil((1.0 - bucket.tokens) / rate))
        return retry_after, False

    bucket.tokens -= 1.0
    near_limit = False
    if bucket.tokens / limit_per_min <= _WARN_RATIO:
        if not bucket.warned:
            bucket.warned = True
            near_limit = True
    else:
        bucket.warned = False
    return 0, near_limit


async def _record_rate_audit(
    principal: Principal, *, action: str, path: str, detail: dict
) -> None:
    """独立会话写限流审计 + 用量计数（失败仅 warning，不改变 429 决策）。"""
    try:
        session = core_db.get_session_local()()
        try:
            await bind_tenant(session, principal.tenant_id)
            await audit_service.record_explicit(
                session,
                action=action,
                resource_type=RESOURCE_TYPE,
                resource_id=None,
                detail={"path": path, **detail},
                principal=principal,
            )
            if action == RATE_LIMITED_ACTION:
                await tenantmgmt_service.bump_usage_daily(
                    session, principal.tenant_id, throttled_429=1
                )
            await session.commit()
        finally:
            await session.close()
    except Exception:
        logger.warning("限流审计写入失败：%s", action, exc_info=True)


async def record_rate_limited(
    principal: Principal, *, path: str, retry_after: int, limit_per_min: int
) -> None:
    """429 拒绝留痕：审计 + throttled_429（独立会话提交）。"""
    await _record_rate_audit(
        principal,
        action=RATE_LIMITED_ACTION,
        path=path,
        detail={"retry_after": retry_after, "limit_per_min": limit_per_min},
    )


async def record_rate_warning(
    principal: Principal, *, path: str, limit_per_min: int
) -> None:
    """80% 水位告警审计（每耗尽窗口一次，独立会话提交）。"""
    await _record_rate_audit(
        principal,
        action=RATE_LIMIT_WARNING_ACTION,
        path=path,
        detail={"limit_per_min": limit_per_min},
    )


async def record_api_call(tenant_id: UUID) -> None:
    """api_calls 计量 +1（**独立短会话**，立即提交）。

    独立会话的原因：usage 行 upsert 会持有 ``(tenant_id, usage_date)`` 行锁
    直到请求事务结束——同事务写法下并发请求在该行上串行互等（长事务请求
    会阻塞同租户其他请求至 statement_timeout）。独立短会话把锁窗口压缩到
    计量语句本身。语义随之从「受理成功调用」变为「全部请求」（含失败），
    计量口径更直白；失败仅 warning，不影响请求。
    """
    try:
        session = core_db.get_session_local()()
        try:
            await tenantmgmt_service.bump_usage_daily(
                session, tenant_id, api_calls=1
            )
            await session.commit()
        finally:
            await session.close()
    except Exception:
        logger.warning("api_calls 计量写入失败", exc_info=True)
