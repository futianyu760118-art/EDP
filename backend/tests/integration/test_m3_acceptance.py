"""T19 M3 端到端验收集成测试（演示脚本 ②~⑥ 断言化）。

与 ``docs/demo/m3-demo.md`` 七段脚本一一对应（① seed 幂等由 test_demo_seed.py
覆盖、⑦ 控制台段由前端回归 + T18 真 API 冒烟记录承载）：

- 段②：tools 六类接口（7 路径）200 + evidence_hint（对象 id + 最新快照事件 id）；
- 段③：非 GET → 405 统一 envelope（METHOD_NOT_ALLOWED + 通用文案，路由先于鉴权）；
- 段④：无 readonly scope 的 Key → 403，且 ``GET /audit-logs?action=GUARD_DENIED``
  可举证（演示脚本的 API 级证据路径，非仅 DB 直查）；
- 段⑤：seed 回流 → ``GET /ebms/exceptions?severity=P1`` 三条，场景 2
  （SO-2026-00123）case_id 非空且等于 seed 案例；
- 段⑥：``POST /admin/adapters/erp-demo/sync {mode:"replay"}`` → 202，轮询至
  SUCCEEDED 后 duplicated==fetched==36、registered=0（UUIDv5 幂等重放）。

会话形态：应用引擎 = conftest.app_role_engine（edp_app，FORCE RLS）；断言以
migrator db_session 直查（绕 RLS）。清场：purge_tenant_business_data（逆依赖序，
与 seed 复位同一实现）+ 本模块审计行/临时 Key/adapter_sync 任务行。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.core.security.apikey import hash_key
from edp_api.main import create_app
from edp_api.modules.audit.aspect import install_audit_aspect
from edp_api.modules.demo import service as demo_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

TOOLS = "/api/v1/tools"
EBMS = "/api/v1/ebms/exceptions"
ADAPTERS = "/api/v1/admin/adapters"
AUDIT = "/api/v1/audit-logs"
LOGIN = "/api/v1/auth/login"
SEED_PASSWORD = "Admin@123!"
DEV_KEY = "edp-dev-agent-hub-key"
DEV_HEADERS = {"X-API-Key": DEV_KEY}

# 无 readonly scope 的临时 API Key（段④ 403 用例；每测试自行插入/清场）
NO_READONLY_KEY = "t19-acceptance-no-readonly-key"
NO_READONLY_PRINCIPAL = "t19-acceptance-no-readonly"

# 演示数据集 erp 段记录数（段⑥ replay 全量重放口径；plm 段不经 erp-demo）
ERP_DEMO_COUNT = 36

# 段⑤：seed 回流 P1×3（场景 2/5/9），仅场景 2（SO-2026-00123）关联案例
P1_ORDER_NOS = {"SO-2026-00123", "SO-2026-00126", "SO-2026-00131"}
CASE_ORDER_NO = "SO-2026-00123"

POLL_TIMEOUT = 10.0
POLL_INTERVAL = 0.05


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS）——后台同步任务经
    core_db.get_engine() 取同一引擎（模块属性引用，monkeypatch 生效）。"""
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


@pytest.fixture
async def demo(
    app_role_engine: AsyncEngine, default_tenant_id: UUID
) -> demo_service.SeedStats:
    """default 租户演示数据集（T7 seed 等价路径）；清场见 _clean_m3_rows。"""
    stats = await demo_service.seed(app_role_engine, default_tenant_id)
    assert stats.failed == 0
    return stats


@pytest.fixture(autouse=True)
def _install_aspect() -> None:
    """seed 的 ORM 写依赖切面落审计——与 CLI 同一装配（幂等）。"""
    install_audit_aspect()


async def _purge(db_session: AsyncSession, tenant_id: UUID) -> None:
    """逆依赖序清 default 业务行 + 本模块审计行/临时 Key/adapter_sync 任务行。"""
    await demo_service.purge_tenant_business_data(db_session, tenant_id)
    await db_session.execute(
        text(
            "DELETE FROM platform.audit_logs WHERE tenant_id = :t"
            " AND actor_id IN ('adapter:erp', 'agent-hub')"
        ),
        {"t": tenant_id},
    )
    await db_session.execute(
        text(
            "DELETE FROM platform.audit_logs"
            " WHERE action = 'GUARD_DENIED' AND resource_type = 'tools'"
            " AND actor_id = :a"
        ),
        {"a": NO_READONLY_PRINCIPAL},
    )
    await db_session.execute(
        text("DELETE FROM platform.api_keys WHERE principal_id = :p"),
        {"p": NO_READONLY_PRINCIPAL},
    )
    # 任务落库（W5 T5）：sync 任务行及其 TASK 审计行（清场后 jobs/status 空）
    await db_session.execute(
        text(
            "DELETE FROM platform.audit_logs"
            " WHERE action LIKE 'TASK_%' AND resource_id IN ("
            "  SELECT task_id::text FROM ops.tasks WHERE task_type = 'adapter_sync')"
        )
    )
    await db_session.execute(
        text("DELETE FROM ops.tasks WHERE task_type = 'adapter_sync'")
    )
    await db_session.commit()


@pytest.fixture(autouse=True)
async def _clean_m3_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    """每测试前后清场：验收断言依赖 seed 单源基线（前清防他模块残留）。"""
    await _purge(db_session, default_tenant_id)
    yield
    await _purge(db_session, default_tenant_id)


async def _insert_api_key(
    db_session: AsyncSession,
    tenant_id: UUID,
    *,
    key: str,
    principal_id: str,
    scopes: list[str],
) -> None:
    """直插临时 API Key（照 test_tools 模式；hash_key 与生产同实现）。"""
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
            "key_hash": hash_key(key),
            "t": tenant_id,
            "principal": principal_id,
            "scopes": scopes,
        },
    )
    await db_session.commit()


async def _login(client: httpx.AsyncClient, username: str) -> dict[str, str]:
    resp = await client.post(
        LOGIN, json={"username": username, "password": SEED_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _poll_finished(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    sync_id: str,
    *,
    adapter: str = "erp-demo",
) -> dict[str, Any]:
    """轮询 /{adapter}/status 直至指定任务完成（超时 fail 附现场）。"""
    deadline = time.monotonic() + POLL_TIMEOUT
    while True:
        resp = await client.get(f"{ADAPTERS}/{adapter}/status", headers=headers)
        assert resp.status_code == 200, resp.text
        last_sync = resp.json()["last_sync"]
        if last_sync and last_sync["sync_id"] == sync_id and last_sync["finished_at"]:
            return last_sync
        if time.monotonic() > deadline:
            pytest.fail(f"同步任务 {sync_id} 未在 {POLL_TIMEOUT}s 内完成：{last_sync}")
        await asyncio.sleep(POLL_INTERVAL)


async def _assert_snapshot_hint(
    db_session: AsyncSession, hint: dict[str, Any]
) -> None:
    """evidence_hint 直证：event_id 即该对象最新快照事件。"""
    UUID(hint["object_id"])
    UUID(hint["event_id"])
    latest = (
        await db_session.execute(
            text(
                "SELECT event_id FROM event.events"
                " WHERE object_id = :o AND event_type LIKE '%\\_SNAPSHOT'"
                " ORDER BY occurred_at DESC, event_id DESC LIMIT 1"
            ),
            {"o": UUID(hint["object_id"])},
        )
    ).scalar_one_or_none()
    assert latest is not None
    assert str(latest) == hint["event_id"]


# ---- 段②：tools 六类接口 200 + evidence_hint ----


async def test_tools_endpoints_200_with_evidence_hint(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    demo: demo_service.SeedStats,
) -> None:
    # 单对象接口（顶层 evidence_hint）：B.8 示例 SO-2026-00123 / X-100 / P-F / S-021 / C-008
    # V1.2 T21：official_only 缺省 true（仅 OFFICIAL/ARCHIVED）——demo 数据未走
    # 准入审核，此处显式 false（过渡期适配，记偏差；门禁行为见
    # test_v12_fact_layer）
    detail_paths: tuple[tuple[str, dict[str, str] | None], ...] = (
        ("/orders/SO-2026-00123", None),
        ("/inventory", {"material_code": "X-100"}),
        ("/bom", {"product_code": "P-F"}),
        ("/supplier-lead-times", {"supplier_code": "S-021"}),
        ("/customers/C-008", None),
    )
    for path, params in detail_paths:
        merged = {"official_only": "false", **(params or {})}
        resp = await client.get(f"{TOOLS}{path}", params=merged, headers=DEV_HEADERS)
        assert resp.status_code == 200, f"{path}: {resp.text}"
        body = resp.json()
        assert "evidence_hint" in body, f"{path}: {body}"
        hint = body["evidence_hint"]
        assert hint["object_id"], path
        assert hint["event_id"], path
        await _assert_snapshot_hint(db_session, hint)

    # 列表接口（envelope.items 每行 evidence_hint 指向自身对象）
    resp = await client.get(
        f"{TOOLS}/orders",
        params={"customer": "C-008", "official_only": "false"},
        headers=DEV_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert [item["order_no"] for item in items] == ["SO-2026-00123", "SO-2026-00128"]
    for item in items:
        assert item["evidence_hint"]["object_id"] == item["object_id"]
        assert item["evidence_hint"]["event_id"]
        await _assert_snapshot_hint(db_session, item["evidence_hint"])

    resp = await client.get(
        f"{TOOLS}/purchase-orders",
        params={"material_code": "X-100", "official_only": "false"},
        headers=DEV_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    purchase_items = resp.json()["items"]
    assert [item["po_no"] for item in purchase_items] == ["PO-2026-00771"]
    for item in purchase_items:
        assert item["evidence_hint"]["object_id"] == item["object_id"]
        assert item["evidence_hint"]["event_id"]
        await _assert_snapshot_hint(db_session, item["evidence_hint"])


# ---- 段③：非 GET → 405 统一 envelope（路由先于鉴权，无需凭据） ----


async def test_non_get_405_envelope(client: httpx.AsyncClient) -> None:
    resp = await client.post(f"{TOOLS}/orders/SO-2026-00123", json={})
    assert resp.status_code == 405, resp.text
    assert resp.headers.get("allow") == "GET"
    body = resp.json()["error"]
    assert body["code"] == "METHOD_NOT_ALLOWED"
    assert body["message"] == "方法不允许"
    UUID(body["request_id"])


# ---- 段④：无 readonly scope Key → 403 + GUARD_DENIED 审计可查 ----


async def test_no_readonly_403_and_guard_denied_audited(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await _insert_api_key(
        db_session,
        default_tenant_id,
        key=NO_READONLY_KEY,
        principal_id=NO_READONLY_PRINCIPAL,
        scopes=["write:event"],
    )

    resp = await client.get(
        f"{TOOLS}/orders/SO-2026-00123", headers={"X-API-Key": NO_READONLY_KEY}
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    # 演示脚本举证路径：GET /audit-logs?action=GUARD_DENIED（admin JWT）
    headers = await _login(client, "admin")
    audit = await client.get(
        AUDIT,
        params={"action": "GUARD_DENIED", "resource_type": "tools", "limit": 100},
        headers=headers,
    )
    assert audit.status_code == 200, audit.text
    rows = [
        item
        for item in audit.json()["items"]
        if item["actor_id"] == NO_READONLY_PRINCIPAL
    ]
    assert len(rows) == 1
    row = rows[0]
    assert row["actor_type"] == "SERVICE"
    assert row["detail"]["path"] == f"{TOOLS}/orders/SO-2026-00123"
    assert row["detail"]["reason"] == "缺少 scope：readonly"
    assert row["detail"]["scopes"] == ["write:event"]


# ---- 段⑤：回流 → exceptions P1 含 case_id（场景 2） ----


async def test_reflow_exceptions_p1_with_case_id(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    assert demo.events_accepted == 10
    assert demo.case_created is True

    resp = await client.get(EBMS, params={"severity": "P1"}, headers=DEV_HEADERS)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 3
    assert {item["risk_level"] for item in items} == {"P1"}
    assert {item["order_no"] for item in items} == P1_ORDER_NOS

    case_id = (
        await db_session.execute(
            text("SELECT case_id FROM decision.cases WHERE tenant_id = :t"),
            {"t": default_tenant_id},
        )
    ).scalar_one()
    with_case = [item for item in items if item["case_id"] is not None]
    assert [item["order_no"] for item in with_case] == [CASE_ORDER_NO]
    assert with_case[0]["case_id"] == str(case_id)
    assert with_case[0]["summary"] == "物料X缺口1000，预计延误5天"


# ---- 段⑥：replay 202 → status duplicated==fetched（seed 后全量重放） ----


async def test_replay_202_then_duplicated_equals_fetched(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    headers = await _login(client, "admin")
    resp = await client.post(
        f"{ADAPTERS}/erp-demo/sync", json={"mode": "replay"}, headers=headers
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "RUNNING"
    sync_id = body["sync_id"]

    last_sync = await _poll_finished(client, headers, sync_id)
    assert last_sync["status"] == "SUCCEEDED"
    assert last_sync["error"] is None
    assert last_sync["stats"] == {
        "fetched": ERP_DEMO_COUNT,
        "registered": 0,
        "duplicated": ERP_DEMO_COUNT,
        "failed": 0,
    }
    assert last_sync["stats"]["duplicated"] == last_sync["stats"]["fetched"]

    # 幂等直证：重放不新增行、不推 revision（对象数不变且全为 revision=1）
    row = (
        await db_session.execute(
            text(
                "SELECT count(*), max(revision) FROM master.business_objects"
                " WHERE tenant_id = :t AND source_system = 'erp'"
            ),
            {"t": default_tenant_id},
        )
    ).one()
    assert (row[0], row[1]) == (ERP_DEMO_COUNT, 1)
