"""W6 运营报告（EDP-034）测试：P95 直方图解析 + 各指标装配 + 空库 SQL 冒烟。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.ops_report import (  # noqa: E402
    build_metrics,
    collect_db_metrics,
    p95_from_histogram,
    parse_drills,
    parse_e2e_result,
    parse_loadtest,
)


def test_p95_from_histogram_recent_rank() -> None:
    # 100 次：10ms×50、20ms×30、100ms×20 → 95 分位落在 100ms 桶
    assert p95_from_histogram({"10": 50, "20": 30, "100": 20}, 100) == 100
    # 空/零请求 → None
    assert p95_from_histogram({}, 0) is None


def test_parse_loadtest_filters_aggregated_and_gates(tmp_path: Path) -> None:
    payload = [
        {
            "name": "GET /api/v1/events",
            "num_requests": 100,
            "num_failures": 0,
            "response_times": {"10": 90, "2000": 10},
        },
        {
            "name": "Aggregated",
            "num_requests": 100,
            "num_failures": 0,
            "response_times": {"9999": 100},
        },
    ]
    path = tmp_path / "locust.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    parsed = parse_loadtest(path)
    assert parsed["available"] is True
    assert [e["name"] for e in parsed["entries"]] == ["GET /api/v1/events"]
    assert parsed["max_p95_ms"] == 2000  # 95 分位落 2000ms 桶（10% 在尾部）
    assert parse_loadtest(tmp_path / "missing.json")["available"] is False


def test_parse_drills_and_e2e(tmp_path: Path) -> None:
    drills_path = tmp_path / "drills.json"
    drills_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "drill_type": "pitr",
                        "result": "SUCCEEDED",
                        "rto_seconds": 22.1,
                        "rpo_seconds": 0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert parse_drills(drills_path)["items"][0]["rto_seconds"] == 22.1
    assert parse_drills(tmp_path / "nope.json")["available"] is False

    e2e_path = tmp_path / "e2e.json"
    e2e_path.write_text(
        json.dumps({"closed_loop": {"passed": True}, "tenant_isolation": {"passed": True}}),
        encoding="utf-8",
    )
    assert parse_e2e_result(e2e_path)["available"] is True
    assert parse_e2e_result(tmp_path / "nope.json")["available"] is False


def _fake_db(**overrides: object) -> dict:
    base = {
        "coverage": {"overall_pct": 100.0, "by_type": []},
        "traceability": {"total": 0, "traced": 0, "pct": 100.0},
        "recall": {
            "expected_major": 4,
            "detected_major": 4,
            "matched": 4,
            "recall_pct": 100.0,
            "false_positives": 0,
            "false_positive_pct": 0.0,
            "false_positive_sample": [],
        },
        "closure": {"total": 2, "verified": 2, "pct": 100.0},
        "audit_completeness": {
            "covered_actions": 2,
            "total_actions": 2,
            "covered_cases": 1,
            "total_cases": 1,
            "covered_records": 1,
            "total_records": 1,
            "pct": 100.0,
        },
        "guard_denied": {"denied_count": 1, "export": [], "ai_human_only_success": 0},
    }
    base.update(overrides)
    return base


def test_build_metrics_all_pass_and_latency_gate() -> None:
    db = _fake_db()
    loadtest = {"available": True, "entries": [{"p95_ms": 1100}], "max_p95_ms": 1100}
    drills = {
        "available": True,
        "items": [
            {"drill_type": "pitr", "result": "SUCCEEDED", "rto_seconds": 22.1, "rpo_seconds": 0}
        ],
    }
    e2e = {"available": True, "closed_loop": {"passed": True}, "tenant_isolation": {"passed": True}}
    metrics = build_metrics(db, loadtest, drills, e2e)
    assert len(metrics) == 9
    assert all(m["passed"] for m in metrics)

    slow = {"available": True, "entries": [{"p95_ms": 2500}], "max_p95_ms": 2500}
    latency = next(m for m in build_metrics(db, slow, drills, e2e) if m["key"] == "latency")
    assert latency["passed"] is False

    recall_low = _fake_db(
        recall={
            "expected_major": 4,
            "detected_major": 3,
            "matched": 2,
            "recall_pct": 50.0,
            "false_positives": 1,
            "false_positive_pct": 33.3,
            "false_positive_sample": [],
        }
    )
    assert (
        next(m for m in build_metrics(recall_low, loadtest, drills, e2e) if m["key"] == "recall")[
            "passed"
        ]
        is False
    )


async def test_collect_db_metrics_smoke(database_url: str) -> None:
    """冒烟：全部 SQL 可执行 + 各指标结构自洽（不依赖空库——testcontainer 为会话共享，
    其他用例可能已写入数据；空集 100 约定由纯函数装配测试覆盖）。"""
    db = await collect_db_metrics(database_url)
    assert 0.0 <= db["coverage"]["overall_pct"] <= 100.0
    tr = db["traceability"]
    assert tr["traced"] <= tr["total"] and 0.0 <= tr["pct"] <= 100.0
    rc = db["recall"]
    assert rc["expected_major"] == 4  # 十场景中 P0/P1 期望数（dataset 常量）
    assert 0 <= rc["detected_major"]
    assert rc["matched"] + rc["false_positives"] == rc["detected_major"]
    assert 0.0 <= rc["recall_pct"] <= 100.0 and 0.0 <= rc["false_positive_pct"] <= 100.0
    cl = db["closure"]
    assert cl["verified"] <= cl["total"] and 0.0 <= cl["pct"] <= 100.0
    assert 0.0 <= db["audit_completeness"]["pct"] <= 100.0
    assert db["guard_denied"]["denied_count"] >= 0
    assert db["guard_denied"]["ai_human_only_success"] == 0
