"""T12 events 集成测试（B.3 契约）：批量入库三层幂等 / 部分失败重试 /
risk_level 校验 / JWT 查询分页 / 跨租户 RLS 隔离 / Idempotency-Key 必填。

应用引擎 = conftest.app_role_engine（NOBYPASSRLS，与生产 api 同角色）——
RLS 隔离（跨租户不可见）在测试路径真实生效。双轨认证：API Key
（write:event + write:registry + readonly）负责写路径，JWT（manager1）负责读。
"""

from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.main import create_app
from edp_api.modules.demo import service as demo_service
from edp_api.modules.tenantmgmt import service as tenantmgmt_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

EVENTS = "/api/v1/events"
OBJECTS = "/api/v1/objects"
LOGIN = "/api/v1/auth/login"
DEV_API_KEY = "edp-dev-agent-hub-key"
SEED_PASSWORD = "Admin@123!"

KEY_HEADERS = {"X-API-Key": DEV_API_KEY}


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS），events 路由随
    create_app 装配。"""
    await core_db.dispose_engine()
    monkeypatch.setattr(core_db, "get_engine", lambda: app_role_engine)
    transport = httpx.ASGITransport(app=create_app())
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        await core_db.dispose_engine()  # 重置绑定到测试引擎的会话工厂


@pytest.fixture(autouse=True)
async def _clean_events_rows(db_session: AsyncSession) -> None:
    """每测试后清场：删除本模块痕迹（idem-evt-% 幂等键/事件及其结果证据、
    tenantb.% 事件、SO-EVT-% 对象与关联 outbox、临时租户、本租户计量行），
    保证用例间独立（migrator 绕 RLS）。"""
    yield
    await db_session.execute(
        text(
            "DELETE FROM evidence.links WHERE evidence_id IN"
            " (SELECT evidence_id FROM evidence.records WHERE event_id IN"
            " (SELECT event_id FROM event.events WHERE idempotency_key LIKE 'idem-evt-%'))"
        )
    )
    await db_session.execute(
        text(
            "DELETE FROM evidence.records WHERE event_id IN"
            " (SELECT event_id FROM event.events WHERE idempotency_key LIKE 'idem-evt-%')"
        )
    )
    await db_session.execute(
        text(
            "DELETE FROM event.outbox WHERE aggregate_id IN"
            " (SELECT event_id FROM event.events WHERE idempotency_key LIKE 'idem-evt-%')"
            " OR aggregate_id IN"
            " (SELECT event_id FROM event.events WHERE event_type LIKE 'tenantb.%')"
            " OR aggregate_id IN"
            " (SELECT object_id FROM master.business_objects WHERE source_id LIKE 'SO-EVT-%')"
        )
    )
    await db_session.execute(
        text(
            "DELETE FROM event.events WHERE idempotency_key LIKE 'idem-evt-%'"
            " OR event_type LIKE 'tenantb.%'"
        )
    )
    await db_session.execute(
        text("DELETE FROM platform.idempotency_keys WHERE key LIKE 'idem-evt-%'")
    )
    await db_session.execute(
        text("DELETE FROM master.business_objects WHERE source_id LIKE 'SO-EVT-%'")
    )
    await db_session.execute(
        text(
            "DELETE FROM platform.tenant_usage_daily WHERE tenant_id IN"
            " (SELECT tenant_id FROM platform.tenants WHERE slug = 'tenant-b-evt')"
        )
    )
    await db_session.execute(
        text("DELETE FROM platform.tenants WHERE slug = 'tenant-b-evt'")
    )
    await db_session.execute(
        text(
            "DELETE FROM platform.tenant_usage_daily WHERE tenant_id IN"
            " (SELECT tenant_id FROM platform.tenants"
            " WHERE slug IN ('default', 'tenant-purge-evt'))"
        )
    )
    await db_session.execute(
        text(
            "DELETE FROM platform.tenant_usage_daily WHERE tenant_id IN"
            " (SELECT tenant_id FROM platform.tenants WHERE slug = 'tenant-purge-evt')"
        )
    )
    await db_session.execute(
        text("DELETE FROM platform.tenants WHERE slug = 'tenant-purge-evt'")
    )
    await db_session.commit()


async def _create_objects(client: httpx.AsyncClient, count: int) -> list[str]:
    """经 API Key 注册 count 个对象（source_id=SO-EVT-000n），返回 object_id 列表。"""
    ids: list[str] = []
    for seq in range(1, count + 1):
        resp = await client.post(
            OBJECTS,
            json={
                "object_type": "ORDER",
                "owner_domain": "sales",
                "source_system": "erp",
                "source_id": f"SO-EVT-{seq:04d}",
                "attributes": {"seq": seq},
            },
            headers=KEY_HEADERS,
        )
        assert resp.status_code == 201, resp.text
        ids.append(resp.json()["object_id"])
    return ids


def _event(object_id: str, seq: int, **extra: Any) -> dict[str, Any]:
    return {
        "event_type": "evt.test.created",
        "object_id": object_id,
        "source_system": "agent-hub",
        "occurred_at": f"2026-09-14T08:00:{seq:02d}Z",
        "actor_type": "AI",
        "actor_id": "agent:test",
        "data": {"seq": seq},
        **extra,
    }


def _batch(object_ids: list[str]) -> dict[str, Any]:
    return {"events": [_event(oid, seq) for seq, oid in enumerate(object_ids, 1)]}


def _key() -> str:
    return f"idem-evt-{uuid4()}"


def _key_headers(key: str) -> dict[str, str]:
    return {**KEY_HEADERS, "Idempotency-Key": key}


async def _login(client: httpx.AsyncClient, username: str) -> str:
    resp = await client.post(
        LOGIN, json={"username": username, "password": SEED_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


async def _count_events(db_session: AsyncSession, key: str) -> int:
    """批次入库行数（行级幂等键为 "{批次键}:{下标}"，按前缀计数）。"""
    return (
        await db_session.execute(
            text("SELECT count(*) FROM event.events WHERE idempotency_key LIKE :k"),
            {"k": f"{key}:%"},
        )
    ).scalar_one()


# ---- 1. API Key 入库 3 条：全接受 ----


async def test_batch_ingest_accepts_3(client: httpx.AsyncClient) -> None:
    object_ids = await _create_objects(client, 3)
    resp = await client.post(
        EVENTS + "/batch", json=_batch(object_ids), headers=_key_headers(_key())
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "accepted": 3,
        "duplicated": 0,
        "rejected": 0,
        "deduplicated": False,
    }


# ---- 2. 同批次同 Key 重放：存档响应原样返回 + deduplicated=true（不重算） ----


async def test_replay_same_key_deduplicated(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    object_ids = await _create_objects(client, 3)
    key = _key()
    first = await client.post(
        EVENTS + "/batch", json=_batch(object_ids), headers=_key_headers(key)
    )
    assert first.status_code == 200, first.text
    body1 = first.json()
    assert body1["accepted"] == 3

    second = await client.post(
        EVENTS + "/batch", json=_batch(object_ids), headers=_key_headers(key)
    )
    assert second.status_code == 200, second.text
    # 存档响应反序列化：accepted 仍为 3（若重算应为 0）→ 证明未重算
    assert second.json() == {**body1, "deduplicated": True}
    assert await _count_events(db_session, key) == 3


# ---- 3. 同批次新 Key：数据层 event_id 幂等 → duplicated、0 重复行 ----


async def test_replay_new_key_duplicated_no_new_rows(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    object_ids = await _create_objects(client, 3)
    resp = await client.post(
        EVENTS + "/batch", json=_batch(object_ids), headers=_key_headers(_key())
    )
    assert resp.json()["accepted"] == 3

    resp2 = await client.post(
        EVENTS + "/batch", json=_batch(object_ids), headers=_key_headers(_key())
    )
    assert resp2.status_code == 200, resp2.text
    assert resp2.json() == {
        "accepted": 0,
        "duplicated": 3,
        "rejected": 0,
        "deduplicated": False,
    }
    # 两批次事件表合计 3 行（0 重复行）
    rows = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM event.events WHERE idempotency_key LIKE 'idem-evt-%'"
            )
        )
    ).scalar_one()
    assert rows == 3


# ---- 4. 含 1 条坏 object_id 的批次：部分成功 + 同 Key 重放不走存档 ----


async def test_partial_rejection_and_same_key_retry(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    object_ids = await _create_objects(client, 4)
    # index=2 为坏 object_id
    batch = _batch(object_ids[:2] + [str(uuid4())] + object_ids[2:])
    key = _key()

    first = await client.post(EVENTS + "/batch", json=batch, headers=_key_headers(key))
    assert first.status_code == 200, first.text
    body1 = first.json()
    assert body1["accepted"] == 4
    assert body1["rejected"] == 1
    assert body1["deduplicated"] is False
    error1 = body1["errors"][0]
    assert body1["errors"] == [
        {"index": 2, "code": "VALIDATION_ERROR", "message": error1["message"]}
    ]
    assert "不存在" in error1["message"]
    assert await _count_events(db_session, key) == 4

    # 同 Key 重放：上次 rejected>0 → 未存档 → 重算（4 条已存在 → duplicated）
    second = await client.post(EVENTS + "/batch", json=batch, headers=_key_headers(key))
    assert second.status_code == 200, second.text
    body2 = second.json()
    assert body2["accepted"] == 0
    assert body2["duplicated"] == 4
    assert body2["rejected"] == 1
    assert body2["deduplicated"] is False
    assert body2["errors"][0]["index"] == 2
    assert await _count_events(db_session, key) == 4


# ---- 5. risk_level 越界值：400 VALIDATION_ERROR ----


async def test_invalid_risk_level_400(client: httpx.AsyncClient) -> None:
    object_ids = await _create_objects(client, 1)
    batch = {"events": [_event(object_ids[0], 1, risk_level="X9")]}
    resp = await client.post(
        EVENTS + "/batch", json=batch, headers=_key_headers(_key())
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


# ---- 6. JWT 查询：event_type 过滤命中 + limit=2 分页翻页 + 点查 200 ----


async def test_jwt_query_filter_pagination_and_detail(
    client: httpx.AsyncClient,
) -> None:
    object_ids = await _create_objects(client, 3)
    assert (
        await client.post(
            EVENTS + "/batch", json=_batch(object_ids), headers=_key_headers(_key())
        )
    ).json()["accepted"] == 3

    jwt_headers = {"Authorization": f"Bearer {await _login(client, 'manager1')}"}
    page1 = await client.get(
        EVENTS,
        params={"event_type": "evt.test.created", "limit": 2},
        headers=jwt_headers,
    )
    assert page1.status_code == 200, page1.text
    body1 = page1.json()
    assert len(body1["items"]) == 2
    assert body1["next_cursor"]
    # occurred_at DESC：首页为 08:00:03、08:00:02
    assert [item["data"]["seq"] for item in body1["items"]] == [3, 2]
    assert UUID(body1["items"][0]["event_id"]).version == 5  # 确定性派生

    page2 = await client.get(
        EVENTS,
        params={
            "event_type": "evt.test.created",
            "limit": 2,
            "cursor": body1["next_cursor"],
        },
        headers=jwt_headers,
    )
    assert page2.status_code == 200, page2.text
    body2 = page2.json()
    assert len(body2["items"]) == 1
    assert body2["next_cursor"] is None
    assert body2["items"][0]["data"]["seq"] == 1

    detail = await client.get(
        f"{EVENTS}/{body1['items'][0]['event_id']}", headers=jwt_headers
    )
    assert detail.status_code == 200, detail.text
    event = detail.json()
    assert event["event_id"] == body1["items"][0]["event_id"]
    assert event["object_id"] == object_ids[2]
    assert event["source_system"] == "agent-hub"
    assert event["occurred_at"] == "2026-09-14T08:00:03Z"
    assert event["actor_type"] == "AI"
    assert event["data"] == {"seq": 3}


# ---- 7. 跨租户：migrator 直插的第二租户事件对 default JWT 不可见 ----


async def test_cross_tenant_events_invisible(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    tenant_b = uuid4()
    b_object = uuid4()
    b_event = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO platform.tenants (tenant_id, slug, name, status)"
            " VALUES (:t, 'tenant-b-evt', '租户B', 'ACTIVE')"
        ),
        {"t": tenant_b},
    )
    await db_session.execute(
        text(
            "INSERT INTO master.business_objects"
            " (object_id, tenant_id, object_type, owner_domain, source_system, source_id)"
            " VALUES (:o, :t, 'ORDER', 'sales', 'tenantb-src', 'SO-EVT-B-0001')"
        ),
        {"o": b_object, "t": tenant_b},
    )
    await db_session.execute(
        text(
            "INSERT INTO event.events"
            " (event_id, tenant_id, event_type, object_id, source_system, occurred_at, data)"
            " VALUES (:e, :t, 'tenantb.local.evt', :o, 'tenantb-src', now(), '{}')"
        ),
        {"e": b_event, "t": tenant_b, "o": b_object},
    )
    await db_session.commit()
    # 行确实存在（migrator 绕 RLS 计数）
    total = (
        await db_session.execute(
            text("SELECT count(*) FROM event.events WHERE event_type = 'tenantb.local.evt'")
        )
    ).scalar_one()
    assert total == 1

    jwt_headers = {"Authorization": f"Bearer {await _login(client, 'manager1')}"}
    listed = await client.get(
        EVENTS, params={"event_type": "tenantb.local.evt"}, headers=jwt_headers
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"] == []

    detail = await client.get(f"{EVENTS}/{b_event}", headers=jwt_headers)
    assert detail.status_code == 404
    assert detail.json()["error"]["code"] == "NOT_FOUND"


# ---- 8. Idempotency-Key 缺失：400 VALIDATION_ERROR ----


async def test_missing_idempotency_key_400(client: httpx.AsyncClient) -> None:
    object_ids = await _create_objects(client, 1)
    resp = await client.post(
        EVENTS + "/batch", json=_batch(object_ids), headers=KEY_HEADERS
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


# ---- 9. total 与过滤一致（Page.total 仅 events 填充，翻页不变） ----


async def test_list_total_matches_filters(client: httpx.AsyncClient) -> None:
    object_ids = await _create_objects(client, 3)
    batch = {
        "events": [
            _event(oid, seq, risk_level="P1" if seq == 1 else None)
            for seq, oid in enumerate(object_ids, 1)
        ]
    }
    assert (
        await client.post(EVENTS + "/batch", json=batch, headers=_key_headers(_key()))
    ).json()["accepted"] == 3

    jwt_headers = {"Authorization": f"Bearer {await _login(client, 'manager1')}"}
    page1 = await client.get(
        EVENTS,
        params={"event_type": "evt.test.created", "limit": 2},
        headers=jwt_headers,
    )
    assert page1.status_code == 200, page1.text
    body1 = page1.json()
    assert body1["total"] == 3
    assert len(body1["items"]) == 2
    assert body1["next_cursor"]

    page2 = await client.get(
        EVENTS,
        params={
            "event_type": "evt.test.created",
            "limit": 2,
            "cursor": body1["next_cursor"],
        },
        headers=jwt_headers,
    )
    assert page2.status_code == 200, page2.text
    assert page2.json()["total"] == 3  # total = 过滤计数，不含 cursor

    by_risk = await client.get(
        EVENTS,
        params={"event_type": "evt.test.created", "risk_level": "P1"},
        headers=jwt_headers,
    )
    assert by_risk.json()["total"] == 1
    assert len(by_risk.json()["items"]) == 1

    by_since = await client.get(
        EVENTS,
        params={"event_type": "evt.test.created", "since": "2026-09-14T08:00:03Z"},
        headers=jwt_headers,
    )
    assert by_since.json()["total"] == 1

    empty = await client.get(
        EVENTS, params={"event_type": "evt.test.none"}, headers=jwt_headers
    )
    assert empty.status_code == 200, empty.text
    assert empty.json()["total"] == 0
    assert empty.json()["items"] == []


# ---- 10. delivery_status（outbox 左连派生）与 object_source_id（对象 join） ----


async def test_delivery_status_and_object_source_id(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    object_ids = await _create_objects(client, 1)
    assert (
        await client.post(
            EVENTS + "/batch", json=_batch(object_ids), headers=_key_headers(_key())
        )
    ).json()["accepted"] == 1

    jwt_headers = {"Authorization": f"Bearer {await _login(client, 'manager1')}"}
    params = {"event_type": "evt.test.created"}
    listed = await client.get(EVENTS, params=params, headers=jwt_headers)
    assert listed.status_code == 200, listed.text
    item = listed.json()["items"][0]
    assert item["delivery_status"] == "PENDING"  # 刚入库：outbox 未分发
    assert item["object_source_id"] == "SO-EVT-0001"
    assert isinstance(item["ingest_latency_ms"], int)

    event_id = UUID(item["event_id"])
    await db_session.execute(
        text("UPDATE event.outbox SET status = 'PUBLISHED' WHERE aggregate_id = :e"),
        {"e": event_id},
    )
    await db_session.commit()
    published = await client.get(EVENTS, params=params, headers=jwt_headers)
    assert published.json()["items"][0]["delivery_status"] == "DELIVERED"

    await db_session.execute(
        text("UPDATE event.outbox SET status = 'FAILED' WHERE aggregate_id = :e"),
        {"e": event_id},
    )
    await db_session.commit()
    failed = await client.get(EVENTS, params=params, headers=jwt_headers)
    assert failed.json()["items"][0]["delivery_status"] == "DEAD_LETTER"


# ---- 10b. 详情派生字段（与列表同组装路径）：PENDING/PUBLISHED/无 outbox ----


async def test_event_detail_derived_fields(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    object_ids = await _create_objects(client, 1)
    assert (
        await client.post(
            EVENTS + "/batch", json=_batch(object_ids), headers=_key_headers(_key())
        )
    ).json()["accepted"] == 1

    jwt_headers = {"Authorization": f"Bearer {await _login(client, 'manager1')}"}
    listed = await client.get(
        EVENTS, params={"event_type": "evt.test.created"}, headers=jwt_headers
    )
    event_id = UUID(listed.json()["items"][0]["event_id"])

    detail = await client.get(f"{EVENTS}/{event_id}", headers=jwt_headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["delivery_status"] == "PENDING"
    assert body["object_source_id"] == "SO-EVT-0001"
    assert isinstance(body["ingest_latency_ms"], int)

    await db_session.execute(
        text("UPDATE event.outbox SET status = 'PUBLISHED' WHERE aggregate_id = :e"),
        {"e": event_id},
    )
    await db_session.commit()
    published = await client.get(f"{EVENTS}/{event_id}", headers=jwt_headers)
    assert published.json()["delivery_status"] == "DELIVERED"

    # 无 outbox 行（如直接落库的事件）→ delivery_status 为 null，不报错
    await db_session.execute(
        text("DELETE FROM event.outbox WHERE aggregate_id = :e"), {"e": event_id}
    )
    await db_session.commit()
    orphan = await client.get(f"{EVENTS}/{event_id}", headers=jwt_headers)
    assert orphan.status_code == 200, orphan.text
    assert orphan.json()["delivery_status"] is None


# ---- 11. 结果事件（risk_level）自动落证据 + RESULT link；重放不重复 ----


async def test_result_event_evidence_and_replay_no_duplicate(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    object_ids = await _create_objects(client, 1)
    key = _key()
    batch = {
        "events": [
            _event(
                object_ids[0],
                1,
                event_type="capability.result.order_risk",
                result_type="ORDER_RISK",
                risk_level="P1",
                score=0.82,
                data={"summary": "物料X缺口1000，预计延误5天", "seq": 1},
            )
        ]
    }
    first = await client.post(EVENTS + "/batch", json=batch, headers=_key_headers(key))
    assert first.status_code == 200, first.text
    assert first.json()["accepted"] == 1

    event_id = (
        await db_session.execute(
            text("SELECT event_id FROM event.events WHERE idempotency_key = :k"),
            {"k": f"{key}:0"},
        )
    ).scalar_one()
    evidence = (
        await db_session.execute(
            text(
                "SELECT evidence_id, object_id, event_id, snapshot"
                " FROM evidence.records WHERE source_record_id = :s"
            ),
            {"s": f"result:{event_id}"},
        )
    ).one()
    assert evidence.event_id == event_id
    assert str(evidence.object_id) == object_ids[0]
    assert evidence.snapshot == {"summary": "物料X缺口1000，预计延误5天", "seq": 1}
    assert (
        await db_session.execute(
            text(
                "SELECT count(*) FROM evidence.links"
                " WHERE ref_type = 'RESULT' AND ref_id = :e"
            ),
            {"e": event_id},
        )
    ).scalar_one() == 1

    # 新 Key 重放：event_id 幂等 → duplicated，证据/link 不重复
    replay = await client.post(EVENTS + "/batch", json=batch, headers=_key_headers(_key()))
    assert replay.status_code == 200, replay.text
    assert replay.json()["duplicated"] == 1
    assert (
        await db_session.execute(
            text(
                "SELECT count(*) FROM evidence.records WHERE source_record_id = :s"
            ),
            {"s": f"result:{event_id}"},
        )
    ).scalar_one() == 1
    assert (
        await db_session.execute(
            text(
                "SELECT count(*) FROM evidence.links"
                " WHERE ref_type = 'RESULT' AND ref_id = :e"
            ),
            {"e": event_id},
        )
    ).scalar_one() == 1


# ---- 12. tenant_usage_daily 累加（accepted → events_in；重放 → duplicated） ----


async def _usage_totals(db_session: AsyncSession, tenant_id: UUID) -> tuple[int, int]:
    row = (
        await db_session.execute(
            text(
                "SELECT COALESCE(sum(events_in), 0),"
                " COALESCE(sum(events_duplicated), 0)"
                " FROM platform.tenant_usage_daily WHERE tenant_id = :t"
            ),
            {"t": tenant_id},
        )
    ).one()
    return int(row[0]), int(row[1])


async def test_usage_daily_accumulates(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    tenant_id = (
        await db_session.execute(
            text("SELECT tenant_id FROM platform.tenants WHERE slug = 'default'")
        )
    ).scalar_one()
    base_in, base_dup = await _usage_totals(db_session, tenant_id)

    object_ids = await _create_objects(client, 3)
    assert (
        await client.post(
            EVENTS + "/batch", json=_batch(object_ids), headers=_key_headers(_key())
        )
    ).json()["accepted"] == 3
    assert await _usage_totals(db_session, tenant_id) == (base_in + 3, base_dup)

    assert (
        await client.post(
            EVENTS + "/batch", json=_batch(object_ids), headers=_key_headers(_key())
        )
    ).json()["duplicated"] == 3
    assert await _usage_totals(db_session, tenant_id) == (base_in + 3, base_dup + 3)


# ---- 13. RESET 清 usage（T7 评审 Important：purge 含 tenant_usage_daily） ----


async def test_purge_tenant_business_data_clears_usage(
    db_session: AsyncSession,
) -> None:
    tenant_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO platform.tenants (tenant_id, slug, name, status)"
            " VALUES (:t, 'tenant-purge-evt', '复位租户', 'ACTIVE')"
        ),
        {"t": tenant_id},
    )
    await tenantmgmt_service.bump_usage_daily(
        db_session, tenant_id, events_in=5, events_duplicated=2
    )
    await db_session.commit()
    assert await _usage_totals(db_session, tenant_id) == (5, 2)

    await demo_service.purge_tenant_business_data(db_session, tenant_id)
    await db_session.commit()
    assert await _usage_totals(db_session, tenant_id) == (0, 0)


# ---- 14. event_type_prefix 前缀过滤（W6 T1：与 event_type 互斥）----


async def test_event_type_prefix_filters(client: httpx.AsyncClient) -> None:
    object_ids = await _create_objects(client, 3)
    batch = {
        "events": [
            _event(object_ids[0], 1, event_type="quality.check.passed"),
            _event(object_ids[1], 2, event_type="quality.check.failed"),
            _event(object_ids[2], 3, event_type="order.created"),
        ]
    }
    assert (
        await client.post(EVENTS + "/batch", json=batch, headers=_key_headers(_key()))
    ).json()["accepted"] == 3

    jwt_headers = {"Authorization": f"Bearer {await _login(client, 'manager1')}"}
    by_prefix = await client.get(
        EVENTS, params={"event_type_prefix": "quality."}, headers=jwt_headers
    )
    assert by_prefix.status_code == 200, by_prefix.text
    body = by_prefix.json()
    assert body["total"] == 2
    assert {item["event_type"] for item in body["items"]} == {
        "quality.check.passed",
        "quality.check.failed",
    }

    no_match = await client.get(
        EVENTS, params={"event_type_prefix": "shipping."}, headers=jwt_headers
    )
    assert no_match.status_code == 200, no_match.text
    assert no_match.json()["total"] == 0
    assert no_match.json()["items"] == []

    # 空串前缀按 None 处理（不过滤）：本测试批次的全部事件可见
    empty_prefix = await client.get(
        EVENTS, params={"event_type_prefix": ""}, headers=jwt_headers
    )
    assert empty_prefix.status_code == 200, empty_prefix.text
    assert empty_prefix.json()["total"] == 3
    assert "order.created" in {
        item["event_type"] for item in empty_prefix.json()["items"]
    }


# ---- 15. event_type 与 event_type_prefix 同传：400 互斥 ----


async def test_event_type_and_prefix_mutually_exclusive_400(
    client: httpx.AsyncClient,
) -> None:
    jwt_headers = {"Authorization": f"Bearer {await _login(client, 'manager1')}"}
    resp = await client.get(
        EVENTS,
        params={"event_type": "evt.test.created", "event_type_prefix": "evt.test"},
        headers=jwt_headers,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "互斥" in resp.json()["error"]["message"]
