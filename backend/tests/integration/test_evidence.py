"""T12 证据 API 集成测试（EDP-008）：canonical checksum / verify 告警 /
逆向追溯 / 权限双轨 / 跨租户 404。

权限核实（0005 种子 + rbac.make_require_access）：
- 种子 agent-hub Key scopes = ['readonly','write:event','write:registry']——
  readonly 覆盖全部读（GET 200），但**无 write:evidence**（POST → 403）；
- 临时只读 Key（scopes=['readonly']）POST → 403；
- JWT manager1（MANAGER = evidence:read+write）创建/读取全通。
"""

import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.main import create_app
from edp_api.modules.evidence.service import canonical_json, compute_checksum
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

EVIDENCE = "/api/v1/evidence"
OBJECTS = "/api/v1/objects"
LOGIN = "/api/v1/auth/login"
SEED_PASSWORD = "Admin@123!"
SEED_KEY = "edp-dev-agent-hub-key"

READONLY_KEY = "t12-evidence-readonly-key"
READONLY_PRINCIPAL = "t12-evidence-readonly"

COMPOSITE: dict[str, Any] = {
    "object_type": "ORDER",
    "owner_domain": "sales",
    "source_system": "erp",
    "source_id": "SO-EVD-2026-0001",
}

SNAPSHOT = {"amount": 120000.0, "name": "订单A", "status": "已确认", "seq": 1}


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS），evidence 路由随
    create_app 装配（审计切面幂等）。"""
    await core_db.dispose_engine()
    monkeypatch.setattr(core_db, "get_engine", lambda: app_role_engine)
    transport = httpx.ASGITransport(app=create_app())
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        await core_db.dispose_engine()  # 重置绑定到测试引擎的会话工厂


@pytest.fixture(autouse=True)
async def _clean_evidence_rows(db_session: AsyncSession) -> None:
    """每测试后清场：本模块痕迹（SO-EVD-% 对象/证据/links/审计/outbox、临时
    API Key、tenant-b-evidence 租户），保证用例间独立（migrator 绕 RLS；
    audit_logs 仅追加约束只作用于 edp_app，migrator 不受限）。"""
    yield
    await db_session.execute(
        text(
            """
            DELETE FROM platform.audit_logs WHERE
                detail->'after'->>'source_id' LIKE 'SO-EVD-%'
                OR detail->>'source_id' LIKE 'SO-EVD-%'
                OR detail->'after'->>'source_record_id' LIKE 'SO-EVD-%'
                OR resource_id IN (
                    SELECT evidence_id::text FROM evidence.records WHERE object_id IN
                    (SELECT object_id FROM master.business_objects
                     WHERE source_id LIKE 'SO-EVD-%'))
                OR detail->'after'->>'evidence_id' IN (
                    SELECT evidence_id::text FROM evidence.records WHERE object_id IN
                    (SELECT object_id FROM master.business_objects
                     WHERE source_id LIKE 'SO-EVD-%'))
            """
        )
    )
    await db_session.execute(
        text(
            "DELETE FROM evidence.links WHERE evidence_id IN"
            " (SELECT evidence_id FROM evidence.records WHERE object_id IN"
            "  (SELECT object_id FROM master.business_objects WHERE source_id LIKE 'SO-EVD-%'))"
        )
    )
    await db_session.execute(
        text(
            "DELETE FROM evidence.records WHERE object_id IN"
            " (SELECT object_id FROM master.business_objects WHERE source_id LIKE 'SO-EVD-%')"
        )
    )
    await db_session.execute(
        text(
            "DELETE FROM event.outbox WHERE aggregate_id IN"
            " (SELECT object_id FROM master.business_objects WHERE source_id LIKE 'SO-EVD-%')"
        )
    )
    await db_session.execute(
        text("DELETE FROM master.business_objects WHERE source_id LIKE 'SO-EVD-%'")
    )
    await db_session.execute(
        text("DELETE FROM platform.api_keys WHERE principal_id = :p"),
        {"p": READONLY_PRINCIPAL},
    )
    await db_session.execute(
        text(
            "DELETE FROM platform.tenant_usage_daily WHERE tenant_id IN"
            " (SELECT tenant_id FROM platform.tenants WHERE slug = 'tenant-b-evidence')"
        )
    )
    await db_session.execute(
        text("DELETE FROM platform.tenants WHERE slug = 'tenant-b-evidence'")
    )
    await db_session.commit()


async def _login(client: httpx.AsyncClient) -> dict[str, str]:
    """JWT 登录 manager1（MANAGER = evidence:read+write）。"""
    resp = await client.post(
        LOGIN, json={"username": "manager1", "password": SEED_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _create_object(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    """造对象（JWT upsert，SO-EVD-% 前缀供清场识别）。"""
    resp = await client.post(
        OBJECTS, json={**COMPOSITE, "attributes": {"amount": 120000.0}}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["object_id"]


async def _create_evidence(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    object_id: str,
    *,
    snapshot: dict,
    captured_at: str = "2026-09-16T08:30:00Z",
    links: list[dict] | None = None,
    source_record_id: str | None = None,
) -> httpx.Response:
    payload: dict[str, Any] = {
        "source_system": "erp",
        "source_record_id": source_record_id or f"{COMPOSITE['source_id']}#v1",
        "object_id": object_id,
        "snapshot": snapshot,
        "captured_at": captured_at,
    }
    if links is not None:
        payload["links"] = links
    return await client.post(EVIDENCE, json=payload, headers=headers)


async def _verify_failed_rows(
    db_session: AsyncSession, evidence_id: str
) -> list[dict]:
    rows = (
        await db_session.execute(
            text(
                "SELECT detail FROM platform.audit_logs"
                " WHERE action = 'EVIDENCE_VERIFY_FAILED' AND resource_id = :rid"
                " ORDER BY audit_id"
            ),
            {"rid": evidence_id},
        )
    ).mappings()
    return [dict(row) for row in rows]


# ---- 1. POST /evidence：201 + sha256 前缀 + 与本地重算一致；GET 回读一致 ----


async def test_create_and_get_roundtrip(
    client: httpx.AsyncClient,
) -> None:
    headers = await _login(client)
    object_id = await _create_object(client, headers)

    case_ref = str(uuid4())
    resp = await _create_evidence(
        client,
        headers,
        object_id,
        snapshot=SNAPSHOT,
        links=[{"ref_type": "CASE", "ref_id": case_ref}],
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert set(body) == {"evidence_id", "checksum", "captured_at"}
    evidence_id = body["evidence_id"]
    UUID(evidence_id)

    # checksum 前缀 + 与本地 canonical 重算一致（同一实现语义的双侧确认）
    expected = "sha256:" + hashlib.sha256(
        canonical_json(SNAPSHOT).encode("utf-8")
    ).hexdigest()
    assert body["checksum"].startswith("sha256:")
    assert body["checksum"] == expected
    assert compute_checksum(SNAPSHOT) == expected

    detail = await client.get(f"{EVIDENCE}/{evidence_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    detail_body = detail.json()
    assert detail_body["evidence_id"] == evidence_id
    assert detail_body["object_id"] == object_id
    assert detail_body["snapshot"] == SNAPSHOT
    assert detail_body["checksum"] == expected
    assert detail_body["source_record_id"] == f"{COMPOSITE['source_id']}#v1"
    assert [(link["ref_type"], link["ref_id"]) for link in detail_body["links"]] == [
        ("CASE", case_ref)
    ]

    # verify 初次即 valid（未篡改）
    verify = await client.get(f"{EVIDENCE}/{evidence_id}/verify", headers=headers)
    assert verify.status_code == 200, verify.text
    verify_body = verify.json()
    assert verify_body["evidence_id"] == evidence_id
    assert verify_body["valid"] is True
    assert verify_body["verified_at"]


# ---- 2. 篡改 → verify valid=false + EVIDENCE_VERIFY_FAILED（P1）；恢复无新告警 ----


async def test_verify_detects_tampering_and_alerts(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _login(client)
    object_id = await _create_object(client, headers)
    created = await _create_evidence(client, headers, object_id, snapshot=SNAPSHOT)
    assert created.status_code == 201, created.text
    evidence_id = created.json()["evidence_id"]
    stored_checksum = created.json()["checksum"]

    # migrator 直改 snapshot 列（绕 RLS/审计切面——纯 SQL 不经 ORM 状态）
    await db_session.execute(
        text("UPDATE evidence.records SET snapshot = snapshot || CAST(:t AS jsonb)"
             " WHERE evidence_id = :e"),
        {"t": '{"tampered":true}', "e": evidence_id},
    )
    await db_session.commit()

    failed = await client.get(f"{EVIDENCE}/{evidence_id}/verify", headers=headers)
    assert failed.status_code == 200, failed.text
    assert failed.json()["valid"] is False

    rows = await _verify_failed_rows(db_session, evidence_id)
    assert len(rows) == 1
    detail = rows[0]["detail"]
    assert detail["risk"] == "P1"
    assert detail["expected"] == stored_checksum
    assert detail["actual"] == compute_checksum({**SNAPSHOT, "tampered": True})
    assert detail["actual"] != detail["expected"]

    # 恢复原值 → valid=true 且不新增告警行
    await db_session.execute(
        text("UPDATE evidence.records SET snapshot = CAST(:s AS jsonb)"
             " WHERE evidence_id = :e"),
        {"s": json.dumps(SNAPSHOT, ensure_ascii=False), "e": evidence_id},
    )
    await db_session.commit()

    ok = await client.get(f"{EVIDENCE}/{evidence_id}/verify", headers=headers)
    assert ok.status_code == 200, ok.text
    assert ok.json()["valid"] is True
    assert len(await _verify_failed_rows(db_session, evidence_id)) == 1  # 仍仅 1 行


# ---- 3. ?ref_type&ref_id 逆向命中 + object_id 过滤（无命中为空） ----


async def test_reverse_ref_lookup_and_object_filter(
    client: httpx.AsyncClient,
) -> None:
    headers = await _login(client)
    object_id = await _create_object(client, headers)

    case_ref = str(uuid4())
    first = await _create_evidence(
        client,
        headers,
        object_id,
        snapshot=SNAPSHOT,
        captured_at="2026-09-16T08:30:00Z",
        links=[{"ref_type": "CASE", "ref_id": case_ref}],
    )
    assert first.status_code == 201, first.text
    second = await _create_evidence(
        client,
        headers,
        object_id,
        snapshot={**SNAPSHOT, "seq": 2},
        captured_at="2026-09-16T09:00:00Z",
        links=[],
    )
    assert second.status_code == 201, second.text

    by_ref = await client.get(
        EVIDENCE,
        params={"ref_type": "CASE", "ref_id": case_ref},
        headers=headers,
    )
    assert by_ref.status_code == 200, by_ref.text
    ref_items = by_ref.json()["items"]
    assert [item["evidence_id"] for item in ref_items] == [first.json()["evidence_id"]]
    # 列表简投影字段集（无 snapshot/links 大字段）
    assert set(ref_items[0]) == {
        "evidence_id",
        "source_system",
        "source_record_id",
        "object_id",
        "checksum",
        "captured_at",
    }

    by_object = await client.get(
        EVIDENCE, params={"object_id": object_id}, headers=headers
    )
    assert by_object.status_code == 200, by_object.text
    object_items = by_object.json()["items"]
    assert len(object_items) == 2  # captured_at DESC：09:00 在前
    assert object_items[0]["evidence_id"] == second.json()["evidence_id"]

    miss = await client.get(
        EVIDENCE,
        params={"ref_type": "CASE", "ref_id": str(uuid4())},
        headers=headers,
    )
    assert miss.status_code == 200, miss.text
    assert miss.json()["items"] == []


# ---- 3b. q 模糊搜索（source_record_id/source_system，W3R-T8） ----


async def test_search_q_matches_record_id_and_source_system(
    client: httpx.AsyncClient,
) -> None:
    headers = await _login(client)
    object_id = await _create_object(client, headers)

    hit = await _create_evidence(
        client,
        headers,
        object_id,
        snapshot={**SNAPSHOT, "seq": "q-hit"},
        source_record_id="ORDER-Q-777#v1",
    )
    assert hit.status_code == 201, hit.text
    other = await _create_evidence(
        client,
        headers,
        object_id,
        snapshot={**SNAPSHOT, "seq": "q-other"},
        source_record_id="INVOICE-888#v1",
    )
    assert other.status_code == 201, other.text

    by_record = await client.get(
        EVIDENCE, params={"q": "order-q"}, headers=headers
    )
    assert by_record.status_code == 200, by_record.text
    assert [item["evidence_id"] for item in by_record.json()["items"]] == [
        hit.json()["evidence_id"]
    ]

    # source_system 命中（两条都是 erp → 全量）
    by_source = await client.get(EVIDENCE, params={"q": "ERP"}, headers=headers)
    assert by_source.status_code == 200, by_source.text
    assert len(by_source.json()["items"]) == 2

    # 组合过滤：q + object_id 与 q 无结果
    combo = await client.get(
        EVIDENCE,
        params={"q": "order-q", "object_id": object_id},
        headers=headers,
    )
    assert combo.status_code == 200, combo.text
    assert len(combo.json()["items"]) == 1

    empty = await client.get(
        EVIDENCE, params={"q": "no-such-record"}, headers=headers
    )
    assert empty.status_code == 200, empty.text
    assert empty.json()["items"] == []

    # LIKE 通配符按字面处理（% 不放大匹配）
    literal = await client.get(EVIDENCE, params={"q": "%"}, headers=headers)
    assert literal.status_code == 200, literal.text
    assert literal.json()["items"] == []


# ---- 4. API Key 双轨：种子 Key GET 200（readonly）；无 write:evidence POST 403 ----


async def test_api_key_read_ok_and_write_forbidden_403(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _login(client)
    object_id = await _create_object(client, headers)
    created = await _create_evidence(client, headers, object_id, snapshot=SNAPSHOT)
    assert created.status_code == 201, created.text

    # 种子 agent-hub Key：scopes=['readonly','write:event','write:registry']——
    # readonly 覆盖读 → GET 列表 200
    key_headers = {"X-API-Key": SEED_KEY}
    listed = await client.get(EVIDENCE, headers=key_headers)
    assert listed.status_code == 200, listed.text
    assert any(
        item["evidence_id"] == created.json()["evidence_id"]
        for item in listed.json()["items"]
    )

    # 种子 Key 无 write:evidence → POST 403
    seed_post = await _create_evidence(client, key_headers, object_id, snapshot=SNAPSHOT)
    assert seed_post.status_code == 403, seed_post.text
    assert seed_post.json()["error"]["code"] == "FORBIDDEN"

    # 临时只读 Key（scopes=['readonly']）POST 同样 403（照 test_audit 临时 Key 模式）
    await db_session.execute(
        text(
            """
            INSERT INTO platform.api_keys
                (key_id, key_hash, tenant_id, principal_type, principal_id,
                 scopes, status)
            VALUES
                (:key_id, :key_hash,
                 (SELECT tenant_id FROM platform.tenants WHERE slug = 'default'),
                 'SERVICE', :principal, ARRAY['readonly'], 'ACTIVE')
            """
        ),
        {
            "key_id": uuid4(),
            "key_hash": hashlib.sha256(READONLY_KEY.encode()).hexdigest(),
            "principal": READONLY_PRINCIPAL,
        },
    )
    await db_session.commit()

    readonly_post = await _create_evidence(
        client, {"X-API-Key": READONLY_KEY}, object_id, snapshot=SNAPSHOT
    )
    assert readonly_post.status_code == 403, readonly_post.text
    assert readonly_post.json()["error"]["code"] == "FORBIDDEN"

    readonly_get = await client.get(EVIDENCE, headers={"X-API-Key": READONLY_KEY})
    assert readonly_get.status_code == 200, readonly_get.text


# ---- 5. 跨租户：tenant-b 证据在 default 会话 GET → 404（不泄露存在性） ----


async def test_cross_tenant_evidence_not_found(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    tenant_b, b_object, b_evidence, b_link = (uuid4() for _ in range(4))
    await db_session.execute(
        text(
            "INSERT INTO platform.tenants (tenant_id, slug, name, status)"
            " VALUES (:t, 'tenant-b-evidence', '租户B', 'ACTIVE')"
        ),
        {"t": tenant_b},
    )
    await db_session.execute(
        text(
            "INSERT INTO master.business_objects"
            " (object_id, tenant_id, object_type, owner_domain, source_system, source_id)"
            " VALUES (:o, :t, 'ORDER', 'sales', 'tenantb-src', 'SO-EVD-B-0001')"
        ),
        {"o": b_object, "t": tenant_b},
    )
    await db_session.execute(
        text(
            "INSERT INTO evidence.records"
            " (evidence_id, tenant_id, source_system, source_record_id, object_id,"
            "  checksum, snapshot, captured_at)"
            " VALUES (:e, :t, 'tenantb-src', 'SO-EVD-B-0001#v1', :o,"
            "  'sha256:b', '{}', '2026-09-16T00:00:00Z')"
        ),
        {"e": b_evidence, "t": tenant_b, "o": b_object},
    )
    b_ref = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO evidence.links"
            " (link_id, tenant_id, evidence_id, ref_type, ref_id)"
            " VALUES (:l, :t, :e, 'CASE', :r)"
        ),
        {"l": b_link, "t": tenant_b, "e": b_evidence, "r": b_ref},
    )
    await db_session.commit()

    headers = await _login(client)  # default 租户（manager1）
    detail = await client.get(f"{EVIDENCE}/{b_evidence}", headers=headers)
    assert detail.status_code == 404
    assert detail.json()["error"]["code"] == "NOT_FOUND"

    verify = await client.get(f"{EVIDENCE}/{b_evidence}/verify", headers=headers)
    assert verify.status_code == 404

    # RLS 双证：object_id / ref 逆向过滤均不可见（0 行而非报错）
    by_object = await client.get(
        EVIDENCE, params={"object_id": str(b_object)}, headers=headers
    )
    assert by_object.status_code == 200, by_object.text
    assert by_object.json()["items"] == []

    by_ref = await client.get(
        EVIDENCE,
        params={"ref_type": "CASE", "ref_id": str(b_ref)},  # 真实插入的 ref_id
        headers=headers,
    )
    assert by_ref.status_code == 200, by_ref.text
    assert by_ref.json()["items"] == []


# ---- 6. object_id 不存在：400 VALIDATION_ERROR（RLS 下跨租户 object 同义） ----


async def test_create_evidence_unknown_object_400(client: httpx.AsyncClient) -> None:
    headers = await _login(client)
    resp = await _create_evidence(
        client, headers, str(uuid4()), snapshot=SNAPSHOT
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "object_id 不存在" in resp.json()["error"]["message"]
