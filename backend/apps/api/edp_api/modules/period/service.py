"""period 服务（V1.2 T24）：AEOS 经营周期纯函数。

AEOS 经营窗口：上月16日 ～ 当月15日（V1.1 第十二节）。
- 某日所属 AEOS 周期：day ≥ 16 → 窗口 [当月16, 次月15)，label = 当月
  （AEOS-{YYYY}-{MM}）；day < 16 → 窗口 [上月16, 当月15)，label = 上月；
- 其余周期：自然日 / ISO 自然周（YYYY-Www）/ 自然月 / 滚动7天 / 滚动30天；
- 全部纯函数（无 IO/无 now 依赖），入参日期缺省由调用方提供。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

AEOS_DAY_START = 16  # AEOS 窗口起始日（含）
AEOS_DAY_END = 15  # AEOS 窗口结束日（含，相对 start 月次月）

PERIOD_KINDS = (
    "DAILY",
    "WEEKLY",
    "MONTHLY",
    "AEOS",
    "CUSTOM",
    "ROLLING_7D",
    "ROLLING_30D",
)


@dataclass(frozen=True, slots=True)
class PeriodWindow:
    """周期窗口（start 含 / end 含，date 粒度）。"""

    kind: str
    label: str
    start: date
    end: date


def aeos_window_for(day: date) -> PeriodWindow:
    """某日所属 AEOS 周期窗口。

    day ≥ 16：窗口 [当月16, 次月15]，label=当月；day < 16：窗口
    [上月16, 当月15]，label=上月。
    """
    if day.day >= AEOS_DAY_START:
        label_month = day
    else:
        label_month = _previous_month(day)
    start = date(label_month.year, label_month.month, AEOS_DAY_START)
    end_month = _next_month(start)
    end = date(end_month.year, end_month.month, AEOS_DAY_END)
    return PeriodWindow(
        kind="AEOS",
        label=f"AEOS-{label_month.year:04d}-{label_month.month:02d}",
        start=start,
        end=end,
    )


def daily_window(day: date) -> PeriodWindow:
    return PeriodWindow(kind="DAILY", label=day.isoformat(), start=day, end=day)


def weekly_window(day: date) -> PeriodWindow:
    iso = day.isocalendar()
    start = day - timedelta(days=iso.weekday)
    end = start + timedelta(days=6)
    return PeriodWindow(
        kind="WEEKLY", label=f"{iso.year:04d}-W{iso.week:02d}", start=start, end=end
    )


def monthly_window(day: date) -> PeriodWindow:
    start = date(day.year, day.month, 1)
    end = date(_next_month(start).year, _next_month(start).month, 1) - timedelta(days=1)
    return PeriodWindow(
        kind="MONTHLY", label=f"{day.year:04d}-{day.month:02d}", start=start, end=end
    )


def rolling_window(day: date, days: int) -> PeriodWindow:
    start = day - timedelta(days=days - 1)
    return PeriodWindow(
        kind=f"ROLLING_{days}D",
        label=f"ROLLING_{days}D:{start.isoformat()}",
        start=start,
        end=day,
    )


def compute_period(kind: str, day: date) -> PeriodWindow:
    """按 kind 计算窗口；未知 kind → ValueError（路由层枚举已收敛）。"""
    if kind == "DAILY":
        return daily_window(day)
    if kind == "WEEKLY":
        return weekly_window(day)
    if kind == "MONTHLY":
        return monthly_window(day)
    if kind == "AEOS":
        return aeos_window_for(day)
    if kind == "ROLLING_7D":
        return rolling_window(day, 7)
    if kind == "ROLLING_30D":
        return rolling_window(day, 30)
    if kind == "CUSTOM":
        raise ValueError("CUSTOM 周期需显式 start/end（本服务不提供存储，调用方自定）")
    raise ValueError(f"未知周期类型：{kind}")


def _previous_month(day: date) -> date:
    """上月首日（label 定位用）。"""
    month = day.month - 1
    year = day.year if month > 0 else day.year - 1
    return date(year, month or 12, 1)


def _next_month(day: date) -> date:
    month = day.month + 1
    year = day.year + month // 13
    month = month % 12 or 12
    return date(year, month, 1)


def now_utc() -> datetime:
    """当前时刻（服务入口注入点；测试可 monkeypatch 亦可不依赖——纯函数层
    保持无 IO，仅此单点与时钟交互）。"""
    return datetime.now(UTC)
