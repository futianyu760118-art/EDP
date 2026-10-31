"""T10 租户上下文纯逻辑单测：ensure_tenant_usable 状态矩阵 + 时序垫片。"""

import time

import pytest
from edp_api.core.errors import EdpError, ErrorCode
from edp_api.core.security.password import (
    hash_password,
    timing_dummy_verify,
    verify_password,
)
from edp_api.core.tenant_context import ensure_tenant_usable


def test_active_passes() -> None:
    ensure_tenant_usable("ACTIVE")


@pytest.mark.parametrize("status", ["SUSPENDED", "CANCELLED"])
def test_blocked_statuses_raise_tenant_suspended(status: str) -> None:
    with pytest.raises(EdpError) as exc_info:
        ensure_tenant_usable(status)
    assert exc_info.value.code == ErrorCode.TENANT_SUSPENDED
    assert exc_info.value.http_status == 403


@pytest.mark.parametrize("status", ["PROVISIONING", "SOMETHING_NEW", None])
def test_other_statuses_raise_tenant_forbidden(status: str | None) -> None:
    with pytest.raises(EdpError) as exc_info:
        ensure_tenant_usable(status)
    assert exc_info.value.code == ErrorCode.TENANT_FORBIDDEN
    assert exc_info.value.http_status == 403


def test_timing_dummy_verify_costs_like_real_verify() -> None:
    """垫片与真实失败校验的耗时同数量级（防用户名枚举的时序等价基础）。"""
    real_hash = hash_password("correct-password")

    t0 = time.perf_counter()
    assert verify_password("wrong-password", real_hash) is False
    real_ms = (time.perf_counter() - t0) * 1000

    t1 = time.perf_counter()
    timing_dummy_verify("wrong-password")
    dummy_ms = (time.perf_counter() - t1) * 1000

    assert real_ms > 5  # 真实 argon2 成本存在
    assert dummy_ms > 5  # 垫片等价，而非空操作
    # 同数量级（比值在 0.25~4 倍内，避免绝对时间断言的抖动）
    assert 0.25 <= dummy_ms / real_ms <= 4
