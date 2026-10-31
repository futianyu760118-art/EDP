"""T6 证据重索引集成测试（W3-04 收口）：POST /admin/evidence/reindex 202 异步
→ 全量重算 → 失配统计 + quality.reindex_mismatch 事件 + 原 checksum 不回写 /
无篡改零失配无事件 / 任务轨道复用 quality tasks 端点（跨租户 404）/ 鉴权
（ANALYST 403 无 quality:run）/ FAILED 路径（重算抛错 → FAILED + failed 事件）。

造数：demo_service.seed（同 test_quality_tasks，确定性数据集）；篡改 = migrator
直改一条 evidence snapshot（绕 RLS/审计——模拟外部库内篡改），断言经
migrator db_session 直查。后台执行体走独立会话（get_session_local → 测试
引擎），轮询（≤10s）到终态后 drain 后台任务再收尾（防清理/引擎销毁竞态）。

清场：purge 业务数据（含 quality.* 事件/outbox/usage/幂等键）+ ops.tasks 行
+ seed/TASK/quality 事件审计行 + tenant-b 痕迹（migrator 直造）——同
test_quality_tasks 口径。
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from uuid import UUID

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.core.security.password import hash_password
from edp_api.main import create_app
from edp_api.modules.audit.aspect import install_audit_aspect
from edp_api.modules.demo import service as demo_service
from edp_api.modules.evidence import service as evidence_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

REINDEX = "/api/v1/admin/evidence/reindex"
TASKS = "/api/v1/admin/quality/tasks"
LOGIN = "/api/v1/auth/login"
SEED_PASSWORD = "Admin@123!"

B_SLUG = "tenant-b"
B_PASSWORD = "TenantB@123!"
B_USERNAME = "member1b"


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS），evidence
    admin/quality 路由随 create_app 装配。"""
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
    """seed/任务行写依赖切面落审计（TASK_CREATE/TASK_UPDATE 派生）——
    与 CLI 同一装配。"""
    install_audit_aspect()


@pytest.fixture
async def seeded(
    app_role_engine: AsyncEngine, default_tenant_id: UUID
) -> None:
    """demo seed（make seed-demo 等价；确定性数据集）。"""
    await demo_service.seed(app_role_engine, default_tenant_id)


@pytest.fixture
async def tenant_b(db_session: AsyncSession) -> None:
    """tenant-b + MANAGER 用户（MANAGER 持 quality:read；migrator 直造绕
    RLS，同 test_quality_tasks 造法）——跨租户 404 用例的对侧主体。"""
    tenant_id, user_id, member_id = (UUID(int=i) for i in (9001, 9002, 9003))
    await db_session.execute(
        text(
            "INSERT INTO platform.tenants (tenant_id, slug, name, status)"
            " VALUES (:t, 'tenant-b', '租户B', 'ACTIVE')"
        ),
        {"t": tenant_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO platform.users"
            " (user_id, tenant_id, username, email, password_hash, display_name,"
            "  principal_type, is_platform_admin, status)"
            " VALUES (:u, :t, 'member1b', 'member1b@tenant-b.local', :pw,"
            "         'B租户经理', 'HUMAN', FALSE, 'ACTIVE')"
        ),
        {"u": user_id, "t": tenant_id, "pw": hash_password(B_PASSWORD)},
    )
    await db_session.execute(
        text(
            "INSERT INTO platform.tenant_members"
            " (member_id, tenant_id, user_id, member_roles, status)"
            " VALUES (:m, :t, :u, ARRAY['MANAGER'], 'ACTIVE')"
        ),
        {"m": member_id, "t": tenant_id, "u": user_id},
    )
    await db_session.commit()


@pytest.fixture(autouse=True)
async def _clean_reindex_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> AsyncIterator[None]:
    """每测试后清场：先 drain 后台执行体（防清理与执行体竞态——测试体内
    已各自 drain，此处兜底），再删业务行（purge 逆依赖序含 quality.*
    事件/outbox/usage/幂等键）+ ops.tasks 行 + seed/TASK/quality 事件审计行
    + tenant-b 痕迹（同 test_quality_tasks 口径）。"""
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
    b_ids = "SELECT tenant_id FROM platform.tenants WHERE slug = 'tenant-b'"
    await db_session.execute(
        text(
            "DELETE FROM platform.tenant_usage_daily WHERE tenant_id IN (" + b_ids + ")"
        )
    )
    await db_session.execute(
        text("DELETE FROM platform.tenant_members WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM platform.users WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(text("DELETE FROM platform.tenants WHERE slug = 'tenant-b'"))
    await db_session.commit()


async def _login(
    client: httpx.AsyncClient,
    username: str,
    *,
    password: str = SEED_PASSWORD,
    tenant_slug: str | None = None,
) -> dict[str, str]:
    body = {"username": username, "password": password}
    if tenant_slug is not None:
        body["tenant_slug"] = tenant_slug
    resp = await client.post(LOGIN, json=body)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _drain_background(timeout_s: float = 10.0) -> None:
    """等待后台 reindex 执行体收尾（当前任务之外全空即收齐；带超时兜底）。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if not pending:
            return
        await asyncio.wait(pending, timeout=0.5)


async def _poll_terminal(
    client: httpx.AsyncClient, headers: dict[str, str], task_id: str
) -> dict:
    """轮询任务到终态（SUCCEEDED/FAILED；≤10s——复用 T4 quality tasks 端点）。"""
    deadline = time.monotonic() + 10.0
    while True:
        resp = await client.get(f"{TASKS}/{task_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        if body["status"] in ("SUCCEEDED", "FAILED"):
            return body
        assert time.monotonic() < deadline, f"任务未在 10s 内到达终态：{body}"
        await asyncio.sleep(0.2)


async def _trigger(
    client: httpx.AsyncClient, headers: dict[str, str], json: dict | None = None
) -> str:
    """POST /admin/evidence/reindex → 202 → task_id（缺省 body = scope ALL）。"""
    resp = await client.post(REINDEX, json=json if json is not None else {}, headers=headers)
    assert resp.status_code == 202, resp.text
    accepted = resp.json()
    assert set(accepted) == {"task_id", "status"}
    assert accepted["status"] == "RUNNING"
    return accepted["task_id"]


async def _event_data(
    db_session: AsyncSession, tenant_id: UUID, event_type: str
) -> dict | None:
    return (
        await db_session.execute(
            text(
                "SELECT data FROM event.events WHERE tenant_id = :t"
                " AND event_type = :et"
            ),
            {"t": tenant_id, "et": event_type},
        )
    ).scalar_one_or_none()


# ---- 1. 篡改探测：全量重算 → mismatched + 事件 + 原 checksum 不回写 ----


async def test_reindex_detects_tampering_and_preserves_checksum(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    seeded: None,
) -> None:
    # 外部篡改一条证据 snapshot（migrator 直改 DB——绕 RLS/审计）
    tampered = (
        await db_session.execute(
            text(
                "UPDATE evidence.records"
                " SET snapshot = snapshot || '{\"tampered\": true}'::jsonb"
                " WHERE evidence_id = ("
                "   SELECT evidence_id FROM evidence.records WHERE tenant_id = :t"
                "   ORDER BY captured_at DESC, evidence_id DESC LIMIT 1)"
                " RETURNING evidence_id, checksum"
            ),
            {"t": default_tenant_id},
        )
    ).one()
    tampered_id, original_checksum = tampered.evidence_id, tampered.checksum
    await db_session.commit()  # 提交篡改——后台执行体独立会话须可见（READ COMMITTED）
    total_evidence = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM evidence.records WHERE tenant_id = :t"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one()

    admin = await _login(client, "admin")  # ADMIN（quality:run）
    task_id = await _trigger(client, admin)
    task = await _poll_terminal(client, admin, task_id)
    await _drain_background()

    # 任务轨道（T4 端点复用）：task_type/scope/终态/finished_at
    assert task["task_type"] == "evidence_reindex"
    assert task["scope"] == "ALL"
    assert task["status"] == "SUCCEEDED"
    assert task["finished_at"] is not None

    # stats：total（全量行数）= rechecked（实际重算）且 mismatched ≥ 1
    assert set(task["stats"]) == {"total", "rechecked", "mismatched"}
    assert task["stats"]["total"] == total_evidence
    assert task["stats"]["rechecked"] == task["stats"]["total"]
    assert task["stats"]["mismatched"] >= 1

    # logs：进度行（{ts, level, message}）
    logs = task["logs"]
    assert logs and all(set(line) == {"ts", "level", "message"} for line in logs)
    messages = [line["message"] for line in logs]
    assert any("任务启动" in m for m in messages)
    assert any("进度" in m for m in messages)
    assert any("任务完成" in m for m in messages)

    # 失配事件：quality.reindex_mismatch 聚合一条，含篡改 evidence_id + 期望/实际
    mismatch_event = await _event_data(
        db_session, default_tenant_id, "quality.reindex_mismatch"
    )
    assert mismatch_event is not None
    assert mismatch_event["task_id"] == task_id
    assert mismatch_event["mismatched"] == task["stats"]["mismatched"]
    entries = {item["evidence_id"]: item for item in mismatch_event["mismatches"]}
    entry = entries[str(tampered_id)]
    assert entry["expected"] == original_checksum
    assert entry["actual"] != original_checksum

    # 完成：quality.reindex_succeeded 携带 task_id/scope/stats
    done_event = await _event_data(
        db_session, default_tenant_id, "quality.reindex_succeeded"
    )
    assert done_event is not None
    assert done_event["task_id"] == task_id
    assert done_event["scope"] == "ALL"
    assert done_event["stats"]["mismatched"] >= 1

    # **原 checksum 不回写**（checksum 语义不变）：篡改行存储值仍为原值
    stored = (
        await db_session.execute(
            text("SELECT checksum FROM evidence.records WHERE evidence_id = :id"),
            {"id": tampered_id},
        )
    ).scalar_one()
    assert stored == original_checksum


# ---- 2. 无篡改：mismatched=0、无失配事件；任务轨道可查 + 跨租户 404 ----


async def test_reindex_clean_run_no_mismatch_and_task_track(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    seeded: None,
    tenant_b: None,
) -> None:
    admin = await _login(client, "admin")
    task_id = await _trigger(client, admin, {"scope": "ALL"})
    task = await _poll_terminal(client, admin, task_id)
    await _drain_background()

    assert task["status"] == "SUCCEEDED"
    assert task["stats"]["mismatched"] == 0
    assert task["stats"]["rechecked"] == task["stats"]["total"]
    assert task["stats"]["total"] > 0  # seed 证据非空（快照 + 结果证据）

    # 无失配 → 无 mismatch 事件（成功完成事件仍在）
    assert (
        await _event_data(db_session, default_tenant_id, "quality.reindex_mismatch")
        is None
    )
    assert (
        await _event_data(db_session, default_tenant_id, "quality.reindex_succeeded")
        is not None
    )

    # 任务轨道（quality:read，T4 端点）：触发者 200；跨租户 404（RLS 不泄露存在性）
    own = await client.get(f"{TASKS}/{task_id}", headers=admin)
    assert own.status_code == 200, own.text
    assert own.json()["status"] == "SUCCEEDED"
    denied = await client.get(
        f"{TASKS}/{task_id}",
        headers=await _login(
            client, B_USERNAME, password=B_PASSWORD, tenant_slug=B_SLUG
        ),
    )
    assert denied.status_code == 404, denied.text
    assert denied.json()["error"]["code"] == "NOT_FOUND"


# ---- 3. 鉴权：ANALYST 触发 403（quality:run 无 ANALYST）且不登记任务 ----


async def test_analyst_cannot_trigger_reindex(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    seeded: None,
) -> None:
    analyst = await _login(client, "analyst1")
    denied = await client.post(REINDEX, json={}, headers=analyst)
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "FORBIDDEN"
    assert (
        await db_session.execute(
            text(
                "SELECT count(*) FROM ops.tasks WHERE tenant_id = :t"
                " AND task_type = 'evidence_reindex'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one() == 0


# ---- 4. FAILED 路径：重算抛错 → FAILED + 错误日志行 + failed 事件 ----


async def test_reindex_failure_marks_failed_and_writes_event(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    seeded: None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _boom(payload: dict) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(evidence_service, "compute_checksum", _boom)

    admin = await _login(client, "admin")
    task_id = await _trigger(client, admin)
    task = await _poll_terminal(client, admin, task_id)
    await _drain_background()

    assert task["status"] == "FAILED"
    assert task["finished_at"] is not None
    # 首批重算即抛错：stats 仅 total 计入（progress 行未落）
    assert task["stats"]["total"] > 0
    assert task["stats"]["rechecked"] == 0
    error_lines = [line for line in task["logs"] if line["level"] == "ERROR"]
    assert error_lines and "boom" in error_lines[-1]["message"]

    failed_event = await _event_data(
        db_session, default_tenant_id, "quality.reindex_failed"
    )
    assert failed_event is not None
    assert failed_event["task_id"] == task_id
    assert "boom" in failed_event["error"]

    # 失败任务不写 mismatch/succeeded 事件
    assert (
        await _event_data(db_session, default_tenant_id, "quality.reindex_mismatch")
        is None
    )
    assert (
        await _event_data(db_session, default_tenant_id, "quality.reindex_succeeded")
        is None
    )
    # 事件通道尽力语义留痕：终态已落库，仅告警日志（无未捕获异常冒泡）
    assert any(
        record.name == "edp_api.modules.evidence.service" and record.levelno >= logging.ERROR
        for record in caplog.records
    )
