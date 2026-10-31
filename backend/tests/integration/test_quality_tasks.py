"""T4 质量任务轨道集成测试（EDP-030 下半）：rechecks 202 异步 → tasks 轮询
终态 / scope 段选择 / FAILED 路径与质量事件 / 跨租户 404 / 鉴权（ADMIN
触发、ANALYST 403 无 quality:run）/ 审计 TASK_CREATE 派生 / T4 评审修复
回归（后台先于请求 commit 启动的可见性有界重试 / 回滚 deadline 语义 /
完成事件移出终态事务——事件通道异常不改判 FAILED）。

造数：demo_service.seed（同 test_quality_api，确定性数据集——P0/P1 结果
证据 4 条）；断言经 migrator db_session 直查。后台执行体走独立会话
（get_session_local → 测试引擎），轮询（≤10s）到终态后 drain 后台任务
再收尾（防清理/引擎销毁与执行体竞态）。

清场：purge 业务数据（含 quality.* 事件/outbox/usage/幂等键）+ ops.tasks
行 + seed/TASK/quality 事件审计行 + tenant-b 痕迹（migrator 直造）。
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.core.security.password import hash_password
from edp_api.core.security.principal import Principal
from edp_api.main import create_app
from edp_api.modules.audit.aspect import install_audit_aspect
from edp_api.modules.demo import service as demo_service
from edp_api.modules.quality import service as quality_service
from edp_api.modules.quality.models import OpsTask
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

RECHECKS = "/api/v1/admin/quality/rechecks"
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
    RLS，同 test_tenant_isolation 造法）——跨租户 404 用例的对侧主体。"""
    tenant_id, user_id, member_id = (uuid4() for _ in range(3))
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
async def _clean_quality_task_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> AsyncIterator[None]:
    """每测试后清场：先 drain 后台执行体（防清理与执行体竞态——测试体内
    已各自 drain，此处兜底），再删业务行（purge 逆依赖序含 quality.*
    事件/outbox/usage/幂等键）+ ops.tasks 行 + seed/TASK/quality 事件审计行
    + tenant-b 痕迹。"""
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
    """等待后台 recheck 执行体收尾（当前任务之外全空即收齐；带超时兜底）。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if not pending:
            return
        await asyncio.wait(pending, timeout=0.5)


async def _poll_terminal(
    client: httpx.AsyncClient, headers: dict[str, str], task_id: str
) -> dict:
    """轮询任务到终态（SUCCEEDED/FAILED；≤10s，轮询间隙让出事件循环供
    后台执行体推进）。"""
    deadline = time.monotonic() + 10.0
    while True:
        resp = await client.get(f"{TASKS}/{task_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        if body["status"] in ("SUCCEEDED", "FAILED"):
            return body
        assert time.monotonic() < deadline, f"任务未在 10s 内到达终态：{body}"
        await asyncio.sleep(0.2)


async def _count(
    db_session: AsyncSession, tenant_id: UUID, sql: str, **params: object
) -> int:
    return (await db_session.execute(text(sql), {"t": tenant_id, **params})).scalar_one()


async def _trigger(
    client: httpx.AsyncClient, headers: dict[str, str], scope: str
) -> str:
    """触发重校验 → 202 → task_id（响应体恰好 {task_id, status:RUNNING}）。"""
    resp = await client.post(RECHECKS, json={"scope": scope}, headers=headers)
    assert resp.status_code == 202, resp.text
    accepted = resp.json()
    assert set(accepted) == {"task_id", "status"}
    assert accepted["status"] == "RUNNING"
    return accepted["task_id"]


# ---- 1. ALL：四段齐 + 终态 + 完成事件 + 审计 TASK_CREATE ----


async def test_recheck_all_runs_four_segments_and_succeeds(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    seeded: None,
) -> None:
    admin = await _login(client, "admin")  # ADMIN（quality:run）
    task_id = await _trigger(client, admin, "ALL")
    task = await _poll_terminal(client, admin, task_id)

    assert task["task_type"] == "quality_recheck"
    assert task["scope"] == "ALL"
    assert task["status"] == "SUCCEEDED"
    assert task["finished_at"] is not None
    assert task["started_at"]

    # stats 四段齐（段名键 + seed 口径精确值）
    assert set(task["stats"]) == {"reconciliation", "coverage", "orphans", "checksum"}
    assert task["stats"]["checksum"] == {"sampled": 4, "failed": 0}
    assert task["stats"]["orphans"] == {"event_orphans": 0, "evidence_orphans": 0}
    assert task["stats"]["coverage"]["overall_pct"] == 100.0

    # logs：形状对齐 mock（{ts, level, message}）+ 起止/关键计数行
    logs = task["logs"]
    assert logs, "logs 非空"
    assert all(set(line) == {"ts", "level", "message"} for line in logs)
    assert all(line["level"] in {"INFO", "WARN", "ERROR"} for line in logs)
    messages = [line["message"] for line in logs]
    assert any("任务启动" in m for m in messages)
    assert any("对账段完成" in m for m in messages)
    assert any("抽检段完成" in m for m in messages)
    assert any("任务完成" in m for m in messages)

    await _drain_background()

    # 完成事件：quality.recheck_succeeded 携带 task_id/scope/stats 摘要
    event_data = (
        await db_session.execute(
            text(
                "SELECT data FROM event.events WHERE tenant_id = :t"
                " AND event_type = 'quality.recheck_succeeded'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one()
    assert event_data["task_id"] == task_id
    assert event_data["scope"] == "ALL"
    assert set(event_data["stats"]) == {
        "reconciliation",
        "coverage",
        "orphans",
        "checksum",
    }

    # 审计派生：TASK_CREATE（登记行）+ TASK_UPDATE（进度/终态回写）
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM platform.audit_logs WHERE tenant_id = :t"
            " AND action = 'TASK_CREATE' AND resource_type = 'tasks'"
            " AND resource_id = :rid",
            rid=task_id,
        )
        == 1
    )
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM platform.audit_logs WHERE tenant_id = :t"
            " AND action = 'TASK_UPDATE' AND resource_type = 'tasks'"
            " AND resource_id = :rid",
            rid=task_id,
        )
        >= 1
    )


# ---- 2. 单 scope：仅执行对应段（stats 只含该段） ----


async def test_recheck_scope_checksum_runs_only_checksum_segment(
    client: httpx.AsyncClient,
    default_tenant_id: UUID,
    seeded: None,
) -> None:
    admin = await _login(client, "admin")
    task_id = await _trigger(client, admin, "CHECKSUM")
    task = await _poll_terminal(client, admin, task_id)
    await _drain_background()

    assert task["scope"] == "CHECKSUM"
    assert task["status"] == "SUCCEEDED"
    assert set(task["stats"]) == {"checksum"}
    assert task["stats"]["checksum"] == {"sampled": 4, "failed": 0}
    # logs 只提及抽检段（其余段未执行）
    messages = [line["message"] for line in task["logs"]]
    assert any("抽检段" in m for m in messages)
    assert not any("对账段" in m for m in messages)
    assert not any("孤儿段" in m for m in messages)


# ---- 3. FAILED 路径：段计算抛错 → FAILED + 错误日志行 + failed 事件 ----


async def test_recheck_failure_marks_failed_and_writes_event(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    seeded: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _boom(sess, principal):
        raise RuntimeError("boom")

    monkeypatch.setattr(quality_service, "_checksum_sampling", _boom)

    admin = await _login(client, "admin")
    task_id = await _trigger(client, admin, "ALL")
    task = await _poll_terminal(client, admin, task_id)
    await _drain_background()

    assert task["status"] == "FAILED"
    assert task["finished_at"] is not None
    # 已完成段进度落库、失败段（checksum，ALL 序末段）不落 stats
    assert set(task["stats"]) == {"reconciliation", "coverage", "orphans"}
    error_lines = [line for line in task["logs"] if line["level"] == "ERROR"]
    assert error_lines and "boom" in error_lines[-1]["message"]

    event_data = (
        await db_session.execute(
            text(
                "SELECT data FROM event.events WHERE tenant_id = :t"
                " AND event_type = 'quality.recheck_failed'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one()
    assert event_data["task_id"] == task_id
    assert "boom" in event_data["error"]


# ---- 4. 跨租户 404（RLS 行不可见 → 不泄露存在性） ----


async def test_task_get_cross_tenant_404(
    client: httpx.AsyncClient,
    default_tenant_id: UUID,
    seeded: None,
    tenant_b: None,
) -> None:
    admin = await _login(client, "admin")
    task_id = await _trigger(client, admin, "CHECKSUM")
    task = await _poll_terminal(client, admin, task_id)
    await _drain_background()

    denied = await client.get(
        f"{TASKS}/{task_id}",
        headers=await _login(
            client, B_USERNAME, password=B_PASSWORD, tenant_slug=B_SLUG
        ),
    )
    assert denied.status_code == 404, denied.text
    assert denied.json()["error"]["code"] == "NOT_FOUND"

    # 同租户（触发者）仍可见
    own = await client.get(f"{TASKS}/{task_id}", headers=admin)
    assert own.status_code == 200, own.text
    assert own.json()["status"] == task["status"]


# ---- 5. 鉴权：ANALYST 触发 403（quality:run 无 ANALYST）且不登记任务 ----


async def test_analyst_cannot_trigger_recheck(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    seeded: None,
) -> None:
    analyst = await _login(client, "analyst1")
    denied = await client.post(RECHECKS, json={"scope": "ALL"}, headers=analyst)
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "FORBIDDEN"
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM ops.tasks WHERE tenant_id = :t",
        )
        == 0
    )


# ---- 6. T4 评审 Important-1 回归：后台先于请求 commit 启动的可见性竞态 ----


def _race_principal(tenant_id: UUID) -> Principal:
    """竞态用例合成主体（后台执行体仅用作 actor 留痕，不经鉴权链路）。"""
    return Principal(id="user:race-test", kind="HUMAN", tenant_id=tenant_id)


async def test_background_before_request_commit_retries_until_visible(
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """竞态模拟：任务行 INSERT 未 commit 时后台执行体先启动——READ
    COMMITTED 下行不可见且 FOR UPDATE 不等待，修复前首探即空被误诊
    「请求事务已回滚」静默退出 → 202 已返回而任务永久 RUNNING（孤儿）；
    修复后有界重试至请求事务 commit 后行可见才执行，终态照常落库。"""
    await core_db.dispose_engine()
    monkeypatch.setattr(core_db, "get_engine", lambda: app_role_engine)
    try:
        factory = core_db.get_session_local()
        principal = _race_principal(default_tenant_id)
        task_id = uuid4()
        started_at = datetime.now(UTC)

        # 「请求事务」等价路径：INSERT + flush 但不 commit（行对后台不可见）
        async with factory() as request_sess:
            await core_db.bind_tenant(request_sess, default_tenant_id)
            request_sess.add(
                OpsTask(
                    task_id=task_id,
                    tenant_id=default_tenant_id,
                    task_type=quality_service.RECHECK_TASK_TYPE,
                    status="RUNNING",
                    scope="ORPHAN",
                    started_at=started_at,
                    created_by=principal.id,
                )
            )
            await request_sess.flush()

            # 后台执行体先于请求 commit 启动（等价 start_recheck 的派发时序）
            background = asyncio.create_task(
                quality_service._run_recheck(
                    task_id=task_id,
                    tenant_id=default_tenant_id,
                    principal=principal,
                    scope="ORPHAN",
                    started_at=started_at,
                )
            )
            quality_service._recheck_tasks.add(background)
            background.add_done_callback(quality_service._recheck_tasks.discard)

            # 未提交窗口内让出事件循环：后台首次探测读空 → 进入重试等待
            # （修复前此处即静默退出——本断言在旧代码下即失败）
            await asyncio.sleep(0.3)
            assert not background.done(), "后台不应在未提交窗口内退出（误诊已回滚）"

            await request_sess.commit()  # 请求事务提交——行对后台可见
        await background  # 经有界重试看到行后照常执行到终态

        status = (
            await db_session.execute(
                text("SELECT status FROM ops.tasks WHERE task_id = :id"),
                {"id": task_id},
            )
        ).scalar_one()
        assert status == "SUCCEEDED"
    finally:
        await core_db.dispose_engine()  # 重置绑定到测试引擎的会话工厂


async def test_background_exits_after_deadline_when_request_rolled_back(
    app_role_engine: AsyncEngine,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """deadline 语义：请求事务回滚（行永不存在）→ 有界重试耗尽后退出
    并区分告警「已回滚」——不无限轮询；重试期间逐次留「未提交」信息。"""
    await core_db.dispose_engine()
    monkeypatch.setattr(core_db, "get_engine", lambda: app_role_engine)
    try:
        factory = core_db.get_session_local()
        principal = _race_principal(default_tenant_id)
        task_id = uuid4()

        async with factory() as request_sess:
            await core_db.bind_tenant(request_sess, default_tenant_id)
            request_sess.add(
                OpsTask(
                    task_id=task_id,
                    tenant_id=default_tenant_id,
                    task_type=quality_service.RECHECK_TASK_TYPE,
                    status="RUNNING",
                    scope="ORPHAN",
                    started_at=datetime.now(UTC),
                    created_by=principal.id,
                )
            )
            await request_sess.flush()
            await request_sess.rollback()  # 请求事务回滚——行不存在

        with caplog.at_level(
            logging.INFO, logger="edp_api.modules.quality.service"
        ):
            await quality_service._run_recheck(
                task_id=task_id,
                tenant_id=default_tenant_id,
                principal=principal,
                scope="ORPHAN",
                started_at=datetime.now(UTC),
            )
        messages = [record.getMessage() for record in caplog.records]
        # 重试中文案（未提交）与终判文案（已回滚）区分留痕
        assert any("未提交" in m and "重试" in m for m in messages)
        assert any("已回滚" in m for m in messages)
        assert (
            await _count(
                db_session,
                default_tenant_id,
                "SELECT count(*) FROM ops.tasks WHERE tenant_id = :t",
            )
            == 0
        )
    finally:
        await core_db.dispose_engine()


# ---- 7. T4 评审 Minor 回归：完成事件移出终态事务 ----


async def test_succeeded_survives_completion_event_failure(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    seeded: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """完成事件通道抛错仅告警：SUCCEEDED 终态先行 commit 不被回滚改判
    FAILED（修复前事件与终态同事务——ingest 异常会把成功计算改判
    FAILED）。"""

    async def _event_channel_down(sess, principal, **kwargs):
        raise RuntimeError("event channel down")

    monkeypatch.setattr(quality_service, "_record_recheck_event", _event_channel_down)

    admin = await _login(client, "admin")
    task_id = await _trigger(client, admin, "CHECKSUM")
    task = await _poll_terminal(client, admin, task_id)
    await _drain_background()

    assert task["status"] == "SUCCEEDED"  # 终态不被事件失败回滚
    assert task["stats"]["checksum"] == {"sampled": 4, "failed": 0}
    assert (
        await _count(
            db_session,
            default_tenant_id,
            "SELECT count(*) FROM event.events WHERE tenant_id = :t"
            " AND event_type LIKE 'quality.recheck%'",
        )
        == 0
    )
