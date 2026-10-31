"""T11 审计集成测试（EDP-009）：before_flush 切面 + 显式补点 + 查询 API。

核实记录（任务必办项）：tenantmgmt/dependencies.py 的 tenant_scoped **已经**
写入 current_principal / current_tenant_id（dependencies.py:39-40，T10 落地），
本任务无需补 set——切面与 record_explicit 的 actor/tenant 均取自该 contextvar，
全量既有测试亦不受影响（跑全量验证）。

权限矩阵核实（0005 种子 + core/security/rbac.py）：ANALYST 角色含 audit:read
（ANALYST = 全部 :read 权限，ANALYST1_USER_ID 登录可读审计），故"越权 403"
用例不能用 analyst1 JWT——改用 scopes 仅 ['write:event']（无 readonly）的
临时 API Key：SERVICE 主体的读判定要求 readonly scope（make_require_access）
→ 403 FORBIDDEN。
"""

import hashlib
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.main import create_app
from edp_api.modules.audit import service as audit_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

AUDIT = "/api/v1/audit-logs"
OBJECTS = "/api/v1/objects"
LOGIN = "/api/v1/auth/login"
SEED_PASSWORD = "Admin@123!"

# 无 readonly scope 的临时 API Key（403 用例；每测试自行插入/清场）
NO_READONLY_KEY = "t11-audit-no-readonly-key"
NO_READONLY_PRINCIPAL = "t11-audit-no-readonly"

COMPOSITE: dict[str, Any] = {
    "object_type": "ORDER",
    "owner_domain": "sales",
    "source_system": "erp",
    "source_id": "SO-AUD-2026-0001",
}


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS），audit 路由与
    审计切面随 create_app 装配（install_audit_aspect 幂等）。"""
    await core_db.dispose_engine()
    monkeypatch.setattr(core_db, "get_engine", lambda: app_role_engine)
    transport = httpx.ASGITransport(app=create_app())
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        await core_db.dispose_engine()  # 重置绑定到测试引擎的会话工厂


@pytest.fixture(autouse=True)
async def _clean_audit_rows(db_session: AsyncSession) -> None:
    """每测试后清场：本模块痕迹（SO-AUD-% 对象及其审计/outbox 行、临时
    API Key、T11_% 显式审计行），保证用例间独立（migrator 绕 RLS；audit_logs
    仅追加约束只作用于 edp_app，migrator 不受限）。"""
    yield
    await db_session.execute(
        text(
            """
            DELETE FROM platform.audit_logs WHERE
                (detail->'after'->>'source_id' LIKE 'SO-AUD-%'
                 OR detail->>'source_id' LIKE 'SO-AUD-%'
                 OR action LIKE 'T11_%'
                 OR detail->>'object_id' IN (
                     SELECT object_id::text FROM master.business_objects
                     WHERE source_id LIKE 'SO-AUD-%')
                 OR resource_id IN (
                     SELECT object_id::text FROM master.business_objects
                     WHERE source_id LIKE 'SO-AUD-%')
                 OR (resource_type = 'outbox' AND detail->'after'->>'aggregate_id' IN (
                     SELECT object_id::text FROM master.business_objects
                     WHERE source_id LIKE 'SO-AUD-%')))
            """
        )
    )
    await db_session.execute(
        text(
            "DELETE FROM event.outbox WHERE aggregate_id IN"
            " (SELECT object_id FROM master.business_objects WHERE source_id LIKE 'SO-AUD-%')"
            " OR aggregate_id IN"
            " (SELECT event_id FROM event.events WHERE object_id IN"
            "  (SELECT object_id FROM master.business_objects WHERE source_id LIKE 'SO-AUD-%'))"
        )
    )
    await db_session.execute(
        text(
            "DELETE FROM event.events WHERE object_id IN"
            " (SELECT object_id FROM master.business_objects WHERE source_id LIKE 'SO-AUD-%')"
        )
    )
    await db_session.execute(
        text("DELETE FROM platform.idempotency_keys WHERE key LIKE 'idem-audit-%'")
    )
    await db_session.execute(
        text("DELETE FROM master.business_objects WHERE source_id LIKE 'SO-AUD-%'")
    )
    await db_session.execute(
        text("DELETE FROM platform.api_keys WHERE principal_id = :p"),
        {"p": NO_READONLY_PRINCIPAL},
    )
    await db_session.commit()


async def _login(
    client: httpx.AsyncClient, username: str
) -> tuple[dict[str, str], str, str]:
    """JWT 登录 → (headers, principal_id, tenant_id)（sub 与 tenant 取登录响应）。"""
    resp = await client.post(
        LOGIN, json={"username": username, "password": SEED_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    return headers, str(body["user"]["user_id"]), str(body["tenant"]["tenant_id"])


async def _post_object(
    client: httpx.AsyncClient, headers: dict[str, str], attributes: dict
) -> httpx.Response:
    return await client.post(
        OBJECTS, json={**COMPOSITE, "attributes": attributes}, headers=headers
    )


async def _audit_rows(
    db_session: AsyncSession, *, action: str, resource_id: str
) -> list[dict]:
    rows = (
        await db_session.execute(
            text(
                "SELECT actor_type, actor_id, tenant_id::text AS tenant_id,"
                " resource_type, detail FROM platform.audit_logs"
                " WHERE action = :action AND resource_id = :rid"
                " ORDER BY audit_id"
            ),
            {"action": action, "rid": resource_id},
        )
    ).mappings()
    return [dict(row) for row in rows]


# ---- 1. POST /objects（JWT manager1）→ OBJECT_CREATE 行（after 含 source_id） ----


async def test_object_create_audited(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    headers, user_id, tenant_id = await _login(client, "manager1")
    resp = await _post_object(client, headers, {"amount": 120000.0})
    assert resp.status_code == 201, resp.text
    object_id = resp.json()["object_id"]

    rows = await _audit_rows(db_session, action="OBJECT_CREATE", resource_id=object_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["actor_type"] == "HUMAN"
    assert row["actor_id"] == user_id  # JWT sub = manager1 的 user_id
    assert row["tenant_id"] == tenant_id
    assert row["resource_type"] == "business_objects"
    assert row["detail"]["after"]["source_id"] == COMPOSITE["source_id"]
    assert row["detail"]["after"]["revision"] == 1
    assert "before" not in row["detail"]


# ---- 2. 同对象再 POST → OBJECT_UPDATE 行（before.revision=1 / after.revision=2） ----


async def test_object_update_audited_revision_diff(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    headers, user_id, _ = await _login(client, "manager1")
    first = await _post_object(client, headers, {"v": 1})
    assert first.status_code == 201, first.text
    second = await _post_object(client, headers, {"v": 2})
    assert second.status_code == 200, second.text
    assert second.json()["revision"] == 2
    object_id = second.json()["object_id"]

    rows = await _audit_rows(db_session, action="OBJECT_UPDATE", resource_id=object_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["actor_id"] == user_id
    detail = row["detail"]
    assert detail["before"] == {"revision": 1}
    assert detail["after"] == {"revision": 2}
    assert detail["changed"] == ["revision"]
    assert detail["source_id"] == COMPOSITE["source_id"]


# ---- 3. GET /audit-logs：action 过滤命中 + limit=1 游标翻页 ----


async def test_query_filter_and_cursor_pagination(
    client: httpx.AsyncClient,
) -> None:
    headers, user_id, _ = await _login(client, "manager1")
    # 两个不同对象 → 过滤集（action=OBJECT_CREATE@manager1）恰 2 行
    for seq in (1, 2):
        payload = {**COMPOSITE, "source_id": f"SO-AUD-2026-{seq:04d}", "attributes": {"seq": seq}}
        resp = await client.post(OBJECTS, json=payload, headers=headers)
        assert resp.status_code == 201, resp.text

    params = {
        "action": "OBJECT_CREATE",
        "resource_type": "business_objects",
        "actor_id": user_id,
        "limit": 1,
    }
    page1 = await client.get(AUDIT, params=params, headers=headers)
    assert page1.status_code == 200, page1.text
    body1 = page1.json()
    assert len(body1["items"]) == 1
    assert body1["next_cursor"]
    item = body1["items"][0]
    assert set(item) == {
        "audit_id",
        "occurred_at",
        "actor_type",
        "actor_id",
        "action",
        "resource_type",
        "resource_id",
        "detail",
    }
    assert isinstance(item["audit_id"], int)
    assert item["actor_id"] == user_id

    page2 = await client.get(
        AUDIT, params={**params, "cursor": body1["next_cursor"]}, headers=headers
    )
    assert page2.status_code == 200, page2.text
    body2 = page2.json()
    # 过滤集恰 2 行：第二页取最后一行后无更多
    assert len(body2["items"]) == 1
    # 列表路由 exclude_none：无更多页时 next_cursor 键缺省（等价 null）
    assert body2.get("next_cursor") is None
    # 翻页不重不漏
    ids1 = {item["audit_id"]}
    ids2 = {entry["audit_id"] for entry in body2["items"]}
    assert ids1 & ids2 == set()
    sources = {
        item["detail"]["after"]["source_id"],
        body2["items"][0]["detail"]["after"]["source_id"],
    }
    assert sources == {"SO-AUD-2026-0001", "SO-AUD-2026-0002"}


# ---- 4. 越权：无 readonly scope 的 API Key GET /audit-logs → 403 ----
# （ANALYST 有 audit:read，不能用 analyst1；见模块 docstring 核实记录）


async def test_no_readonly_scope_api_key_forbidden_403(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO platform.api_keys
                (key_id, key_hash, tenant_id, principal_type, principal_id,
                 scopes, status)
            VALUES
                (:key_id, :key_hash,
                 (SELECT tenant_id FROM platform.tenants WHERE slug = 'default'),
                 'SERVICE', :principal, ARRAY['write:event'], 'ACTIVE')
            """
        ),
        {
            "key_id": uuid4(),
            "key_hash": hashlib.sha256(NO_READONLY_KEY.encode()).hexdigest(),
            "principal": NO_READONLY_PRINCIPAL,
        },
    )
    await db_session.commit()

    resp = await client.get(AUDIT, headers={"X-API-Key": NO_READONLY_KEY})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    # 对照：种子 Key（含 readonly）可读——证明 403 由 scope 缺失而非路由/租户
    ok = await client.get(AUDIT, headers={"X-API-Key": "edp-dev-agent-hub-key"})
    assert ok.status_code == 200, ok.text


# ---- 5. record_explicit 直调：add 后同事务可见（actor 缺省 SERVICE/system） ----


async def test_record_explicit_direct_flush(db_session: AsyncSession) -> None:
    entry = await audit_service.record_explicit(
        db_session,
        action="T11_EXPLICIT_CREATE",
        resource_type="tests",
        resource_id="t11-explicit",
        detail={"note": "直调"},
        risk="P2",
    )
    # record_explicit 只 add 不 flush（T11 评审：同事务原子落，提交归调用方）
    # ——需要回填 audit_id 的调用方自行 flush
    await db_session.flush()
    assert isinstance(entry.audit_id, int)  # flush 后序列主键已回填
    row = (
        await db_session.execute(
            text(
                "SELECT actor_type, actor_id, detail FROM platform.audit_logs"
                " WHERE action = 'T11_EXPLICIT_CREATE' AND resource_id = 't11-explicit'"
            )
        )
    ).mappings().one()
    assert row["actor_type"] == "SERVICE"
    assert row["actor_id"] == "system"  # 无请求上下文时的缺省 actor
    assert row["detail"]["note"] == "直调"
    assert row["detail"]["risk"] == "P2"


# ---- 6. 0009 SECURITY DEFINER：edp_app 可执行滚动分区函数 ----


async def test_ensure_audit_partitions_executable_by_app_role(
    app_session: AsyncSession,
) -> None:
    """INVOKER 形态下 edp_app 无 platform schema 建表权，此调用必 permission
    denied；0009 改 SECURITY DEFINER 后可执行（幂等不炸）。"""
    await app_session.execute(text("SELECT platform.ensure_audit_partitions()"))


# ---- 7. 附带校验：切面对无关表的 UPDATE 无变更时不产审计行 ----


async def test_events_explicit_audit_via_ingest(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """events 批量入库显式补点：accepted 事件各产生一条 EVENT_CREATE 审计行
    （pg_insert 路径切面不可见，依赖 record_explicit）。"""
    key_headers = {
        "X-API-Key": "edp-dev-agent-hub-key",
        "Idempotency-Key": f"idem-audit-{uuid4()}",
    }
    created = await client.post(
        OBJECTS, json={**COMPOSITE, "attributes": {}}, headers=key_headers
    )
    assert created.status_code == 201, created.text

    batch = {
        "events": [
            {
                "event_type": "t11.audit.created",
                "object_id": created.json()["object_id"],
                "source_system": "agent-hub",
                "occurred_at": "2026-09-16T08:00:00Z",
                "actor_type": "AI",
                "actor_id": "agent:test",
                "data": {},
            }
        ]
    }
    resp = await client.post("/api/v1/events/batch", json=batch, headers=key_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["accepted"] == 1

    rows = (
        await db_session.execute(
            text(
                "SELECT actor_id, detail FROM platform.audit_logs"
                " WHERE action = 'EVENT_CREATE' AND resource_type = 'events'"
                " AND detail->>'event_type' = 't11.audit.created'"
            )
        )
    ).mappings()
    entries = [dict(r) for r in rows]
    assert len(entries) == 1
    assert entries[0]["actor_id"] == "agent-hub"
    assert entries[0]["detail"]["object_id"] == created.json()["object_id"]
    assert UUID(entries[0]["detail"]["object_id"])
