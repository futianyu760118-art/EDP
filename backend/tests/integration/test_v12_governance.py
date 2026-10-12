"""V1.2 治理最小闭环集成测试（T08~T16）：RAW 留存 / 清洗 / 准入全链 / 门禁。

覆盖：
1. seed 后 RAW 留存与准入推进：raw_records 与 SNAPSHOT 事件等量、
   admission 全部 CLASSIFIED、governance.admission.* 事件存在；
2. replay 幂等：raw_records 行数不增（ON CONFLICT 唯一键）；
3. 清洗规则经管道生效：MAPPING 规则 auto_fix → 对象属性清洗 + clean_records
   留痕，而 evidence 快照保留原始 payload（证据=源快照）；
4. A2/A3/A4 全链：CLASSIFIED → source-review APPROVED → SOURCE_APPROVED →
   management-review APPROVED → OFFICIAL → archive → ARCHIVED（归档要素
   回填 + review_records 留痕 + ADMISSION_REVIEW 审计 + 状态事件）；
5. T16 门禁：BLOCK 规则 → 机器 FAIL → 400 + DataQuality.Exception 事件，
   状态停在 CLASSIFIED；非法状态推进 409；
6. Human-Only 与权限矩阵：SERVICE 403 / analyst1 无 admission:review 403 /
   analyst1 无 governance:manage 写 403 读 200；
7. 实体解析：别名 → canonical 名称替换（引擎级）；分类/维度/标签 CRUD。

会话形态：应用引擎 = conftest.app_role_engine（edp_app，FORCE RLS）；断言以
migrator db_session 直查。清场：demo_service.purge_tenant_business_data
（0014 起含 governance 段）+ 本模块审计行。
"""

import asyncio
from uuid import UUID

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.core.db import bind_tenant
from edp_api.main import create_app
from edp_api.modules.demo import service as demo_service
from edp_api.modules.governance import cleaning
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

BASE = "/api/v1"
LOGIN = "/api/v1/auth/login"
SEED_PASSWORD = "Admin@123!"

MAPPING_RULE = {
    "rule_name": "订单状态码映射",
    "object_type": "ORDER",
    "field": "status",
    "rule_type": "MAPPING",
    "transformation": {"map": {"已确认": "CONFIRMED"}},
    "severity": "WARN",
    "owner": "SALES",
    "auto_fix": True,
    "review_required": False,
}

BLOCK_RULE = {
    "rule_name": "订单金额上界",
    "object_type": "ORDER",
    "field": "amount",
    "rule_type": "RANGE_CHECK",
    "transformation": {"min": 1000000000},
    "severity": "BLOCK",
    "owner": "SALES",
    "auto_fix": False,
    "review_required": True,
}


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    await core_db.dispose_engine()
    monkeypatch.setattr(core_db, "get_engine", lambda: app_role_engine)
    transport = httpx.ASGITransport(app=create_app())
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        await core_db.dispose_engine()


@pytest.fixture
async def default_tenant_id(db_session: AsyncSession) -> UUID:
    return (
        await db_session.execute(
            text("SELECT tenant_id FROM platform.tenants WHERE slug = 'default'")
        )
    ).scalar_one()


@pytest.fixture(autouse=True)
async def _clean_governance_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    """每测试后清场：seed 业务数据（purge 含 governance 段）+ governance 审计行。"""
    yield
    await demo_service.purge_tenant_business_data(db_session, default_tenant_id)
    await db_session.execute(
        text(
            "DELETE FROM platform.audit_logs WHERE tenant_id = :t"
            " AND resource_type IN ('governance.admission_records',"
            " 'governance.cleaning_rules', 'governance.entity_aliases',"
            " 'governance.dimensions', 'governance.taxonomies',"
            " 'governance.tags', 'governance.object_classifications',"
            " 'governance.raw_records', 'governance.clean_records')"
        ),
        {"t": default_tenant_id},
    )
    await db_session.commit()


async def _login(client: httpx.AsyncClient, username: str) -> dict[str, str]:
    resp = await client.post(
        LOGIN, json={"username": username, "password": SEED_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed(app_role_engine: AsyncEngine, tenant_id: UUID) -> None:
    await demo_service.seed(app_role_engine, tenant_id)


async def _count(
    db_session: AsyncSession, sql: str, tid: UUID, extra: dict | None = None
) -> int:
    return (
        await db_session.execute(text(sql), {"t": tid, **(extra or {})})
    ).scalar_one()


async def _admission_of(
    db_session: AsyncSession, tid: UUID, source_id: str
) -> tuple[UUID, str]:
    row = (
        await db_session.execute(
            text(
                "SELECT a.admission_id, a.state FROM governance.admission_records a"
                " JOIN master.business_objects bo ON bo.object_id = a.object_id"
                " WHERE a.tenant_id = :t AND bo.source_id = :s"
            ),
            {"t": tid, "s": source_id},
        )
    ).one()
    return row.admission_id, row.state


# ---- 1. seed → RAW 留存 + 准入推进 CLASSIFIED ----


async def test_seed_creates_raw_and_admission_classified(
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await _seed(app_role_engine, default_tenant_id)

    raw_count = await _count(
        db_session,
        "SELECT count(*) FROM governance.raw_records WHERE tenant_id = :t",
        default_tenant_id,
    )
    snapshot_events = await _count(
        db_session,
        "SELECT count(*) FROM event.events WHERE tenant_id = :t"
        " AND event_type LIKE '%_SNAPSHOT'",
        default_tenant_id,
    )
    assert raw_count == snapshot_events > 0

    total = await _count(
        db_session,
        "SELECT count(*) FROM governance.admission_records WHERE tenant_id = :t",
        default_tenant_id,
    )
    classified = await _count(
        db_session,
        "SELECT count(*) FROM governance.admission_records WHERE tenant_id = :t"
        " AND state = 'CLASSIFIED'",
        default_tenant_id,
    )
    assert total == classified > 0

    # 同步管线段不发状态事件（防污染 SNAPSHOT 事件计数基线）——记录级审计
    # 由切面留痕（admission 行 ORM 写入）；事件自人工审核段产生
    assert (
        await _count(
            db_session,
            "SELECT count(*) FROM event.events WHERE tenant_id = :t"
            " AND event_type LIKE 'governance.admission.%'",
            default_tenant_id,
        )
        == 0
    )
    assert (
        await _count(
            db_session,
            "SELECT count(*) FROM platform.audit_logs WHERE tenant_id = :t"
            " AND resource_type IN ('governance.admission_records', 'admission_records')",
            default_tenant_id,
        )
        > 0
    )


# ---- 2. replay：RAW 幂等 ----


async def test_replay_raw_rows_not_duplicated(
    client: httpx.AsyncClient,
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await _seed(app_role_engine, default_tenant_id)
    before = await _count(
        db_session,
        "SELECT count(*) FROM governance.raw_records WHERE tenant_id = :t",
        default_tenant_id,
    )
    headers = await _login(client, "manager1")
    resp = await client.post(
        f"{BASE}/admin/adapters/erp-demo/sync",
        headers=headers,
        json={"mode": "replay"},
    )
    assert resp.status_code == 202, resp.text
    for _ in range(50):
        status = await client.get(
            f"{BASE}/admin/adapters/erp-demo/status", headers=headers
        )
        last_sync = status.json()["last_sync"]
        if last_sync and last_sync["status"] != "RUNNING":
            break
        await asyncio.sleep(0.1)
    assert last_sync["status"] == "SUCCEEDED", last_sync

    after = await _count(
        db_session,
        "SELECT count(*) FROM governance.raw_records WHERE tenant_id = :t",
        default_tenant_id,
    )
    assert after == before


# ---- 3. 清洗规则经管道生效 + clean_records 留痕，证据保原 payload ----


async def test_cleaning_rule_applied_in_pipeline(
    client: httpx.AsyncClient,
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    headers = await _login(client, "admin")
    resp = await client.post(
        f"{BASE}/governance/cleaning-rules", headers=headers, json=MAPPING_RULE
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["version"] == 1

    await _seed(app_role_engine, default_tenant_id)

    # 对象属性已清洗（attributes.status = CONFIRMED）
    converted = await _count(
        db_session,
        "SELECT count(*) FROM master.business_objects WHERE tenant_id = :t"
        " AND object_type = 'ORDER' AND attributes->>'status' = 'CONFIRMED'",
        default_tenant_id,
    )
    assert converted > 0
    # 证据快照保留原始值（已确认）
    evidence_original = await _count(
        db_session,
        "SELECT count(*) FROM evidence.records r"
        " JOIN master.business_objects bo ON bo.object_id = r.object_id"
        " WHERE r.tenant_id = :t AND bo.object_type = 'ORDER'"
        " AND r.snapshot->>'status' = '已确认'",
        default_tenant_id,
    )
    assert evidence_original > 0
    # clean_records 留痕（fixAudit：rule_refs 含规则 id）
    clean_count = await _count(
        db_session,
        "SELECT count(*) FROM governance.clean_records WHERE tenant_id = :t",
        default_tenant_id,
    )
    assert clean_count > 0


# ---- 4. A2/A3/A4 全链：CLASSIFIED → ARCHIVED ----


async def test_admission_full_chain_to_archived(
    client: httpx.AsyncClient,
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await _seed(app_role_engine, default_tenant_id)
    admission_id, state = await _admission_of(
        db_session, default_tenant_id, "SO-2026-00131"
    )
    assert state == "CLASSIFIED"
    headers = await _login(client, "admin")

    # A2
    resp = await client.post(
        f"{BASE}/governance/admission/{admission_id}/source-review",
        headers=headers,
        json={"decision": "APPROVED", "comment": "数据符合业务实际"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "SOURCE_APPROVED"

    # A3 → OFFICIAL
    resp = await client.post(
        f"{BASE}/governance/admission/{admission_id}/management-review",
        headers=headers,
        json={"decision": "APPROVED", "comment": "复核通过"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "OFFICIAL"

    # A4
    resp = await client.post(
        f"{BASE}/governance/admission/{admission_id}/archive", headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "ARCHIVED"

    # 留痕：review_records 两条 + 归档要素 + 审计 + 状态事件
    reviews = await _count(
        db_session,
        "SELECT count(*) FROM governance.review_records WHERE tenant_id = :t"
        " AND admission_id = :a",
        default_tenant_id,
        {"a": admission_id},
    )
    archived_checksum = (
        await db_session.execute(
            text(
                "SELECT checksum IS NOT NULL, archived_at IS NOT NULL"
                " FROM governance.admission_records WHERE admission_id = :a"
            ),
            {"a": admission_id},
        )
    ).one()
    assert reviews == 2
    assert all(archived_checksum)
    assert (
        await _count(
            db_session,
            "SELECT count(*) FROM platform.audit_logs WHERE tenant_id = :t"
            " AND action = 'ADMISSION_REVIEW'",
            default_tenant_id,
        )
        >= 2
    )
    assert (
        await _count(
            db_session,
            "SELECT count(*) FROM event.events WHERE tenant_id = :t"
            " AND event_type IN ('governance.admission.SOURCE_APPROVED',"
            " 'governance.admission.MANAGEMENT_APPROVED',"
            " 'governance.admission.OFFICIAL', 'governance.admission.ARCHIVED')",
            default_tenant_id,
        )
        == 4
    )


# ---- 5. T16 门禁：BLOCK 规则 → 机器 FAIL 阻断 + DataQuality.Exception ----


async def test_source_review_fail_gate_blocks_and_records_dq(
    client: httpx.AsyncClient,
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    headers = await _login(client, "admin")
    resp = await client.post(
        f"{BASE}/governance/cleaning-rules", headers=headers, json=BLOCK_RULE
    )
    assert resp.status_code == 201, resp.text
    await _seed(app_role_engine, default_tenant_id)
    admission_id, _ = await _admission_of(db_session, default_tenant_id, "SO-2026-00131")

    resp = await client.post(
        f"{BASE}/governance/admission/{admission_id}/source-review",
        headers=headers,
        json={"decision": "APPROVED"},
    )
    assert resp.status_code == 400, resp.text
    assert "DataQuality.Exception" in resp.text

    # 状态未推进
    row = (
        await db_session.execute(
            text(
                "SELECT state FROM governance.admission_records WHERE admission_id = :a"
            ),
            {"a": admission_id},
        )
    ).one()
    assert row.state == "CLASSIFIED"
    # 异常事件落库
    assert (
        await _count(
            db_session,
            "SELECT count(*) FROM event.events WHERE tenant_id = :t"
            " AND event_type = 'DataQuality.Exception'",
            default_tenant_id,
        )
        == 1
    )


# ---- 6. Human-Only 与权限矩阵 ----


async def test_admission_human_only_and_permissions(
    client: httpx.AsyncClient,
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await _seed(app_role_engine, default_tenant_id)
    admission_id, _ = await _admission_of(db_session, default_tenant_id, "SO-2026-00122")
    analyst = await _login(client, "analyst1")
    manager = await _login(client, "manager1")

    # SERVICE（dev Key）审核 → 403（Human-Only 依赖层）
    resp = await client.post(
        f"{BASE}/governance/admission/{admission_id}/source-review",
        headers={"X-API-Key": "edp-dev-agent-hub-key"},
        json={"decision": "APPROVED"},
    )
    assert resp.status_code == 403

    # analyst1 无 admission:review → 403；manager1 有 → 200（机器 WARNING 允许推进）
    resp = await client.post(
        f"{BASE}/governance/admission/{admission_id}/source-review",
        headers=analyst,
        json={"decision": "APPROVED"},
    )
    assert resp.status_code == 403
    resp = await client.post(
        f"{BASE}/governance/admission/{admission_id}/source-review",
        headers=manager,
        json={"decision": "APPROVED"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "SOURCE_APPROVED"

    # 写面：analyst1 无 governance:manage → 403；读面 200
    resp = await client.post(
        f"{BASE}/governance/cleaning-rules", headers=analyst, json=MAPPING_RULE
    )
    assert resp.status_code == 403
    resp = await client.get(f"{BASE}/governance/cleaning-rules", headers=analyst)
    assert resp.status_code == 200

    # 非法状态推进：SOURCE_APPROVED 再 source-review → 409
    resp = await client.post(
        f"{BASE}/governance/admission/{admission_id}/source-review",
        headers=manager,
        json={"decision": "APPROVED"},
    )
    assert resp.status_code == 409


# ---- 7. 实体解析 + 分类/维度/标签 ----


async def test_entity_resolution_and_classification(
    client: httpx.AsyncClient,
    app_role_engine: AsyncEngine,
    app_session: AsyncSession,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    headers = await _login(client, "admin")
    await _seed(app_role_engine, default_tenant_id)

    canonical = (
        await db_session.execute(
            text(
                "SELECT object_id FROM master.business_objects WHERE tenant_id = :t"
                " AND object_type = 'CUSTOMER' AND source_id = 'C-030'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one()

    resp = await client.post(
        f"{BASE}/governance/entity-aliases",
        headers=headers,
        json={
            "object_type": "CUSTOMER",
            "alias": "恒剑光电",
            "canonical_ref": str(canonical),
            "source": "HUMAN_MAINTAINED",
        },
    )
    assert resp.status_code == 201, resp.text

    resp = await client.post(
        f"{BASE}/governance/cleaning-rules",
        headers=headers,
        json={
            "rule_name": "客户别名归一",
            "object_type": "CUSTOMER",
            "field": "name",
            "rule_type": "ENTITY_RESOLUTION",
            "transformation": {"object_type": "CUSTOMER", "value_field": "name"},
            "severity": "WARN",
            "owner": "SALES",
            "auto_fix": True,
            "review_required": True,
        },
    )
    assert resp.status_code == 201, resp.text

    await bind_tenant(app_session, default_tenant_id)
    result = await cleaning.apply_cleaning(
        app_session,
        default_tenant_id,
        "CUSTOMER",
        {"name": "恒剑光电", "owner_domain": "master"},
    )
    await app_session.commit()
    assert result.cleaned["name"] == "宏达精密"  # canonical 名称替换
    assert any("恒剑光电" in str(f.before_value) for f in result.fixes)

    # 分类/维度/标签 CRUD
    resp = await client.post(
        f"{BASE}/governance/dimensions",
        headers=headers,
        json={"code": "ORDER", "name": "订单维度"},
    )
    assert resp.status_code == 201, resp.text
    dimension_id = resp.json()["dimension_id"]
    resp = await client.post(
        f"{BASE}/governance/tags",
        headers=headers,
        json={"code": "high-risk", "name": "高风险"},
    )
    assert resp.status_code == 201, resp.text
    object_id = (
        await db_session.execute(
            text(
                "SELECT object_id FROM master.business_objects WHERE tenant_id = :t"
                " AND source_id = 'SO-2026-00131'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one()
    resp = await client.post(
        f"{BASE}/governance/object-classifications",
        headers=headers,
        json={
            "object_id": str(object_id),
            "dimension_id": dimension_id,
            "label": "高风险",
            "source": "HUMAN_MAINTAINED",
        },
    )
    assert resp.status_code == 201, resp.text
    resp = await client.get(
        f"{BASE}/governance/classifications", headers=headers, params={"object_id": str(object_id)}
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["label"] == "高风险"
