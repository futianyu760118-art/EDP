"""T6 令牌桶单测（假时钟）：容量消耗 / Retry-After 计算 / 惰性回填与容量
上限 / 80% 告警每耗尽窗口一次 / 配额 <=0 不限流。
"""

from uuid import uuid4

from edp_api.modules.tenantmgmt import ratelimit


def setup_function() -> None:
    ratelimit.reset_buckets()


def test_full_bucket_allows_capacity_then_rejects() -> None:
    tid = uuid4()
    warnings = 0
    for _ in range(100):
        retry, near = ratelimit.check_rate_limit(tid, 100, now=0.0)
        assert retry == 0
        warnings += 1 if near else 0
    assert warnings == 1  # 耗尽途中首次跌破 20% 告警一次
    retry, near = ratelimit.check_rate_limit(tid, 100, now=0.0)
    assert retry >= 1
    assert near is False


def test_retry_after_math_and_refill() -> None:
    tid = uuid4()
    # limit=60/min → 1 token/s：耗尽后需 1 秒
    for _ in range(60):
        ratelimit.check_rate_limit(tid, 60, now=0.0)
    retry, _ = ratelimit.check_rate_limit(tid, 60, now=0.0)
    assert retry == 1
    # 0.5s 后补 0.5 个令牌：仍不足，ceil(0.5/1)=1
    retry, _ = ratelimit.check_rate_limit(tid, 60, now=0.5)
    assert retry == 1
    # 1.0s 后可取
    retry, _ = ratelimit.check_rate_limit(tid, 60, now=1.0)
    assert retry == 0


def test_refill_is_capped_at_capacity() -> None:
    tid = uuid4()
    for _ in range(30):
        ratelimit.check_rate_limit(tid, 60, now=0.0)
    # 10 分钟后回满（不超容量）→ 可再取 60 个
    for _ in range(60):
        retry, _ = ratelimit.check_rate_limit(tid, 60, now=600.0)
        assert retry == 0
    retry, _ = ratelimit.check_rate_limit(tid, 60, now=600.0)
    assert retry >= 1


def test_near_limit_warning_once_per_depletion_window() -> None:
    tid = uuid4()
    warnings = 0
    for _ in range(60):
        _, near = ratelimit.check_rate_limit(tid, 60, now=0.0)
        warnings += 1 if near else 0
    assert warnings == 1  # 首次跌破 20% 告警一次

    # 回满后再次耗尽 → 第二次告警（新窗口）：先取一个触发回填并把 warned
    # 重置（tokens 回升到 20% 以上），再耗尽一轮
    ratelimit.check_rate_limit(tid, 60, now=600.0)
    warnings = 0
    for _ in range(60):
        _, near = ratelimit.check_rate_limit(tid, 60, now=600.0)
        warnings += 1 if near else 0
    assert warnings == 1


def test_zero_or_negative_limit_disables() -> None:
    tid = uuid4()
    for _ in range(10):
        retry, near = ratelimit.check_rate_limit(tid, 0, now=0.0)
        assert (retry, near) == (0, False)


def test_buckets_are_per_tenant() -> None:
    a, b = uuid4(), uuid4()
    for _ in range(60):
        ratelimit.check_rate_limit(a, 60, now=0.0)
    assert ratelimit.check_rate_limit(a, 60, now=0.0)[0] >= 1
    assert ratelimit.check_rate_limit(b, 60, now=0.0)[0] == 0
