"""period 纯函数单元测试（V1.2 T24）：AEOS 窗口边界 + ISO 周 + 滚动。"""

from datetime import date

from edp_api.modules.period import service as period_service


def test_aeos_window_day_ge_16_uses_current_month() -> None:
    window = period_service.aeos_window_for(date(2026, 10, 16))
    assert window.label == "AEOS-2026-10"
    assert window.start == date(2026, 10, 16)
    assert window.end == date(2026, 11, 15)


def test_aeos_window_day_lt_16_uses_previous_month() -> None:
    window = period_service.aeos_window_for(date(2026, 10, 10))
    assert window.label == "AEOS-2026-09"
    assert window.start == date(2026, 9, 16)
    assert window.end == date(2026, 10, 15)


def test_aeos_window_day_15_boundary() -> None:
    window = period_service.aeos_window_for(date(2026, 10, 15))
    assert window.label == "AEOS-2026-09"
    assert window.end == date(2026, 10, 15)


def test_aeos_window_year_crossing() -> None:
    window = period_service.aeos_window_for(date(2027, 1, 5))
    assert window.label == "AEOS-2026-12"
    assert window.start == date(2026, 12, 16)
    assert window.end == date(2027, 1, 15)


def test_weekly_window_iso() -> None:
    window = period_service.weekly_window(date(2026, 10, 12))  # 周一
    assert window.label.startswith("2026-W")
    assert (window.end - window.start).days == 6


def test_monthly_window() -> None:
    window = period_service.monthly_window(date(2026, 10, 10))
    assert window.start == date(2026, 10, 1)
    assert window.end == date(2026, 10, 31)


def test_rolling_window() -> None:
    w7 = period_service.rolling_window(date(2026, 10, 10), 7)
    assert w7.start == date(2026, 10, 4)
    assert w7.end == date(2026, 10, 10)
    w30 = period_service.rolling_window(date(2026, 10, 10), 30)
    assert w30.start == date(2026, 9, 11)


def test_compute_period_dispatch_and_unknown_kind() -> None:
    assert period_service.compute_period("AEOS", date(2026, 10, 10)).kind == "AEOS"
    assert period_service.compute_period("ROLLING_7D", date(2026, 10, 10)).kind == "ROLLING_7D"
    try:
        period_service.compute_period("NOPE", date(2026, 10, 10))
        raise AssertionError("未知周期类型应抛 ValueError")
    except ValueError:
        pass
