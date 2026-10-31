"""T13 Outbox Worker 集成测试（EDP-006，设计文档 7.2）：

1. 真实 API 路径造数（POST /objects + POST /events/batch）→ 事务性 outbox
   PENDING 落账 → dispatch_batch 一轮全 PUBLISHED；
2. BrokenSubscriber nack → retry_count/available_at 指数退避递增，
   连续重投至 outbox_max_retries=8 → FAILED；
3. 退避数列 available_at-now() ≈ 2^n * 5s（容差 1s）；
4. 单租户异常隔离：订阅者仅对 default 抛错 → tenant-b 照常 PUBLISHED；
5. SKIP LOCKED 并发：同租户两个并发 dispatch_batch 不双发。

引擎形态：dispatch 使用 app_role_engine（edp_app，NOBYPASSRLS）——
worker 同样受 FORCE RLS 约束，bind_tenant 后才能读写 outbox，测试路径
与生产 worker 完全一致；断言侧用 migrator 直查绕 RLS。
"""

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.core.events import LoggingSubscriber, OutboxMessage, Subscriber
from edp_api.main import create_app
from edp_worker.outbox_dispatch import dispatch_batch
from edp_worker.scheduler import active_tenant_ids, reset_tenant_cache
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

pytestmark = [pytest.mark.integration]

EVENTS = "/api/v1/events"
OBJECTS = "/api/v1/objects"
DEV_API_KEY = "edp-dev-agent-hub-key"
KEY_HEADERS = {"X-API-Key": DEV_API_KEY}

BACKOFF_BASE_S = 5.0


# ---- 测试替身（订阅者注入接缝） ----


class RecordingSubscriber:
    """记录全部收到的消息（ack）。"""

    def __init__(self) -> None:
        self.messages: list[OutboxMessage] = []

    async def on_event(self, msg: OutboxMessage) -> None:
        self.messages.append(msg)


class BrokenSubscriber:
    """一律 nack（驱动重投路径）。"""

    async def on_event(self, msg: OutboxMessage) -> None:
        raise RuntimeError(f"boom:{msg.outbox_id}")


class BrokenForTenantSubscriber:
    """仅对指定租户 nack（异常隔离用例）。"""

    def __init__(self, broken_tenant_id: UUID) -> None:
        self._broken_tenant_id = broken_tenant_id

    async def on_event(self, msg: OutboxMessage) -> None:
        if msg.tenant_id == self._broken_tenant_id:
            raise RuntimeError(f"tenant down:{msg.outbox_id}")


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS）。"""
    await core_db.dispose_engine()
    monkeypatch.setattr(core_db, "get_engine", lambda: app_role_engine)
    transport = httpx.ASGITransport(app=create_app())
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        await core_db.dispose_engine()


@pytest.fixture(autouse=True)
async def _clean_outbox_rows(db_session: AsyncSession) -> None:
    """每测试后清场：本模块痕迹（SO-OB-% 对象、idem-ob-% 事件与幂等键、
    ob.% 事件类型、tenant-b-ob 租户及其直插 outbox）。"""
    yield
    await db_session.execute(
        text(
            "DELETE FROM event.outbox WHERE aggregate_id IN"
            " (SELECT event_id FROM event.events WHERE idempotency_key LIKE 'idem-ob-%')"
            " OR aggregate_id IN"
            " (SELECT object_id FROM master.business_objects WHERE source_id LIKE 'SO-OB-%')"
            " OR tenant_id IN"
            " (SELECT tenant_id FROM platform.tenants WHERE slug = 'tenant-b-ob')"
        )
    )
    await db_session.execute(
        text("DELETE FROM event.events WHERE idempotency_key LIKE 'idem-ob-%'")
    )
    await db_session.execute(
        text("DELETE FROM platform.idempotency_keys WHERE key LIKE 'idem-ob-%'")
    )
    await db_session.execute(
        text("DELETE FROM master.business_objects WHERE source_id LIKE 'SO-OB-%'")
    )
    await db_session.execute(
        text(
            "DELETE FROM platform.tenant_usage_daily WHERE tenant_id IN"
            " (SELECT tenant_id FROM platform.tenants WHERE slug = 'tenant-b-ob')"
        )
    )
    await db_session.execute(
        text("DELETE FROM platform.tenants WHERE slug = 'tenant-b-ob'")
    )
    await db_session.commit()
    reset_tenant_cache()


# ---- 造数与查询辅助 ----


async def _default_tenant_id(db_session: AsyncSession) -> UUID:
    return (
        await db_session.execute(
            text("SELECT tenant_id FROM platform.tenants WHERE slug = 'default'")
        )
    ).scalar_one()


async def _create_objects(client: httpx.AsyncClient, count: int) -> list[str]:
    ids: list[str] = []
    for seq in range(1, count + 1):
        resp = await client.post(
            OBJECTS,
            json={
                "object_type": "ORDER",
                "owner_domain": "sales",
                "source_system": "erp",
                "source_id": f"SO-OB-{seq:04d}",
                "attributes": {"seq": seq},
            },
            headers=KEY_HEADERS,
        )
        assert resp.status_code == 201, resp.text
        ids.append(resp.json()["object_id"])
    return ids


async def _ingest_events(
    client: httpx.AsyncClient, object_id: str, count: int
) -> None:
    events: list[dict[str, Any]] = [
        {
            "event_type": "ob.test.created",
            "object_id": object_id,
            "source_system": "agent-hub",
            "occurred_at": f"2026-09-14T09:00:{seq:02d}Z",
            "actor_type": "AI",
            "actor_id": "agent:test",
            "data": {"seq": seq},
        }
        for seq in range(1, count + 1)
    ]
    resp = await client.post(
        f"{EVENTS}/batch",
        json={"events": events},
        headers={**KEY_HEADERS, "Idempotency-Key": f"idem-ob-{uuid4()}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["accepted"] == count, resp.text


async def _outbox_rows(
    db_session: AsyncSession, tenant_id: UUID
) -> list[dict[str, Any]]:
    """本模块造出的 outbox 行（按 aggregate 关联 SO-OB-% 对象与 idem-ob-% 事件）。"""
    return [
        dict(row)
        for row in (
            await db_session.execute(
                text(
                    "SELECT outbox_id, event_type, status, retry_count, available_at, published_at"
                    " FROM event.outbox"
                    " WHERE (tenant_id = :t AND event_type LIKE 'ob.%')"
                    " OR (tenant_id = :t AND event_type = 'OBJECT_UPSERT'"
                    "  AND aggregate_id IN (SELECT object_id FROM master.business_objects"
                    "  WHERE source_id LIKE 'SO-OB-%'))"
                    " ORDER BY outbox_id"
                ),
                {"t": tenant_id},
            )
        ).mappings()
    ]


async def _reset_available_at(db_session: AsyncSession, tenant_id: UUID) -> None:
    """migrator 手动把 PENDING 行 available_at 归 now()（驱动下一轮重投）。"""
    await db_session.execute(
        text(
            "UPDATE event.outbox SET available_at = now()"
            " WHERE tenant_id = :t AND status = 'PENDING'"
        ),
        {"t": tenant_id},
    )
    await db_session.commit()


# ---- 1. API 造数 → 一轮 dispatch 全 PUBLISHED ----


async def test_dispatch_publishes_all(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    app_role_engine: AsyncEngine,
) -> None:
    tenant_id = await _default_tenant_id(db_session)
    object_ids = await _create_objects(client, 1)
    await _ingest_events(client, object_ids[0], 3)

    rows = await _outbox_rows(db_session, tenant_id)
    assert len(rows) == 4  # 1 OBJECT_UPSERT + 3 事件
    assert {r["status"] for r in rows} == {"PENDING"}
    assert [r["event_type"] for r in rows].count("OBJECT_UPSERT") == 1

    recorder = RecordingSubscriber()
    stats = await dispatch_batch(
        app_role_engine, tenant_id, [LoggingSubscriber(), recorder]
    )
    assert stats == {"published": 4, "retried": 0, "failed": 0}
    assert len(recorder.messages) == 4

    rows = await _outbox_rows(db_session, tenant_id)
    assert {r["status"] for r in rows} == {"PUBLISHED"}
    assert all(r["published_at"] is not None for r in rows)

    # 空转一轮：无 PENDING 可取 → stats 全 0，不误报
    idle = await dispatch_batch(app_role_engine, tenant_id, [recorder])
    assert idle == {"published": 0, "retried": 0, "failed": 0}
    assert len(recorder.messages) == 4


# ---- 2. nack 重投：retry_count 递增至 8 → FAILED ----


async def test_retry_then_failed_after_max_retries(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    app_role_engine: AsyncEngine,
) -> None:
    tenant_id = await _default_tenant_id(db_session)
    object_ids = await _create_objects(client, 1)
    await _ingest_events(client, object_ids[0], 2)

    stats = await dispatch_batch(app_role_engine, tenant_id, [BrokenSubscriber()])
    assert stats == {"published": 0, "retried": 3, "failed": 0}

    rows = await _outbox_rows(db_session, tenant_id)
    now = datetime.now(UTC)
    assert {r["status"] for r in rows} == {"PENDING"}
    assert {r["retry_count"] for r in rows} == {1}
    assert all(r["available_at"] > now for r in rows)

    # 第 2~8 轮：手动归零 available_at 后重投，retry_count 逐轮 +1，
    # 第 8 轮（retry_count == outbox_max_retries）转 FAILED
    for expected_retry in range(2, 9):
        await _reset_available_at(db_session, tenant_id)
        stats = await dispatch_batch(app_role_engine, tenant_id, [BrokenSubscriber()])
        rows = await _outbox_rows(db_session, tenant_id)
        assert {r["retry_count"] for r in rows} == {expected_retry}, (
            f"round {expected_retry}: {[dict(r) for r in rows]}"
        )
        if expected_retry < 8:
            assert stats["retried"] == 3
            assert {r["status"] for r in rows} == {"PENDING"}
        else:
            assert stats == {"published": 0, "retried": 0, "failed": 3}
            assert {r["status"] for r in rows} == {"FAILED"}

    # FAILED 不再被拾取
    await _reset_available_at(db_session, tenant_id)
    stats = await dispatch_batch(app_role_engine, tenant_id, [BrokenSubscriber()])
    assert stats == {"published": 0, "retried": 0, "failed": 0}


# ---- 3. 指数退避数列：第 n 轮后 available_at - now ≈ 2^n * base_s ----


async def test_backoff_sequence(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    app_role_engine: AsyncEngine,
) -> None:
    tenant_id = await _default_tenant_id(db_session)
    object_ids = await _create_objects(client, 1)
    await _ingest_events(client, object_ids[0], 1)

    for retry_n in (1, 2, 3):
        if retry_n > 1:
            await _reset_available_at(db_session, tenant_id)
        await dispatch_batch(app_role_engine, tenant_id, [BrokenSubscriber()])
        rows = await _outbox_rows(db_session, tenant_id)
        expected = (2**retry_n) * BACKOFF_BASE_S
        for row in rows:
            delta = (row["available_at"] - datetime.now(UTC)).total_seconds()
            assert abs(delta - expected) <= 1.0, (
                f"retry {retry_n}: delta={delta:.3f}s expected≈{expected}s"
            )


# ---- 4. 单租户异常隔离 ----


async def test_tenant_isolation_on_subscriber_failure(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    app_role_engine: AsyncEngine,
) -> None:
    tenant_a = await _default_tenant_id(db_session)
    object_ids = await _create_objects(client, 1)
    await _ingest_events(client, object_ids[0], 1)  # tenant-a: 2 行 PENDING

    # tenant-b：直插租户 + 2 行 outbox（绕 API，migrator 绕 RLS）
    tenant_b = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO platform.tenants (tenant_id, slug, name, status)"
            " VALUES (:t, 'tenant-b-ob', '租户B-OB', 'ACTIVE')"
        ),
        {"t": tenant_b},
    )
    for seq in (1, 2):
        await db_session.execute(
            text(
                "INSERT INTO event.outbox"
                " (tenant_id, aggregate_type, aggregate_id, event_type, payload)"
                " VALUES (:t, 'EVENT', :agg, 'ob.tenantb.evt', CAST(:payload AS jsonb))"
            ),
            {"t": tenant_b, "agg": uuid4(), "payload": f'{{"seq": {seq}}}'},
        )
    await db_session.commit()

    # 调度清单：双租户均 ACTIVE（先重置 30s 缓存；edp_app 可直查控制面表）
    reset_tenant_cache()
    factory = async_sessionmaker(app_role_engine, expire_on_commit=False)
    async with factory() as sess:
        tenant_ids = await active_tenant_ids(sess)
    assert {tenant_a, tenant_b} <= set(tenant_ids)

    # 模拟 run_forever 单轮：逐租户 dispatch（订阅者仅对 tenant-a 抛错）
    broken = BrokenForTenantSubscriber(tenant_a)
    stats_a = await dispatch_batch(app_role_engine, tenant_a, [broken])
    stats_b = await dispatch_batch(app_role_engine, tenant_b, [broken])
    assert stats_a == {"published": 0, "retried": 2, "failed": 0}
    assert stats_b == {"published": 2, "retried": 0, "failed": 0}

    rows_a = await _outbox_rows(db_session, tenant_a)
    assert {r["status"] for r in rows_a} == {"PENDING"}
    assert {r["retry_count"] for r in rows_a} == {1}
    rows_b = [
        dict(r)
        for r in (
            await db_session.execute(
                text(
                    "SELECT status, retry_count FROM event.outbox"
                    " WHERE tenant_id = :t"
                ),
                {"t": tenant_b},
            )
        ).mappings()
    ]
    assert {r["status"] for r in rows_b} == {"PUBLISHED"}
    assert {r["retry_count"] for r in rows_b} == {0}


# ---- 5. SKIP LOCKED：并发双 dispatch 同租户不双发 ----


async def test_skip_locked_no_double_dispatch(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    app_role_engine: AsyncEngine,
) -> None:
    tenant_id = await _default_tenant_id(db_session)
    object_ids = await _create_objects(client, 1)
    await _ingest_events(client, object_ids[0], 4)  # 1 + 4 = 5 行 PENDING

    recorder = RecordingSubscriber()
    stats1, stats2 = await asyncio.gather(
        dispatch_batch(app_role_engine, tenant_id, [recorder]),
        dispatch_batch(app_role_engine, tenant_id, [recorder]),
    )
    total = stats1["published"] + stats2["published"]
    assert total == 5, (stats1, stats2)  # 恰为存量数
    assert stats1["retried"] + stats2["retried"] == 0

    # 每条消息恰投递一次（同一 outbox_id 不重复出现）
    assert len(recorder.messages) == 5
    assert len({m.outbox_id for m in recorder.messages}) == 5

    rows = await _outbox_rows(db_session, tenant_id)
    assert {r["status"] for r in rows} == {"PUBLISHED"}


# ---- Subscriber 协议结构自检（进程内总线数据契约） ----


def test_subscriber_protocol_shape() -> None:
    msg = OutboxMessage(
        outbox_id=1,
        tenant_id=uuid4(),
        aggregate_type="EVENT",
        aggregate_id=uuid4(),
        event_type="ob.test.created",
        payload={"k": 1},
    )
    assert issubclass(LoggingSubscriber, object)
    recorder: Subscriber = RecordingSubscriber()
    assert hasattr(recorder, "on_event")
    assert msg.payload == {"k": 1}
