"""T3 质量口径纯函数单测（EDP-030）：对账偏差边界 / 覆盖率空集 / 线性扣减
评分 / kpi 与维度派生表驱动 / 期望基数常量——不触达数据库。
"""

from collections import Counter

from edp_adapters.demo_dataset import SNAPSHOT_RECORDS
from edp_api.modules.quality import service as quality_service
from edp_api.modules.quality.schemas import (
    ChecksumSampling,
    CoverageReport,
    DimensionScore,
    OrphansReport,
    QualityKpi,
    ReconciliationRow,
)


def _row(
    source_system: str = "erp",
    object_type: str = "ORDER",
    source_count: int | None = 10,
    edp_count: int = 10,
    deviation_pct: float = 0.0,
    ok: bool = True,
) -> ReconciliationRow:
    return ReconciliationRow(
        source_system=source_system,
        object_type=object_type,
        source_count=source_count,
        edp_count=edp_count,
        deviation_pct=deviation_pct,
        ok=ok,
    )


# ---- 对账偏差：边界 2.0 含 / 2.1 断 / 降级行 ----


def test_deviation_pct_table() -> None:
    """表驱动：20/1000 → 2.0 边界 ok=true；21/1000 → 2.1 ok=false；
    source 为 None/0 → (0.0, True) 降级。"""
    cases = [
        ((1000, 1000), (0.0, True)),
        ((1000, 980), (2.0, True)),  # 边界含
        ((1000, 979), (2.1, False)),
        ((1000, 1020), (2.0, True)),  # 反向偏差同口径
        ((1000, 1021), (2.1, False)),
        ((100, 80), (20.0, False)),
        ((20, 1000), (4900.0, False)),
        ((None, 7), (0.0, True)),  # real/无水位降级
        ((0, 7), (0.0, True)),  # 零基数降级
        ((0, 0), (0.0, True)),
    ]
    for (source, edp), expected in cases:
        assert quality_service.deviation_pct(source, edp) == expected, (source, edp)


def test_deviation_pct_rounds_before_threshold_judgement() -> None:
    """展示与判定一致：原始 2.083 四舍五入展示 2.08 → ok=false；
    1/2400 展示 0.04 → ok=true。"""
    pct, ok = quality_service.deviation_pct(2400, 2399)
    assert (pct, ok) == (0.04, True)
    pct, ok = quality_service.deviation_pct(2400, 2350)
    assert (pct, ok) == (2.08, False)


# ---- 覆盖率：9/10 → 90.0；空集约定 100.0 ----


def test_coverage_pct_table() -> None:
    cases = [
        ((9, 10), 90.0),
        ((10, 10), 100.0),
        ((0, 10), 0.0),
        ((0, 0), 100.0),  # 空集约定（docstring 留痕）
        ((1, 3), 33.3),  # round 1 位
        ((2, 3), 66.7),
    ]
    for (connected, registered), expected in cases:
        assert quality_service.coverage_pct(connected, registered) == expected


# ---- 段内评分：零异常满分 / 线性扣减 / 分母 0 满分 ----


def test_score_from_anomaly_rate_table() -> None:
    cases = [
        ((0, 0), 100.0),  # 段内无数据 → 无缺口
        ((0, 10), 100.0),
        ((1, 10), 90.0),
        ((5, 10), 50.0),
        ((10, 10), 0.0),
        ((3, 9), 66.7),
        ((1, 3), 66.7),
    ]
    for (bad, total), expected in cases:
        assert quality_service.score_from_anomaly_rate(bad, total) == expected


# ---- 维度派生：表驱动（孤儿构造命中/未命中） ----


def test_derive_dimensions_all_clean_full_scores() -> None:
    dimensions = quality_service.derive_dimensions(
        reconciliation=[_row(), _row("plm", "PRODUCT")],
        coverage_overall=100.0,
        orphan_counts=quality_service.OrphanCounts(0, 0, 50, 30),
        sampling=ChecksumSampling(sampled=4, failed=0),
    )
    assert [(d.domain, d.score_pct) for d in dimensions] == [
        ("reconciliation", 100.0),
        ("coverage", 100.0),
        ("orphans", 100.0),
        ("checksum", 100.0),
    ]
    assert all(d.label for d in dimensions)


def test_derive_dimensions_table() -> None:
    """表驱动：四段各自异常构造 → 对应维度扣减、其余不受影响。"""
    cases = [
        # (reconciliation 行集, coverage, orphans, sampling) → 四维分
        (
            # 对账 2 组（均有期望基数）中 1 组超阈 → 50.0；降级行不计分母
            [_row(source_count=1000, edp_count=900, deviation_pct=10.0, ok=False),
             _row(object_type="BOM", source_count=100, edp_count=100)],
            100.0,
            quality_service.OrphanCounts(0, 0, 40, 30),
            ChecksumSampling(sampled=10, failed=0),
            [50.0, 100.0, 100.0, 100.0],
        ),
        (
            # 覆盖率 90.0 直通维度
            [_row()],
            90.0,
            quality_service.OrphanCounts(0, 0, 40, 30),
            ChecksumSampling(sampled=10, failed=0),
            [100.0, 90.0, 100.0, 100.0],
        ),
        (
            # 孤儿命中：2/(40+30) 扣减 → 97.1；未命中对照见上行
            [_row()],
            100.0,
            quality_service.OrphanCounts(1, 1, 40, 30),
            ChecksumSampling(sampled=10, failed=0),
            [100.0, 100.0, 97.1, 100.0],
        ),
        (
            # 孤儿未命中：0/(40+30) → 满分
            [_row()],
            100.0,
            quality_service.OrphanCounts(0, 0, 40, 30),
            ChecksumSampling(sampled=10, failed=0),
            [100.0, 100.0, 100.0, 100.0],
        ),
        (
            # checksum 1/4 失配 → 75.0
            [_row()],
            100.0,
            quality_service.OrphanCounts(0, 0, 40, 30),
            ChecksumSampling(sampled=4, failed=1),
            [100.0, 100.0, 100.0, 75.0],
        ),
        (
            # 全空段：降级对账（无期望基数组）+ 空 coverage/orphans/checksum
            [_row(source_count=None, edp_count=3)],
            100.0,
            quality_service.OrphanCounts(0, 0, 0, 0),
            ChecksumSampling(sampled=0, failed=0),
            [100.0, 100.0, 100.0, 100.0],
        ),
    ]
    for reconciliation, coverage, orphans, sampling, expected in cases:
        dimensions = quality_service.derive_dimensions(
            reconciliation=reconciliation,
            coverage_overall=coverage,
            orphan_counts=orphans,
            sampling=sampling,
        )
        assert [d.score_pct for d in dimensions] == expected


def test_derive_dimensions_orphan_hit_vs_miss() -> None:
    """孤儿构造命中/未命中直证：同总量下 2 孤儿 → 97.1；0 孤儿 → 100。"""
    miss = quality_service.derive_dimensions(
        reconciliation=[],
        coverage_overall=100.0,
        orphan_counts=quality_service.OrphanCounts(0, 0, 10, 10),
        sampling=ChecksumSampling(sampled=0, failed=0),
    )
    hit = quality_service.derive_dimensions(
        reconciliation=[],
        coverage_overall=100.0,
        orphan_counts=quality_service.OrphanCounts(1, 1, 10, 10),
        sampling=ChecksumSampling(sampled=0, failed=0),
    )
    by_domain = {d.domain: d.score_pct for d in hit}
    assert by_domain["orphans"] == 90.0  # 2/20 扣减
    assert {d.domain: d.score_pct for d in miss}["orphans"] == 100.0


# ---- kpi 派生：均分 / sla / completeness / 计数透传 ----


def test_derive_kpi_table() -> None:
    dimensions = [
        DimensionScore(domain="reconciliation", label="a", score_pct=100.0),
        DimensionScore(domain="coverage", label="b", score_pct=100.0),
        DimensionScore(domain="orphans", label="c", score_pct=100.0),
        DimensionScore(domain="checksum", label="d", score_pct=75.0),
    ]
    kpi = quality_service.derive_kpi(
        dimensions=dimensions,
        coverage_overall=90.0,
        sampling=ChecksumSampling(sampled=4, failed=1),
        pending_exceptions=7,
        high_priority=4,
    )
    assert kpi.overall_pct == 93.8  # (100+100+100+75)/4 = 93.75 → 93.8
    assert kpi.sla_pct == 75.0  # (4-1)/4
    assert kpi.completeness_pct == 90.0  # coverage 直通
    assert kpi.pending_exceptions == 7
    assert kpi.high_priority == 4
    assert set(QualityKpi.model_fields) == {
        "overall_pct",
        "sla_pct",
        "completeness_pct",
        "pending_exceptions",
        "high_priority",
    }  # 形状对齐 mocks/types.ts QualityKpi


def test_derive_kpi_empty_dimensions_and_zero_sample() -> None:
    """空维度 → overall 100.0；sampled=0 → sla 100.0。"""
    kpi = quality_service.derive_kpi(
        dimensions=[],
        coverage_overall=100.0,
        sampling=ChecksumSampling(sampled=0, failed=0),
        pending_exceptions=0,
        high_priority=0,
    )
    assert kpi.overall_pct == 100.0
    assert kpi.sla_pct == 100.0


# ---- 期望基数：SNAPSHOT 常量分组 ----


def test_expected_source_counts_match_dataset() -> None:
    counts = quality_service.expected_source_counts()
    expected = Counter(
        (record.source_system, record.object_type) for record in SNAPSHOT_RECORDS
    )
    assert counts == dict(expected)
    assert counts[("erp", "ORDER")] == expected[("erp", "ORDER")]
    assert counts[("mes", "CAPACITY")] == 3


# ---- 响应形状：kpi/dimensions 字段名逐字对齐 mocks/types.ts ----


def test_report_schema_shape_matches_mocks() -> None:
    """字段名逐字对齐 frontend mocks/types.ts 的 QualityReport 族。"""
    assert set(QualityKpi.model_fields) == {
        "overall_pct",
        "sla_pct",
        "completeness_pct",
        "pending_exceptions",
        "high_priority",
    }
    assert set(DimensionScore.model_fields) == {"domain", "label", "score_pct"}
    assert set(ReconciliationRow.model_fields) == {
        "source_system",
        "object_type",
        "source_count",
        "edp_count",
        "deviation_pct",
        "ok",
    }
    assert set(CoverageReport.model_fields) == {"overall_pct", "by_type"}
    assert set(OrphansReport.model_fields) == {
        "event_orphans",
        "evidence_orphans",
    }
