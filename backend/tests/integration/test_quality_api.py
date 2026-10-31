"""T3 质量报告集成测试（EDP-030 上半）：四段形状与精确值 / checksum 篡改
落事件与幂等 / coverage 同形 / 鉴权矩阵（MANAGER/ANALYST 200、SERVICE
readonly Key 403、匿名 401）/ 抽样排序专项（>120 条 P0/P1 证据钉住
captured_at DESC 新证据优先，T4 评审 Minor）。

造数：demo_service.seed（make seed-demo 等价，确定性数据集）——快照
43 对象/事件、回流 10 风险事件（P0×1+P1×3+P2×3+P3×2、场景 10 P2）、
P0/P1 结果证据 4 条（场景 2/5/7/9）；断言经 migrator db_session 直查。

清场：demo_service.purge_tenant_business_data（逆依赖序 + usage/幂等键，
含 quality.checksum_failed 事件与 outbox）+ 本模块审计行（seed 适配器
actor 与 quality 事件写入）+ 临时 readonly Key。
"""

import json
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.core.security.apikey import hash_key
from edp_api.main import create_app
from edp_api.modules.audit.aspect import install_audit_aspect
from edp_api.modules.demo import service as demo_service
from edp_api.modules.evidence.service import compute_checksum
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

REPORTS = "/api/v1/admin/quality/reports"
COVERAGE = "/api/v1/admin/quality/coverage"
LOGIN = "/api/v1/auth/login"
SEED_PASSWORD = "Admin@123!"

READONLY_KEY = "t3-quality-readonly-key"
READONLY_PRINCIPAL = "t3-quality-readonly"


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS），quality
    路由随 create_app 装配。"""
    await core_db.dispose_engine()
    monkeypatch.setattr(core_db, "get_engine", lambda: app_role_engine)
    transport = httpx.ASGITransport(app=create_app())
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        await core_db.dispose_engine()  # 重置绑定到测试引擎的会话工厂


@pytest.fixture
async def default_tenant_id(db_session: AsyncSession) -> UUID:
    """default 租户 id（0005 种子；tenants 控制面表，migrator 直查）。"""
    return (
        await db_session.execute(
            text("SELECT tenant_id FROM platform.tenants WHERE slug = 'default'")
        )
    ).scalar_one()


@pytest.fixture(autouse=True)
def _install_aspect() -> None:
    """seed 的 ORM 写依赖切面落审计——与 CLI 同一装配。"""
    install_audit_aspect()


@pytest.fixture
async def seeded(
    app_role_engine: AsyncEngine, default_tenant_id: UUID
) -> None:
    """demo seed（make seed-demo 等价；确定性数据集）。"""
    await demo_service.seed(app_role_engine, default_tenant_id)


@pytest.fixture(autouse=True)
async def _clean_quality_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> AsyncIterator[None]:
    """每测试后清场：业务行（含 quality.checksum_failed 事件/outbox/usage/
    幂等键——purge 逆依赖序）+ seed 适配器与 quality 事件的审计行 +
    临时 readonly Key。"""
    yield
    await demo_service.purge_tenant_business_data(db_session, default_tenant_id)
    await db_session.execute(
        text(
            "DELETE FROM platform.audit_logs WHERE tenant_id = :t"
            " AND (actor_id LIKE 'adapter:%'"
            "       OR detail->>'event_type' = 'quality.checksum_failed')"
        ),
        {"t": default_tenant_id},
    )
    await db_session.execute(
        text("DELETE FROM platform.api_keys WHERE principal_id = :p"),
        {"p": READONLY_PRINCIPAL},
    )
    await db_session.commit()


async def _login(client: httpx.AsyncClient, username: str) -> dict[str, str]:
    resp = await client.post(
        LOGIN, json={"username": username, "password": SEED_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _insert_readonly_key(
    db_session: AsyncSession, tenant_id: UUID
) -> None:
    """直插仅 readonly scope 的 SERVICE Key（照 test_traces 模式）。"""
    await db_session.execute(
        text(
            """
            INSERT INTO platform.api_keys
                (key_id, key_hash, tenant_id, principal_type, principal_id,
                 scopes, status)
            VALUES (:key_id, :key_hash, :t, 'SERVICE', :principal,
                    CAST(:scopes AS text[]), 'ACTIVE')
            """
        ),
        {
            "key_id": uuid4(),
            "key_hash": hash_key(READONLY_KEY),
            "t": tenant_id,
            "principal": READONLY_PRINCIPAL,
            "scopes": ["readonly"],
        },
    )
    await db_session.commit()


async def _count(
    db_session: AsyncSession, tenant_id: UUID, sql: str, **params: object
) -> int:
    return (await db_session.execute(text(sql), {"t": tenant_id, **params})).scalar_one()


# ---- 1. 四段形状与精确值（seed 确定性数据集） ----


async def test_reports_segments_shape_and_exact_values(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    seeded: None,
) -> None:
    manager = await _login(client, "manager1")
    resp = await client.get(REPORTS, headers=manager)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # date 回显：缺省 = 请求日（ISO 日期 YYYY-MM-DD）
    assert len(body["date"]) == 10 and body["date"][4] == "-"

    # 对账段：组全集 = SNAPSHOT 期望组（seed 全量同步）；精确组值
    reconciliation = body["reconciliation"]
    assert reconciliation, "对账段至少一组"
    assert all(
        set(row) == {
            "source_system",
            "object_type",
            "source_count",
            "edp_count",
            "deviation_pct",
            "ok",
        }
        for row in reconciliation
    )
    by_group = {(row["source_system"], row["object_type"]): row for row in reconciliation}
    order_row = by_group[("erp", "ORDER")]
    assert order_row["source_count"] == 10  # SNAPSHOT 确定性基数
    assert order_row["edp_count"] == 10
    assert order_row["deviation_pct"] == 0.0
    assert order_row["ok"] is True
    assert by_group[("mes", "CAPACITY")]["source_count"] == 3
    assert all(row["ok"] for row in reconciliation)  # 全量同步 → 全 ok

    # 覆盖率段：seed 对象全部有 *_SNAPSHOT 事件 → 100.0
    coverage = body["coverage"]
    assert set(coverage) == {"overall_pct", "by_type"}
    assert coverage["overall_pct"] == 100.0
    assert coverage["by_type"], "by_type 至少一类"
    assert all(
        set(item) == {"object_type", "coverage_pct"}
        and item["coverage_pct"] == 100.0
        for item in coverage["by_type"]
    )
    assert {item["object_type"] for item in coverage["by_type"]} >= {
        "ORDER",
        "CUSTOMER",
        "MATERIAL",
        "PRODUCT",
        "PURCHASE_ORDER",
        "PROJECT",
    }

    # 孤儿段：seed 干净数据 → 两零
    assert body["orphans"] == {"event_orphans": 0, "evidence_orphans": 0}

    # 抽检段：P0/P1 结果证据 4 条（场景 2/5/7/9）全通过
    assert body["checksum_sampling"] == {"sampled": 4, "failed": 0}

    # kpi：形状对齐 mocks/types.ts；seed 口径 pending=10（全 OPEN）、high=4
    assert set(body["kpi"]) == {
        "overall_pct",
        "sla_pct",
        "completeness_pct",
        "pending_exceptions",
        "high_priority",
    }
    assert body["kpi"]["pending_exceptions"] == 10
    assert body["kpi"]["high_priority"] == 4
    assert body["kpi"]["overall_pct"] == 100.0
    assert body["kpi"]["sla_pct"] == 100.0
    assert body["kpi"]["completeness_pct"] == 100.0

    # dimensions：四条（四段各一），形状 {domain,label,score_pct}
    dimensions = body["dimensions"]
    assert {item["domain"] for item in dimensions} == {
        "reconciliation",
        "coverage",
        "orphans",
        "checksum",
    }
    assert all(
        set(item) == {"domain", "label", "score_pct"} and item["score_pct"] == 100.0
        for item in dimensions
    )

    # 干净数据不落 quality.checksum_failed（仅失配行落数直证）
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM event.events"
            " WHERE tenant_id = :t AND event_type = 'quality.checksum_failed'",
        )
        == 0
    )


async def test_reports_date_param_echoed_without_backtrack(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    seeded: None,
) -> None:
    """date 接受并回显；计算恒实时（回显旧日期仍返回当前数据）。"""
    manager = await _login(client, "manager1")
    resp = await client.get(REPORTS, params={"date": "2026-09-01"}, headers=manager)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["date"] == "2026-09-01"
    assert body["reconciliation"], "回显历史日期仍按实时计算（不回溯）"
    assert body["checksum_sampling"]["sampled"] == 4


# ---- 2. checksum 篡改：failed ≥1 + quality.checksum_failed 事件 + 幂等 ----


async def test_checksum_tampering_writes_failure_event_idempotently(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    seeded: None,
) -> None:
    # 篡改 P0 结果证据（场景 7）的 snapshot：重算 checksum 必失配
    tampered = await db_session.execute(
        text(
            """
            UPDATE evidence.records r
            SET snapshot = r.snapshot || '{"tampered": true}'::jsonb
            WHERE r.tenant_id = :t AND r.evidence_id IN (
                SELECT l.evidence_id FROM evidence.links l
                JOIN event.events e ON e.event_id = l.ref_id
                 AND e.risk_level = 'P0' AND e.tenant_id = :t
                WHERE l.ref_type = 'RESULT' AND l.tenant_id = :t)
            RETURNING r.evidence_id::text
            """
        ),
        {"t": default_tenant_id},
    )
    tampered_ids = [row[0] for row in tampered.all()]
    assert len(tampered_ids) == 1
    await db_session.commit()

    manager = await _login(client, "manager1")
    first = await client.get(REPORTS, headers=manager)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["checksum_sampling"]["sampled"] == 4
    assert body["checksum_sampling"]["failed"] >= 1
    # checksum 维度线性扣减（1/4 → 75.0）与 kpi 联动
    checksum_dim = next(
        item for item in body["dimensions"] if item["domain"] == "checksum"
    )
    assert checksum_dim["score_pct"] == 75.0
    assert body["kpi"]["sla_pct"] == 75.0

    # 失配行落数：事件存在、risk_level 空、data 携带证据 id 与两侧 checksum
    event_row = (
        await db_session.execute(
            text(
                "SELECT risk_level, data FROM event.events"
                " WHERE tenant_id = :t AND event_type = 'quality.checksum_failed'"
            ),
            {"t": default_tenant_id},
        )
    ).one()
    assert event_row.risk_level is None
    assert event_row.data["evidence_id"] == tampered_ids[0]
    assert event_row.data["expected"] != event_row.data["actual"]

    # 重复抽检不重复落数（幂等键归档 + UUIDv5 双保险）
    second = await client.get(REPORTS, headers=manager)
    assert second.status_code == 200, second.text
    assert second.json()["checksum_sampling"]["failed"] >= 1
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM event.events"
            " WHERE tenant_id = :t AND event_type = 'quality.checksum_failed'",
        )
        == 1
    )


# ---- 3. coverage 端点：reports.coverage 同形 ----


async def test_coverage_endpoint_same_shape_as_reports(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    seeded: None,
) -> None:
    manager = await _login(client, "manager1")
    coverage = await client.get(COVERAGE, headers=manager)
    reports = await client.get(REPORTS, headers=manager)
    assert coverage.status_code == 200, coverage.text
    assert reports.status_code == 200, reports.text
    assert set(coverage.json()) == {"overall_pct", "by_type"}
    assert coverage.json()["overall_pct"] == reports.json()["coverage"]["overall_pct"]
    assert coverage.json()["by_type"] == reports.json()["coverage"]["by_type"]


# ---- 4. 鉴权矩阵：MANAGER/ANALYST 200；SERVICE readonly Key 403；匿名 401 ----


async def test_auth_matrix(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    manager = await _login(client, "manager1")
    analyst = await _login(client, "analyst1")
    assert (await client.get(REPORTS, headers=manager)).status_code == 200
    assert (await client.get(REPORTS, headers=analyst)).status_code == 200
    assert (await client.get(COVERAGE, headers=analyst)).status_code == 200

    # SERVICE readonly Key：quality 无 scope 轨道 → 403 FORBIDDEN
    await _insert_readonly_key(db_session, default_tenant_id)
    denied = await client.get(REPORTS, headers={"X-API-Key": READONLY_KEY})
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "FORBIDDEN"
    denied_coverage = await client.get(COVERAGE, headers={"X-API-Key": READONLY_KEY})
    assert denied_coverage.status_code == 403

    # 匿名 → 401
    assert (await client.get(REPORTS)).status_code == 401


# ---- 5. 抽样排序专项（T4 评审 Minor）：captured_at DESC 新证据优先 ----


_INSERT_SORT_EVIDENCE_SQL = text("""
    INSERT INTO evidence.records
        (evidence_id, tenant_id, source_system, source_record_id,
         object_id, event_id, checksum, snapshot, captured_at,
         created_by, updated_by)
    VALUES (:evidence_id, :t, 'edp-quality-test', :source_record_id,
            :object_id, :event_id, :checksum, CAST(:snapshot AS jsonb),
            :captured_at, 'test:sampling-sort', 'test:sampling-sort')
""")

_P0P1_POOL_MAX_SQL = text("""
    SELECT max(r.captured_at) FROM evidence.records r
    WHERE r.tenant_id = :t
      AND (r.event_id IN (SELECT e.event_id FROM event.events e
                           WHERE e.tenant_id = :t
                             AND e.risk_level IN ('P0', 'P1'))
           OR r.evidence_id IN (
               SELECT l.evidence_id FROM evidence.links l
               JOIN event.events e ON e.event_id = l.ref_id
                AND e.tenant_id = :t AND e.risk_level IN ('P0', 'P1')
               WHERE l.ref_type = 'RESULT' AND l.tenant_id = :t))
""")


async def test_checksum_sampling_prefers_newest_evidence_beyond_limit(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    seeded: None,
) -> None:
    """合成 130 条 P0 结果证据（captured_at 严格递增、全部早于 seed 证据）
    + 仅篡改最旧 10 条——池 4+130=134 > 上限 120。降序抽样取最新 120
    （seed 4 + 合成最新 116+……即合成 i=14..129 与 seed 4 条），最旧
    篡改行被挤出样本：sampled=120、failed=0、不落 checksum_failed 事件；
    若退化为升序（最旧恒占满限额）则篡改行入样 failed=10——钉住
    captured_at DESC「新证据优先入样」性质（防抽样面被最旧证据冻结）。"""
    base: datetime = (
        await db_session.execute(_P0P1_POOL_MAX_SQL, {"t": default_tenant_id})
    ).scalar_one()
    assert base is not None, "seed P0/P1 证据就位"
    p0 = (
        await db_session.execute(
            text(
                "SELECT e.event_id, e.object_id FROM event.events e"
                " WHERE e.tenant_id = :t AND e.risk_level = 'P0' LIMIT 1"
            ),
            {"t": default_tenant_id},
        )
    ).one()

    synthetic_n = 130
    # i=0 最旧（base-2000min）→ i=129 最新（base-710min），全严格早于 base
    params = [
        {
            "evidence_id": uuid4(),
            "t": default_tenant_id,
            "source_record_id": f"sampling-sort:{i}",
            "object_id": p0.object_id,
            "event_id": p0.event_id,
            "checksum": compute_checksum({"seq": i}),
            "snapshot": json.dumps({"seq": i}),
            "captured_at": base - timedelta(minutes=2000 - i * 10),
        }
        for i in range(synthetic_n)
    ]
    await db_session.execute(_INSERT_SORT_EVIDENCE_SQL, params)
    # 篡改最旧 10 条（i=0..9：captured_at <= base-1910min）——snapshot 与
    # 落库 checksum 失配，若入样必 failed+1 并落数
    await db_session.execute(
        text(
            "UPDATE evidence.records r"
            " SET snapshot = r.snapshot || jsonb_build_object('tampered', true)"
            " WHERE r.tenant_id = :t AND r.created_by = 'test:sampling-sort'"
            "   AND r.captured_at <= :boundary"
        ),
        {"t": default_tenant_id, "boundary": base - timedelta(minutes=1910)},
    )
    await db_session.commit()

    manager = await _login(client, "manager1")
    resp = await client.get(REPORTS, headers=manager)
    assert resp.status_code == 200, resp.text
    # 池 134 > 120：降序取最新 120，最旧 10 条（含全部篡改行）被挤出
    assert resp.json()["checksum_sampling"] == {"sampled": 120, "failed": 0}
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM event.events"
            " WHERE tenant_id = :t AND event_type = 'quality.checksum_failed'",
        )
        == 0
    )
