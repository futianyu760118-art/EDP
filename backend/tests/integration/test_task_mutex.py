"""W6 T3 任务互斥集成测试（Redis B 轻量项 / redis-evaluation §4）：

- 同 task_type 触发即互斥：首个任务执行期内第二次 POST → 409 CONFLICT
  （复用既有码不扩错误码表；extra 附 task_type/current_task_hint）、不登记
  第二行；首个任务照常终态；
- 不同 task_type 互不阻塞：recheck 持锁执行期内 reindex / adapter sync
  照常 202（advisory lock 键按 task_type——adapter 另按 ref_name）；
- 任务完成后可再触发（执行体 finally 释放锁——无 RUNNING 行亦无锁残留）；
- adapter sync 入口接锁（同一适配器互斥 + 不同适配器并行）+ FAILED stats
  置空 {}（W5-21-a「FAILED 即无最终计数」）；
- 内部写事件计量豁免（W5-09）：checksum 抽检失配 → quality.checksum_
  failed 事件经 ingest internal=True 落库而 usage 计量不动（服务直调路径
  ——api_calls/events_in 前后相等；外部正常 ingest 照常计量对照）。

造数：互斥用例 monkeypatch 段执行/同步执行拖住后台（窗口内触发第二请求
确定性 409）；计量豁免用例 demo seed + migrator 直改 checksum 造失配，
服务直调 build_report。断言经 migrator db_session 直查；轮询到终态后
drain 后台任务再收尾（防清理与执行体竞态，模式同 test_quality_tasks）。

清场：purge 业务数据（含 quality.* 事件/outbox/usage/幂等键）+ ops.tasks
行 + TASK/quality 事件审计行（同 test_quality_tasks 清场口径）。
"""

import asyncio
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.core.security.principal import Principal
from edp_api.main import create_app
from edp_api.modules.audit.aspect import install_audit_aspect
from edp_api.modules.demo import service as demo_service
from edp_api.modules.events import service as events_service
from edp_api.modules.events.schemas import EventIn
from edp_api.modules.ingest import service as ingest_service
from edp_api.modules.quality import service as quality_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

RECHECKS = "/api/v1/admin/quality/rechecks"
TASKS = "/api/v1/admin/quality/tasks"
REINDEX = "/api/v1/admin/evidence/reindex"
ADAPTERS = "/api/v1/admin/adapters"
LOGIN = "/api/v1/auth/login"
SEED_PASSWORD = "Admin@123!"

# 拖住后台执行的窗口（秒）——窗口内第二请求确定性命中互斥分支
SLOW_WINDOW_S = 1.0


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS），任务路由随
    create_app 装配（后台执行体经 core_db.get_engine() 取同一引擎）。"""
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
    """任务行写依赖切面落审计（TASK_CREATE/TASK_UPDATE 派生）——与 CLI
    同一装配。"""
    install_audit_aspect()


@pytest.fixture
async def seeded(
    app_role_engine: AsyncEngine, default_tenant_id: UUID
) -> None:
    """demo seed（make seed-demo 等价；确定性数据集——P0/P1 结果证据 4 条）。"""
    await demo_service.seed(app_role_engine, default_tenant_id)


@pytest.fixture(autouse=True)
async def _clean_task_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> AsyncIterator[None]:
    """每测试后清场：drain 后台执行体（防清理竞态）→ purge 业务行（含
    quality.* 事件/outbox/usage/幂等键）+ ops.tasks 行 + TASK/quality 事件
    审计行（口径同 test_quality_tasks）。"""
    yield
    await _drain_background()
    await demo_service.purge_tenant_business_data(db_session, default_tenant_id)
    await db_session.execute(
        text("DELETE FROM ops.tasks WHERE tenant_id = :t"),
        {"t": default_tenant_id},
    )
    await db_session.execute(
        text(
            "DELETE FROM platform.audit_logs WHERE tenant_id = :t"
            " AND (actor_id LIKE 'adapter:%'"
            "       OR detail->>'event_type' LIKE 'quality.%'"
            "       OR (resource_type = 'tasks' AND action LIKE 'TASK_%'))"
        ),
        {"t": default_tenant_id},
    )
    await db_session.commit()


async def _login(client: httpx.AsyncClient, username: str) -> dict[str, str]:
    resp = await client.post(LOGIN, json={"username": username, "password": SEED_PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _drain_background(timeout_s: float = 10.0) -> None:
    """等待后台执行体收尾（当前任务之外全空即收齐；带超时兜底）。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if not pending:
            return
        await asyncio.wait(pending, timeout=0.5)


async def _poll_terminal(
    client: httpx.AsyncClient, headers: dict[str, str], task_id: str
) -> dict:
    """轮询任务到终态（SUCCEEDED/FAILED；≤10s——quality tasks 端点对三类
    task_type 同形）。"""
    deadline = time.monotonic() + 10.0
    while True:
        resp = await client.get(f"{TASKS}/{task_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        if body["status"] in ("SUCCEEDED", "FAILED"):
            return body
        assert time.monotonic() < deadline, f"任务未在 10s 内到达终态：{body}"
        await asyncio.sleep(0.2)


async def _poll_sync_finished(
    client: httpx.AsyncClient, headers: dict[str, str], sync_id: str
) -> dict[str, Any]:
    """轮询 adapter status 直至指定 sync 任务完成（模式同 test_adapters_api）。"""
    deadline = time.monotonic() + 10.0
    while True:
        resp = await client.get(f"{ADAPTERS}/erp/status", headers=headers)
        assert resp.status_code == 200, resp.text
        last_sync = resp.json()["last_sync"]
        if last_sync and last_sync["sync_id"] == sync_id and last_sync["finished_at"]:
            return last_sync
        if time.monotonic() > deadline:
            pytest.fail(f"同步任务 {sync_id} 未在 10s 内完成：{last_sync}")
        await asyncio.sleep(0.2)


def _slow_segment(monkeypatch: pytest.MonkeyPatch) -> None:
    """拖住 recheck 段执行（每段 SLOW_WINDOW_S）——触发即互斥窗口。"""

    async def _slow(sess, principal, segment, stats, logs):
        await asyncio.sleep(SLOW_WINDOW_S)
        stats[segment] = {"slow": True}

    monkeypatch.setattr(quality_service, "_run_segment", _slow)


# ---- 1. 同 task_type 触发即互斥：执行期内第二请求 409、不登记行 ----


async def test_recheck_same_type_second_trigger_409(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _slow_segment(monkeypatch)

    admin = await _login(client, "admin")
    first = await client.post(RECHECKS, json={"scope": "ALL"}, headers=admin)
    assert first.status_code == 202, first.text
    first_id = first.json()["task_id"]

    second = await client.post(RECHECKS, json={"scope": "CHECKSUM"}, headers=admin)
    assert second.status_code == 409, second.text
    error = second.json()["error"]
    # 复用既有 CONFLICT 码（不扩 13 错误码表）——message/extra 区分任务冲突
    assert error["code"] == "CONFLICT"
    assert "quality_recheck" in error["message"]
    assert error["task_type"] == "quality_recheck"
    assert error["current_task_hint"] == first_id

    # 409 方不登记第二行（advisory lock 先于行创建）
    running = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM ops.tasks WHERE tenant_id = :t"
                " AND task_type = 'quality_recheck'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one()
    assert running == 1

    # 首个任务照常执行到终态（被 409 方不干扰）
    task = await _poll_terminal(client, admin, first_id)
    assert task["status"] == "SUCCEEDED"
    await _drain_background()


# ---- 2. 不同 task_type 互不阻塞：recheck 持锁执行期内 reindex/sync 照常 202 ----


async def test_different_task_types_do_not_block(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _slow_segment(monkeypatch)

    async def _slow_sync(engine, tenant_id, adapter, mode, since=None):
        await asyncio.sleep(SLOW_WINDOW_S)
        return ingest_service.SyncStats(fetched=0)

    monkeypatch.setattr(ingest_service, "run_sync_per_record", _slow_sync)

    admin = await _login(client, "admin")
    recheck = await client.post(RECHECKS, json={"scope": "ORPHAN"}, headers=admin)
    assert recheck.status_code == 202, recheck.text

    reindex = await client.post(REINDEX, json={}, headers=admin)
    assert reindex.status_code == 202, reindex.text

    sync = await client.post(
        f"{ADAPTERS}/erp/sync", json={"mode": "full"}, headers=admin
    )
    assert sync.status_code == 202, sync.text

    # 三任务各自终态（键不同互不阻塞；recheck/reindex 真执行、sync 假慢成功）
    assert (await _poll_terminal(client, admin, recheck.json()["task_id"]))[
        "status"
    ] == "SUCCEEDED"
    assert (await _poll_terminal(client, admin, reindex.json()["task_id"]))[
        "status"
    ] == "SUCCEEDED"
    last_sync = await _poll_sync_finished(client, admin, sync.json()["sync_id"])
    assert last_sync["status"] == "SUCCEEDED"
    await _drain_background()


# ---- 3. 任务完成后可再触发（执行体 finally 释放锁） ----


async def test_retrigger_allowed_after_completion(
    client: httpx.AsyncClient,
) -> None:
    admin = await _login(client, "admin")
    first = await client.post(RECHECKS, json={"scope": "CHECKSUM"}, headers=admin)
    assert first.status_code == 202, first.text
    first_id = first.json()["task_id"]
    assert (await _poll_terminal(client, admin, first_id))["status"] == "SUCCEEDED"

    # 终态后锁已随执行体释放（无 RUNNING 行亦无锁残留）→ 再触发 202
    second = await client.post(RECHECKS, json={"scope": "CHECKSUM"}, headers=admin)
    assert second.status_code == 202, second.text
    assert second.json()["task_id"] != first_id
    assert (await _poll_terminal(client, admin, second.json()["task_id"]))[
        "status"
    ] == "SUCCEEDED"
    await _drain_background()


# ---- 4. adapter sync：同一适配器互斥（409）+ 不同适配器并行 + FAILED stats 置空 ----


async def test_sync_mutex_per_adapter_and_failed_stats_empty(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _slow_boom(engine, tenant_id, adapter, mode, since=None):
        await asyncio.sleep(SLOW_WINDOW_S)
        raise RuntimeError("boom")

    monkeypatch.setattr(ingest_service, "run_sync_per_record", _slow_boom)

    admin = await _login(client, "admin")
    first = await client.post(
        f"{ADAPTERS}/erp/sync", json={"mode": "full"}, headers=admin
    )
    assert first.status_code == 202, first.text
    first_id = first.json()["sync_id"]

    # 同一适配器（同 ref_name 键）执行期内再触发 → 409
    second = await client.post(
        f"{ADAPTERS}/erp/sync", json={"mode": "full"}, headers=admin
    )
    assert second.status_code == 409, second.text
    error = second.json()["error"]
    assert error["code"] == "CONFLICT"
    assert error["task_type"] == "adapter_sync"
    assert error["ref_name"] == "erp"
    assert error["current_task_hint"] == first_id

    # 不同适配器（不同 ref_name 键）不阻塞
    other = await client.post(
        f"{ADAPTERS}/plm-demo/sync", json={"mode": "full"}, headers=admin
    )
    assert other.status_code == 202, other.text

    # W5-21-a：整批异常 → FAILED 且 stats 置空 {}（API 面 {} → None）
    last_sync = await _poll_sync_finished(client, admin, first_id)
    assert last_sync["status"] == "FAILED"
    assert last_sync["stats"] is None
    row = (
        await db_session.execute(
            text(
                "SELECT status, stats FROM ops.tasks WHERE task_id = :id"
            ),
            {"id": UUID(first_id)},
        )
    ).one()
    assert row.status == "FAILED"
    assert row.stats == {}
    await _drain_background()

    # 锁已释放 → 同一适配器可再触发
    retrigger = await client.post(
        f"{ADAPTERS}/erp/sync", json={"mode": "full"}, headers=admin
    )
    assert retrigger.status_code == 202, retrigger.text
    assert (await _poll_sync_finished(client, admin, retrigger.json()["sync_id"]))[
        "status"
    ] == "FAILED"
    await _drain_background()


# ---- 5. W5-09 内部计量豁免：checksum 失配事件落库而 usage 计量不动 ----


async def test_checksum_failure_internal_event_exempt_from_usage(
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    seeded: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """服务直调抽检（不经 HTTP——api_calls 每请求 +1 属请求侧计量，与本
    豁免无关）：内部事件（internal=True）豁免 usage 计量 upsert，事件/
    审计/outbox 照旧；对照外部 ingest（internal 缺省）events_in 照常累加。"""
    await core_db.dispose_engine()
    monkeypatch.setattr(core_db, "get_engine", lambda: app_role_engine)
    try:
        # 篡改全部 P0/P1 结果证据 checksum（migrator 直改绕 RLS/审计）
        tampered = (
            (
                await db_session.execute(
                    text(
                        "UPDATE evidence.records SET checksum = 'sha256:tampered'"
                        " WHERE event_id IN (SELECT event_id FROM event.events"
                        "                    WHERE risk_level IN ('P0', 'P1'))"
                        " RETURNING evidence_id"
                    )
                )
            )
            .scalars()
            .all()
        )
        await db_session.commit()
        assert tampered, "seed 应含 P0/P1 结果证据"

        async def _usage() -> tuple[int, int]:
            row = (
                await db_session.execute(
                    text(
                        "SELECT events_in, api_calls FROM"
                        " platform.tenant_usage_daily"
                        " WHERE tenant_id = :t AND usage_date = current_date"
                    ),
                    {"t": default_tenant_id},
                )
            ).one()
            return (int(row.events_in), int(row.api_calls))

        principal = Principal(
            id="user:mutex-test", kind="HUMAN", tenant_id=default_tenant_id
        )
        factory = core_db.get_session_local()

        before = await _usage()
        async with factory() as sess:
            await core_db.bind_tenant(sess, default_tenant_id)
            report = await quality_service.build_report(
                sess, principal, report_date="2026-09-22"
            )
            await sess.commit()

        # 抽检全失配 + checksum_failed 事件照常落库（豁免的是计量不是事件）
        assert report.checksum_sampling.sampled == len(tampered)
        assert report.checksum_sampling.failed == len(tampered)
        events = (
            await db_session.execute(
                text(
                    "SELECT count(*) FROM event.events WHERE tenant_id = :t"
                    " AND event_type = 'quality.checksum_failed'"
                ),
                {"t": default_tenant_id},
            )
        ).scalar_one()
        assert events == len(tampered)

        # 计量豁免（W5-09）：内部写入不占用量口径——events_in/api_calls 均不动
        after = await _usage()
        assert after == before

        # 对照：外部正常 ingest（internal 缺省）照常计量 events_in +1
        anchor = (
            await db_session.execute(
                text(
                    "SELECT object_id FROM master.business_objects"
                    " WHERE tenant_id = :t ORDER BY object_id LIMIT 1"
                ),
                {"t": default_tenant_id},
            )
        ).scalar_one()
        async with factory() as sess:
            await core_db.bind_tenant(sess, default_tenant_id)
            await events_service.ingest_batch(
                sess,
                principal,
                "mutex-external-check",
                [
                    EventIn(
                        event_type="ORDER_SNAPSHOT",
                        object_id=anchor,
                        source_system="erp",
                        occurred_at=datetime.now(UTC),
                        actor_type="SERVICE",
                        actor_id="adapter:erp",
                        data={"via": "mutex-test"},
                    )
                ],
            )
            await sess.commit()
        final = await _usage()
        assert final[0] == after[0] + 1  # events_in 照常累加
    finally:
        await core_db.dispose_engine()
