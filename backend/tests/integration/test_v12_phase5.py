"""V1.2 Phase 5 集成测试（T30/T32/T33/T34）：CSV 导入 / 自动预审 / 多维查询。

覆盖：
1. CSV 导入：缺必需列 400 / 正常导入（RAW + 管道全链 + admission
   CLASSIFIED）/ 重导幂等 duplicated；
2. object-tags 挂接 + search-objects（tag/classification/dimension/
   official_only 过滤组合）；
3. auto_source_machine_review：无规则 WARNING → 推进 SOURCE_REVIEW；
   BLOCK 规则 FAIL → 留 CLASSIFIED + DataQuality.Exception；
4. worker 预审后 source_review 从 SOURCE_REVIEW 起态可审（T32 兼容）。

会话形态：应用引擎 = conftest.app_role_engine（edp_app，FORCE RLS）；断言
以 migrator db_session 直查。清场：purge（0017 起含 object_tags）。
"""

from uuid import UUID

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.core.db import bind_tenant
from edp_api.main import create_app
from edp_api.modules.demo import service as demo_service
from edp_api.modules.governance import service as governance_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

BASE = "/api/v1"
DEV_HEADERS = {"X-API-Key": "edp-dev-agent-hub-key"}
LOGIN = "/api/v1/auth/login"
SEED_PASSWORD = "Admin@123!"

CSV_CONTENT = (
    "object_type,source_id,occurred_at,name,unit,total_available,reserved\r\n"
    "MATERIAL,M-IMP-001,2026-09-20T08:00:00Z,导入物料A,件,100,10\r\n"
    "MATERIAL,M-IMP-002,2026-09-21T08:00:00Z,导入物料B,件,200,0\r\n"
)


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
async def _clean_phase5_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    yield
    await demo_service.purge_tenant_business_data(db_session, default_tenant_id)
    await db_session.execute(
        text(
            "DELETE FROM platform.audit_logs WHERE tenant_id = :t"
            " AND resource_type IN ('governance.object_tags', 'business_objects')"
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


# ---- 1. CSV 导入 ----


async def test_csv_import_full_chain_and_idempotent(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    headers = await _login(client, "admin")

    # 缺必需列 → 400
    resp = await client.post(
        f"{BASE}/admin/ingest/file",
        headers={**headers, "content-type": "text/csv"},
        content="object_type,source_id\r\nX,Y\r\n",
    )
    assert resp.status_code == 400, resp.text
    assert "occurred_at" in resp.text

    # 正常导入：2 行 → RAW + 管道全链
    resp = await client.post(
        f"{BASE}/admin/ingest/file",
        headers={**headers, "content-type": "text/csv"},
        content=CSV_CONTENT,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["received"] == 2
    assert body["registered"] == 2
    assert body["failed"] == 0

    assert (
        await db_session.execute(
            text(
                "SELECT count(*) FROM governance.raw_records WHERE tenant_id = :t"
                " AND source_system = 'file-import'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one() == 2
    # 数值推断：total_available 为数值（投影 NUMERIC 兼容）
    assert (
        await db_session.execute(
            text(
                "SELECT count(*) FROM master.business_objects WHERE tenant_id = :t"
                " AND object_type = 'MATERIAL' AND source_id = 'M-IMP-001'"
                " AND attributes->>'total_available' = '100'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one() == 1
    # admission 至 CLASSIFIED
    assert (
        await db_session.execute(
            text(
                "SELECT count(*) FROM governance.admission_records a"
                " JOIN master.business_objects bo ON bo.object_id = a.object_id"
                " WHERE a.tenant_id = :t AND bo.source_id LIKE 'M-IMP-%'"
                " AND a.state = 'CLASSIFIED'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one() == 2

    # 重导幂等：RAW 不增、duplicated=2
    resp = await client.post(
        f"{BASE}/admin/ingest/file",
        headers={**headers, "content-type": "text/csv"},
        content=CSV_CONTENT,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["registered"] == 0
    assert body["duplicated"] == 2
    assert (
        await db_session.execute(
            text(
                "SELECT count(*) FROM governance.raw_records WHERE tenant_id = :t"
                " AND source_system = 'file-import'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one() == 2


# ---- 2. object-tags + search-objects ----


async def test_object_tags_and_search_objects(
    client: httpx.AsyncClient,
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await demo_service.seed(app_role_engine, default_tenant_id)
    headers = await _login(client, "admin")

    # 标签 + 维度 + 分类
    tag_resp = await client.post(
        f"{BASE}/governance/tags",
        headers=headers,
        json={"code": "high-risk", "name": "高风险"},
    )
    assert tag_resp.status_code == 201, tag_resp.text
    tag_id = tag_resp.json()["tag_id"]
    dim_resp = await client.post(
        f"{BASE}/governance/dimensions",
        headers=headers,
        json={"code": "ORDER", "name": "订单维度"},
    )
    dimension_id = dim_resp.json()["dimension_id"]

    order_id = (
        await db_session.execute(
            text(
                "SELECT object_id FROM master.business_objects WHERE tenant_id = :t"
                " AND source_id = 'SO-2026-00131'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one()
    resp = await client.post(
        f"{BASE}/governance/object-tags",
        headers=headers,
        json={"object_id": str(order_id), "tag_id": tag_id},
    )
    assert resp.status_code == 201, resp.text
    resp = await client.post(
        f"{BASE}/governance/object-classifications",
        headers=headers,
        json={
            "object_id": str(order_id),
            "dimension_id": dimension_id,
            "label": "高风险",
            "source": "HUMAN_MAINTAINED",
        },
    )
    assert resp.status_code == 201, resp.text

    # search-objects（非 OFFICIAL → 默认空；false 命中；各过滤组合）
    searched = await client.get(
        f"{BASE}/tools/search-objects",
        headers=DEV_HEADERS,
        params={"tag": "high-risk"},
    )
    assert searched.status_code == 200
    assert searched.json()["items"] == []

    searched = await client.get(
        f"{BASE}/tools/search-objects",
        headers=DEV_HEADERS,
        params={"tag": "high-risk", "official_only": "false"},
    )
    assert searched.status_code == 200
    items = searched.json()["items"]
    assert [item["source_id"] for item in items] == ["SO-2026-00131"]

    searched = await client.get(
        f"{BASE}/tools/search-objects",
        headers=DEV_HEADERS,
        params={"classification": "高风险", "official_only": "false"},
    )
    assert [item["source_id"] for item in searched.json()["items"]] == ["SO-2026-00131"]

    searched = await client.get(
        f"{BASE}/tools/search-objects",
        headers=DEV_HEADERS,
        params={"dimension": "ORDER", "object_type": "ORDER", "official_only": "false"},
    )
    assert [item["source_id"] for item in searched.json()["items"]] == ["SO-2026-00131"]


# ---- 3. 自动预审（T32） ----


async def test_auto_source_machine_review(
    app_role_engine: AsyncEngine,
    app_session: AsyncSession,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await demo_service.seed(app_role_engine, default_tenant_id)

    await bind_tenant(app_session, default_tenant_id)
    stats = await governance_service.auto_source_machine_review(
        app_session, default_tenant_id
    )
    await app_session.commit()
    # 无规则：分类缺失 WARN → verdict WARNING → 全量推进 SOURCE_REVIEW
    assert stats["advanced"] > 0
    assert stats["blocked"] == 0
    assert (
        await db_session.execute(
            text(
                "SELECT count(*) FROM governance.admission_records WHERE tenant_id = :t"
                " AND state = 'SOURCE_REVIEW'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one() == stats["advanced"]


async def test_auto_review_fail_gate_keeps_classified(
    client: httpx.AsyncClient,
    app_role_engine: AsyncEngine,
    app_session: AsyncSession,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    headers = await _login(client, "admin")
    resp = await client.post(
        f"{BASE}/governance/cleaning-rules",
        headers=headers,
        json={
            "rule_name": "订单金额上界",
            "object_type": "ORDER",
            "field": "amount",
            "rule_type": "RANGE_CHECK",
            "transformation": {"min": 1000000000},
            "severity": "BLOCK",
            "owner": "SALES",
            "auto_fix": False,
            "review_required": True,
        },
    )
    assert resp.status_code == 201, resp.text
    await demo_service.seed(app_role_engine, default_tenant_id)

    await bind_tenant(app_session, default_tenant_id)
    stats = await governance_service.auto_source_machine_review(
        app_session, default_tenant_id
    )
    await app_session.commit()
    assert stats["blocked"] > 0
    assert (
        await db_session.execute(
            text(
                "SELECT count(*) FROM governance.admission_records a"
                " JOIN master.business_objects bo ON bo.object_id = a.object_id"
                " WHERE a.tenant_id = :t AND bo.object_type = 'ORDER'"
                " AND a.state = 'CLASSIFIED'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one() == stats["blocked"]
    assert (
        await db_session.execute(
            text(
                "SELECT count(*) FROM event.events WHERE tenant_id = :t"
                " AND event_type = 'DataQuality.Exception'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one() == stats["blocked"]


# ---- 4. worker 预审后人工审核（SOURCE_REVIEW 起态） ----


async def test_source_review_from_worker_preadvanced_state(
    client: httpx.AsyncClient,
    app_role_engine: AsyncEngine,
    app_session: AsyncSession,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await demo_service.seed(app_role_engine, default_tenant_id)
    await bind_tenant(app_session, default_tenant_id)
    await governance_service.auto_source_machine_review(app_session, default_tenant_id)
    await app_session.commit()

    row = (
        await db_session.execute(
            text(
                "SELECT a.admission_id FROM governance.admission_records a"
                " JOIN master.business_objects bo ON bo.object_id = a.object_id"
                " WHERE a.tenant_id = :t AND bo.source_id = 'SO-2026-00131'"
            ),
            {"t": default_tenant_id},
        )
    ).one()
    headers = await _login(client, "admin")
    resp = await client.post(
        f"{BASE}/governance/admission/{row.admission_id}/source-review",
        headers=headers,
        json={"decision": "APPROVED"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "SOURCE_APPROVED"
