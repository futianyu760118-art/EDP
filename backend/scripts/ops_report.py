"""W6 运营报告一键导出（EDP-034，M6 Go/No-Go 指标表数据源）。

用法（在 backend/ 下，真栈 DB 就绪）：
    uv run python scripts/ops_report.py
    # 缺省路径（相对仓库根）：loadtest=deploy/loadtest/locust.json、
    # drills=deploy/drills/drill-records.json、
    # e2e-result=deploy/ops-report/e2e-result.json（可选，缺失记「待补」）；
    # DB 连接 = EDP_DATABASE_URL（须 migrator 角色——BYPASSRLS 平台全量口径）。
    # 产物：deploy/ops-report/w6-ops-report.json + docs/demo/w6-gonogo.md

九指标（开发计划 §7.2）口径留痕：
- 覆盖率：复用 quality.service.build_coverage（BYPASSRLS 下跨租户聚合）；
- 追溯率：P0/P1 证据（event_id 直指 P0/P1 事件，或经 evidence.links
  ref_type='RESULT' 关联 P0/P1 事件）→ 事件存在 且 对象注册存在 的比例；
- 召回率：十场景 RESULT_EVENTS 期望（P0/P1 = 重大风险）vs event.events 实测
  （仅 capability.result.* / adapter.sync.failed 检出面；放大实体
  source_id ~ '-[0-9]{6}$' 按 T5 约定排除）；误报 = 实测重大风险中非期望项；
- 闭环率：action.actions status='VERIFIED' / 总数（等价 action.verified 事件口径）；
- 越权：GUARD_DENIED 全量导出（信息性）+ 越权成功 probe（decision.records
  created_by 为 AI/服务身份计数，须 = 0；矩阵用例集 test_security_matrix CI 佐证）；
- 审计完整率：action/case/record 实体各自存在 ≥1 条对应审计行
  （ACTION_/CASE_/DECISION_ 前缀，resource_id 匹配）的覆盖比例；
- 延迟：locust.json 直方图 P95（各接口，Aggregated 除外），门槛 2000ms；
- 隔离：读 e2e-result.json（E2E 真栈 + 用例集结果标记）；
- HA：drills JSON 各演练 result=SUCCEEDED 且 rto_seconds ≤ 300（RTO<5min）。
"""

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent

DEFAULT_DB_URL = "postgresql+asyncpg://edp_migrator:edp_dev@localhost:15432/edp"
DEFAULT_LOADTEST = REPO_ROOT / "deploy/loadtest/locust.json"
DEFAULT_DRILLS = REPO_ROOT / "deploy/drills/drill-records.json"
DEFAULT_OUT_DIR = REPO_ROOT / "deploy/ops-report"
DEFAULT_GONOGO = REPO_ROOT / "docs/demo/w6-gonogo.md"

# 放大实体排除模式（T5 约定：seed --scale 追加实体 source_id 尾缀 6 位数字）
SCALED_PATTERN = r"-[0-9]{6}$"

_TRACEABILITY_SQL = text(
    """
    WITH p0p1 AS (
        SELECT r.evidence_id, r.object_id, r.event_id
          FROM evidence.records r
         WHERE r.event_id IN (
                   SELECT event_id FROM event.events
                    WHERE risk_level IN ('P0','P1'))
            OR r.evidence_id IN (
                   SELECT l.evidence_id FROM evidence.links l
                    JOIN event.events e ON e.event_id = l.ref_id
                   WHERE l.ref_type = 'RESULT'
                     AND e.risk_level IN ('P0','P1'))
    )
    SELECT count(*) AS total,
           count(*) FILTER (
               WHERE p.event_id IS NOT NULL
                 AND EXISTS (SELECT 1 FROM event.events e
                              WHERE e.event_id = p.event_id)
                 AND p.object_id IS NOT NULL
                 AND EXISTS (SELECT 1 FROM master.business_objects bo
                              WHERE bo.object_id = p.object_id)
           ) AS traced
      FROM p0p1 p
    """
)

_DETECTED_RISK_SQL = text(
    f"""
    SELECT e.event_type, bo.source_id, e.risk_level
      FROM event.events e
      JOIN master.business_objects bo ON bo.object_id = e.object_id
     WHERE e.risk_level IN ('P0','P1')
       AND (e.event_type LIKE 'capability.result.%'
            OR e.event_type = 'adapter.sync.failed')
       AND bo.source_id !~ '{SCALED_PATTERN}'
    """
)

_CLOSURE_SQL = text(
    """
    SELECT count(*) AS total,
           count(*) FILTER (WHERE status = 'VERIFIED') AS verified
      FROM action.actions
    """
)

_AUDIT_COMPLETENESS_SQL = text(
    """
    SELECT
      (SELECT count(*) FROM action.actions a
        WHERE EXISTS (SELECT 1 FROM platform.audit_logs al
                       WHERE al.action LIKE 'ACTION\\_%'
                         AND al.resource_id = a.action_id::text)) AS covered_actions,
      (SELECT count(*) FROM action.actions) AS total_actions,
      (SELECT count(*) FROM decision.cases c
        WHERE EXISTS (SELECT 1 FROM platform.audit_logs al
                       WHERE al.action LIKE 'CASE\\_%'
                         AND al.resource_id = c.case_id::text)) AS covered_cases,
      (SELECT count(*) FROM decision.cases) AS total_cases,
      (SELECT count(*) FROM decision.records r
        WHERE EXISTS (SELECT 1 FROM platform.audit_logs al
                       WHERE al.action LIKE 'DECISION\\_%'
                         AND al.resource_id = r.decision_id::text)) AS covered_records,
      (SELECT count(*) FROM decision.records) AS total_records
    """
)

_GUARD_DENIED_SQL = text(
    """
    SELECT audit_id, occurred_at, tenant_id, actor_type, actor_id,
           action, resource_type, resource_id, detail
      FROM platform.audit_logs
     WHERE action = 'GUARD_DENIED'
     ORDER BY occurred_at DESC, audit_id DESC
    """
)

_AI_RECORD_PROBE_SQL = text(
    """
    SELECT count(*) AS n
      FROM decision.records
     WHERE created_by LIKE 'agent:%'
        OR created_by LIKE 'ai:%'
        OR created_by LIKE 'service:%'
    """
)


def p95_from_histogram(response_times: dict[str, int], total: int) -> int | None:
    """locust 直方图（响应毫秒字符串键 → 计数）→ P95（毫秒，最近秩法）。"""
    if total <= 0:
        return None
    target = 0.95 * total
    cumulative = 0
    for key in sorted(response_times, key=lambda k: int(k)):
        cumulative += int(response_times[key])
        if cumulative >= target:
            return int(key)
    return None


def parse_loadtest(path: Path) -> dict[str, Any]:
    """locust --json 产物 → 各接口 P95 与门槛判定（Aggregated 除外）。"""
    if not path.exists():
        return {"available": False, "reason": f"缺 {path}", "entries": [], "max_p95_ms": None}
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = []
    for item in raw:
        if item.get("name") == "Aggregated":
            continue
        total = int(item.get("num_requests", 0))
        p95 = p95_from_histogram(item.get("response_times", {}), total)
        entries.append(
            {
                "name": item.get("name"),
                "requests": total,
                "failures": int(item.get("num_failures", 0)),
                "p95_ms": p95,
            }
        )
    max_p95 = max((e["p95_ms"] for e in entries if e["p95_ms"] is not None), default=None)
    return {"available": True, "entries": entries, "max_p95_ms": max_p95}


def parse_drills(path: Path) -> dict[str, Any]:
    """drill-records.json → HA 指标判定（SUCCEEDED 且 RTO ≤300s）。"""
    if not path.exists():
        return {"available": False, "reason": f"缺 {path}", "items": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    items = [
        {
            "drill_type": it.get("drill_type"),
            "result": it.get("result"),
            "rto_seconds": it.get("rto_seconds"),
            "rpo_seconds": it.get("rpo_seconds"),
        }
        for it in data.get("items", [])
    ]
    return {"available": True, "items": items}


def parse_e2e_result(path: Path) -> dict[str, Any]:
    """E2E/隔离结果标记（deploy/ops-report/e2e-result.json；缺失记「待补」）。"""
    if not path.exists():
        return {"available": False, "reason": f"缺 {path}（T10 E2E 本地/CI 结果标记）"}
    return {"available": True, **json.loads(path.read_text(encoding="utf-8"))}


async def collect_db_metrics(db_url: str) -> dict[str, Any]:
    """DB 直读六指标（BYPASSRLS 平台全量口径）。"""
    from edp_api.modules.demo.dataset import RESULT_EVENTS
    from edp_api.modules.quality.service import build_coverage

    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    out: dict[str, Any] = {}
    try:
        async with factory() as sess:
            coverage = await build_coverage(sess)
            out["coverage"] = {
                "overall_pct": coverage.overall_pct,
                "by_type": [
                    {"object_type": it.object_type, "coverage_pct": it.coverage_pct}
                    for it in coverage.by_type
                ],
            }

            trace = (await sess.execute(_TRACEABILITY_SQL)).one()
            out["traceability"] = {
                "total": trace.total,
                "traced": trace.traced,
                "pct": round(100.0 * trace.traced / trace.total, 2) if trace.total else 100.0,
            }

            expected_major = {
                (spec.event_type, spec.object_ref[1])
                for spec in RESULT_EVENTS
                if spec.risk_level in ("P0", "P1")
            }
            detected = [
                (row.event_type, row.source_id, row.risk_level)
                for row in (await sess.execute(_DETECTED_RISK_SQL)).all()
            ]
            matched = [d for d in detected if (d[0], d[1]) in expected_major]
            false_pos = [d for d in detected if (d[0], d[1]) not in expected_major]
            out["recall"] = {
                "expected_major": len(expected_major),
                "detected_major": len(detected),
                "matched": len(matched),
                "recall_pct": round(100.0 * len(matched) / len(expected_major), 2)
                if expected_major
                else 100.0,
                "false_positives": len(false_pos),
                "false_positive_pct": round(100.0 * len(false_pos) / len(detected), 2)
                if detected
                else 0.0,
                "false_positive_sample": [
                    {"event_type": d[0], "source_id": d[1]} for d in false_pos[:5]
                ],
            }

            closure = (await sess.execute(_CLOSURE_SQL)).one()
            out["closure"] = {
                "total": closure.total,
                "verified": closure.verified,
                "pct": round(100.0 * closure.verified / closure.total, 2)
                if closure.total
                else 100.0,
            }

            audit = (await sess.execute(_AUDIT_COMPLETENESS_SQL)).one()
            covered = audit.covered_actions + audit.covered_cases + audit.covered_records
            total_entities = audit.total_actions + audit.total_cases + audit.total_records
            out["audit_completeness"] = {
                "covered_actions": audit.covered_actions,
                "total_actions": audit.total_actions,
                "covered_cases": audit.covered_cases,
                "total_cases": audit.total_cases,
                "covered_records": audit.covered_records,
                "total_records": audit.total_records,
                "pct": round(100.0 * covered / total_entities, 2) if total_entities else 100.0,
            }

            denied_rows = (await sess.execute(_GUARD_DENIED_SQL)).all()
            out["guard_denied"] = {
                "denied_count": len(denied_rows),
                "export": [
                    {
                        "audit_id": row.audit_id,
                        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
                        "tenant_id": str(row.tenant_id) if row.tenant_id else None,
                        "actor_type": row.actor_type,
                        "actor_id": row.actor_id,
                        "resource_type": row.resource_type,
                        "resource_id": row.resource_id,
                        "detail": row.detail,
                    }
                    for row in denied_rows
                ],
                "ai_human_only_success": (await sess.execute(_AI_RECORD_PROBE_SQL)).scalar_one(),
            }
    finally:
        await engine.dispose()
    return out


def build_metrics(
    db: dict[str, Any], loadtest: dict[str, Any], drills: dict[str, Any], e2e: dict[str, Any]
) -> list[dict[str, Any]]:
    """九指标装配（指标/门槛/实测/判定/依据）。"""
    latency_ok = bool(loadtest.get("available")) and (
        loadtest.get("max_p95_ms") is not None and loadtest["max_p95_ms"] < 2000
    )
    drills_items = drills.get("items", [])
    ha_ok = bool(drills.get("available")) and all(
        it["result"] == "SUCCEEDED" and it["rto_seconds"] is not None and it["rto_seconds"] <= 300
        for it in drills_items
    )
    e2e_ok = bool(e2e.get("available")) and bool(
        e2e.get("closed_loop", {}).get("passed") and e2e.get("tenant_isolation", {}).get("passed")
    )
    denied = db.get("guard_denied", {})
    tr = db["traceability"]
    rc = db["recall"]
    cl = db["closure"]
    ac = db["audit_completeness"]
    e2e_cl = e2e.get("closed_loop", {})
    e2e_iso = e2e.get("tenant_isolation", {})
    return [
        {
            "key": "coverage",
            "name": "业务对象覆盖度",
            "threshold": "≥95%",
            "measured": f"{db['coverage']['overall_pct']}%",
            "passed": db["coverage"]["overall_pct"] >= 95.0,
            "note": "quality build_coverage（平台全量）",
        },
        {
            "key": "traceability",
            "name": "证据可追溯率（P0/P1）",
            "threshold": "=100%",
            "measured": f"{tr['pct']}%（{tr['traced']}/{tr['total']}）",
            "passed": tr["pct"] >= 100.0,
            "note": "证据→事件→对象链路存在性；E2E 脚本①内嵌断言另证",
        },
        {
            "key": "recall",
            "name": "重大风险召回率",
            "threshold": "≥80%（误报 ≤20%）",
            "measured": (
                f"召回 {rc['recall_pct']}%（{rc['matched']}/{rc['expected_major']}），"
                f"误报 {rc['false_positive_pct']}%"
                f"（{rc['false_positives']}/{rc['detected_major']}）"
            ),
            "passed": rc["recall_pct"] >= 80.0 and rc["false_positive_pct"] <= 20.0,
            "note": "十场景回放统计（放大实体排除）",
        },
        {
            "key": "closure",
            "name": "Action 闭环率",
            "threshold": "≥90%",
            "measured": f"{cl['pct']}%（{cl['verified']}/{cl['total']}）",
            "passed": cl["pct"] >= 90.0,
            "note": "action.actions status=VERIFIED 口径",
        },
        {
            "key": "guard_denied",
            "name": "AI 越权执行",
            "threshold": "=0",
            "measured": (
                f"越权成功 {denied.get('ai_human_only_success')}；"
                f"GUARD_DENIED 拦截 {denied.get('denied_count')} 条（全量导出）"
            ),
            "passed": denied.get("ai_human_only_success") == 0,
            "note": "越权矩阵用例集（test_security_matrix）CI 佐证",
        },
        {
            "key": "audit_completeness",
            "name": "Action 审计完整率",
            "threshold": "=100%",
            "measured": (
                f"{ac['pct']}%（action {ac['covered_actions']}/{ac['total_actions']}、"
                f"case {ac['covered_cases']}/{ac['total_cases']}、"
                f"record {ac['covered_records']}/{ac['total_records']}）"
            ),
            "passed": ac["pct"] >= 100.0,
            "note": "实体级审计行存在性对账",
        },
        {
            "key": "latency",
            "name": "接口响应（P95）",
            "threshold": "<2s",
            "measured": (
                f"max P95 {loadtest['max_p95_ms']}ms（{len(loadtest.get('entries', []))} 接口）"
                if loadtest.get("available") and loadtest.get("max_p95_ms") is not None
                else loadtest.get("reason", "无压测产物")
            ),
            "passed": latency_ok,
            "note": "locust 三档 VU 实测（deploy/loadtest/locust.json）",
        },
        {
            "key": "isolation",
            "name": "租户隔离",
            "threshold": "100% 拒绝",
            "measured": (
                f"E2E 闭环 {e2e_cl.get('rounds')} 轮 + 隔离 {e2e_iso.get('rounds')} 轮全绿"
                if e2e_ok
                else e2e.get("reason", "待补 e2e-result.json")
            ),
            "passed": e2e_ok,
            "note": "跨租户用例集 + E2E tenant-isolation.spec.ts",
        },
        {
            "key": "ha",
            "name": "高可用/备份恢复",
            "threshold": "RTO<5min；演练通过",
            "measured": "；".join(
                f"{it['drill_type']} RTO={it['rto_seconds']}s/{it['result']}" for it in drills_items
            )
            or drills.get("reason", "无演练记录"),
            "passed": ha_ok,
            "note": "W5 演练实测（drill-records.json）",
        },
    ]


def render_gonogo(report: dict[str, Any]) -> str:
    """Go/No-Go Markdown 指标表（docs/demo/w6-gonogo.md 产物）。"""
    lines = [
        "# W6 Go/No-Go 指标表（M6，EDP-034 一键导出）",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- 数据源：DB（BYPASSRLS 平台全量）、{report['sources']['loadtest']}、",
        f"  {report['sources']['drills']}、{report['sources']['e2e_result']}",
        f"- 结论：{'全指标达标' if report['all_passed'] else '存在未达标项（见下表）'}",
        "",
        "| 指标 | 门槛 | 实测 | 判定 | 依据 |",
        "|---|---|---|---|---|",
    ]
    for m in report["metrics"]:
        verdict = "达标" if m["passed"] else "未达标"
        lines.append(
            f"| {m['name']} | {m['threshold']} | {m['measured']} | {verdict} | {m['note']} |"
        )
    lines += [
        "",
        "> 一键复现：`make ops-report`（backend 环境 + 真栈 DB；"
        "口径见 `backend/scripts/ops_report.py` 模块 docstring）。",
        "> RLS 相对开销口径见 `docs/demo/w6-loadtest.md`"
        "（相对不达标/绝对无影响，门禁采绝对口径）。",
        "",
    ]
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser(description="W6 运营报告一键导出（EDP-034）")
    parser.add_argument("--db-url", default=os.environ.get("EDP_DATABASE_URL", DEFAULT_DB_URL))
    parser.add_argument("--loadtest", type=Path, default=DEFAULT_LOADTEST)
    parser.add_argument("--drills", type=Path, default=DEFAULT_DRILLS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--gonogo", type=Path, default=DEFAULT_GONOGO)
    parser.add_argument(
        "--e2e-result",
        type=Path,
        default=None,
        help="E2E 结果标记 JSON（缺省 <out-dir>/e2e-result.json）",
    )
    args = parser.parse_args()
    e2e_path = args.e2e_result or (args.out_dir / "e2e-result.json")

    db = await collect_db_metrics(args.db_url)
    loadtest = parse_loadtest(args.loadtest)
    drills = parse_drills(args.drills)
    e2e = parse_e2e_result(e2e_path)
    metrics = build_metrics(db, loadtest, drills, e2e)

    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sources": {
            "db": "platform（migrator/BYPASSRLS）",
            "loadtest": str(args.loadtest.relative_to(REPO_ROOT))
            if args.loadtest.is_absolute()
            else str(args.loadtest),
            "drills": str(args.drills.relative_to(REPO_ROOT))
            if args.drills.is_absolute()
            else str(args.drills),
            "e2e_result": str(e2e_path.relative_to(REPO_ROOT))
            if e2e_path.is_absolute()
            else str(e2e_path),
        },
        "metrics": metrics,
        "all_passed": all(m["passed"] for m in metrics),
        "details": {
            "coverage_by_type": db["coverage"]["by_type"],
            "recall": db["recall"],
            "traceability": db["traceability"],
            "closure": db["closure"],
            "audit_completeness": db["audit_completeness"],
            "guard_denied": db["guard_denied"],
            "loadtest_entries": loadtest.get("entries", []),
            "drills": drills.get("items", []),
            "e2e": e2e,
        },
    }

    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "w6-ops-report.json"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    args.gonogo.parent.mkdir(parents=True, exist_ok=True)
    args.gonogo.write_text(render_gonogo(report), encoding="utf-8", newline="\n")

    for m in metrics:
        print(f"[{'PASS' if m['passed'] else 'FAIL'}] {m['name']}: {m['measured']}")
    print(f"JSON: {json_path}")
    print(f"Go/No-Go: {args.gonogo}")
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
