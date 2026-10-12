"""T16 sync API 集成测试（B.12 最小版）+ W5 T5 任务历史落库：202 异步执行 /
状态轮询 / jobs 历史 / 清单 / 权限。

后台任务会话/引擎策略核实：_run 复用 run_sync_per_record(core_db.get_engine(),
...)——本文件客户端 fixture 将 core_db.get_engine monkeypatch 为
app_role_engine（edp_app 角色，受 RLS），任务内每记录独立事务自 bind_tenant，
不占用请求会话；轮询 GET 期间事件循环让出，后台任务得以推进。

任务落库（T5）：sync 触发在 ops.tasks 登记 adapter_sync 行（ref_name=适配器
名，scope=mode），status/jobs 读任务行（进程内 _jobs 注册表已移除——DB 断言
直证）；终态回写与清场竞态由 drain 后台任务兜底（同 test_quality_tasks）。

权限矩阵核实（0008 迁移 + rbac.py 同步后）：adapters:write →
PLATFORM_ADMIN/ADMIN/MANAGER——manager1（MANAGER）**有**写权限，不能当
403 用例；ANALYST 仅有 adapters:read → 403 POST 用例改用 analyst1
（GET status/jobs/清单仍 200），另以 manager1 POST 202 固化写权限矩阵。

轮询稳定性：deadline 轮询（10s 上界 + 50ms 间隔）——慢宿主（testcontainers
首次连接池预热）下 60 条逐记录事务通常 1~2s 完成，上界取计划 5s 的两倍
防 flake；超时 fail 附 last_sync 现场便于诊断。

T13 replay 用例（erp-demo）：清场复用 demo 复位实现（purge_tenant_business_
data）——演示源 id（C-008/X-100/...）不在 erp mock 清场模式内；锚直写固定值
（DEMO_ANCHOR 值）使 since 相对锚计算确定（naive since 由服务层按 UTC 归一）。
"""

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from edp_adapters.demo_dataset import SNAPSHOT_RECORDS
from edp_api.core import db as core_db
from edp_api.main import create_app
from edp_api.modules.demo import service as demo_service
from edp_api.modules.ingest import service as ingest_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

ADAPTERS = "/api/v1/admin/adapters"
LOGIN = "/api/v1/auth/login"
SEED_PASSWORD = "Admin@123!"

POLL_TIMEOUT = 10.0
POLL_INTERVAL = 0.05

# 演示数据集 erp 段记录数（replay 全量重放口径；plm 段不经 erp-demo）
ERP_DEMO_COUNT = sum(1 for spec in SNAPSHOT_RECORDS if spec.source_system == "erp")
# anchor-5h 窗口内 erp 段记录（offset=-300min：X-100:WH-01 / X-100:WH-02 / S-021:X-100）
ERP_DEMO_LAST_5H = 3

_BO_SCOPE = "(source_id LIKE 'SO-2026-%' OR source_id LIKE 'C-1%' OR source_id LIKE 'M-3%')"
_EV_SCOPE = (
    "(source_record_id LIKE 'SO-2026-%' OR source_record_id LIKE 'C-1%'"
    " OR source_record_id LIKE 'M-3%')"
)


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS）——后台任务经
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


@pytest.fixture(autouse=True)
async def _clean_adapter_rows(db_session: AsyncSession) -> None:
    """每测试后清场：erp mock 全链路痕迹（照 test_pipeline 清场 SQL）+
    adapter_sync 任务行及其 TASK 审计行（用例均轮询至任务完成后才返回，
    drain 兜底滞留后台执行体）。"""
    yield
    await _drain_background()
    await db_session.execute(
        text("""
            DELETE FROM platform.audit_logs WHERE
                detail->'after'->>'source_id' LIKE 'SO-2026-%'
                OR detail->'after'->>'source_id' LIKE 'C-1%'
                OR detail->'after'->>'source_id' LIKE 'M-3%'
                OR detail->>'source_id' LIKE 'SO-2026-%'
                OR detail->>'source_id' LIKE 'C-1%'
                OR detail->>'source_id' LIKE 'M-3%'
                OR detail->'after'->>'source_record_id' LIKE 'SO-2026-%'
                OR detail->'after'->>'source_record_id' LIKE 'C-1%'
                OR detail->'after'->>'source_record_id' LIKE 'M-3%'
                OR resource_id IN (SELECT event_id::text FROM event.events
                                    WHERE event_type LIKE '%\\_SNAPSHOT')
                OR resource_id IN (SELECT system_id::text FROM platform.systems
                                    WHERE name = 'erp')
                OR (action LIKE 'TASK_%' AND resource_id IN (
                    SELECT task_id::text FROM ops.tasks
                    WHERE task_type = 'adapter_sync'))
        """)
    )
    await db_session.execute(
        text(f"""
            DELETE FROM event.outbox WHERE
                aggregate_id IN (SELECT object_id FROM master.business_objects
                                 WHERE {_BO_SCOPE})
                OR aggregate_id IN (SELECT event_id FROM event.events
                                    WHERE event_type LIKE '%\\_SNAPSHOT')
        """)
    )
    await db_session.execute(
        text(f"""
            DELETE FROM evidence.records WHERE {_EV_SCOPE}
        """)
    )
    await db_session.execute(
        text("DELETE FROM event.events WHERE event_type LIKE '%\\_SNAPSHOT'")
    )
    # 领域投影行（T4）：子表先删（FK 指向 business_objects，不先清父行删不掉）
    await db_session.execute(
        text(
            "DELETE FROM sales.order_lines WHERE order_id IN"
            f" (SELECT object_id FROM master.business_objects WHERE {_BO_SCOPE})"
        )
    )
    await db_session.execute(
        text(
            "DELETE FROM sales.orders WHERE order_id IN"
            f" (SELECT object_id FROM master.business_objects WHERE {_BO_SCOPE})"
        )
    )
    await db_session.execute(
        text(
            "DELETE FROM master.customers WHERE customer_id IN"
            f" (SELECT object_id FROM master.business_objects WHERE {_BO_SCOPE})"
        )
    )
    await db_session.execute(
        text(
            "DELETE FROM master.materials WHERE material_id IN"
            f" (SELECT object_id FROM master.business_objects WHERE {_BO_SCOPE})"
        )
    )
    # governance（V1.2 0014）：admission/clean/classification FK 指向
    # business_objects——先清（先子后父：review→admission→classification；
    # clean→raw），否则 business_objects 删除被 FK 阻断
    await db_session.execute(
        text(
            "DELETE FROM governance.review_records WHERE tenant_id ="
            " (SELECT tenant_id FROM platform.tenants WHERE slug = 'default')"
        )
    )
    await db_session.execute(
        text(
            "DELETE FROM governance.admission_records WHERE tenant_id ="
            " (SELECT tenant_id FROM platform.tenants WHERE slug = 'default')"
        )
    )
    await db_session.execute(
        text(
            "DELETE FROM governance.object_classifications WHERE tenant_id ="
            " (SELECT tenant_id FROM platform.tenants WHERE slug = 'default')"
        )
    )
    await db_session.execute(
        text(
            "DELETE FROM governance.clean_records WHERE tenant_id ="
            " (SELECT tenant_id FROM platform.tenants WHERE slug = 'default')"
        )
    )
    await db_session.execute(
        text(
            "DELETE FROM governance.raw_records WHERE tenant_id ="
            " (SELECT tenant_id FROM platform.tenants WHERE slug = 'default')"
        )
    )
    await db_session.execute(
        text(f"DELETE FROM master.business_objects WHERE {_BO_SCOPE}")
    )
    await db_session.execute(text("DELETE FROM platform.systems WHERE name = 'erp'"))
    await db_session.execute(
        text("DELETE FROM ops.tasks WHERE task_type = 'adapter_sync'")
    )
    await db_session.commit()


@pytest.fixture
async def clean_demo_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    """erp-demo 用例清场：逆依赖序清本租户业务数据（复用 seed 复位实现——
    演示源 id（C-008/X-100/...）不在 erp mock 清场模式内）+ 清全链路审计行
    （actor=adapter:erp）。任务行/ TASK 审计由 _clean_adapter_rows 统一清。"""
    yield
    await demo_service.purge_tenant_business_data(db_session, default_tenant_id)
    await db_session.execute(
        text(
            "DELETE FROM platform.audit_logs"
            " WHERE tenant_id = :t AND actor_id = 'adapter:erp'"
        ),
        {"t": default_tenant_id},
    )
    await db_session.commit()


async def _set_demo_anchor(
    db_session: AsyncSession, tenant_id: UUID, anchor: datetime
) -> None:
    """直写演示锚（绕 ORM 审计；仅测试夹具用，模式同 test_demo_seed）。"""
    await db_session.execute(
        text(
            "UPDATE platform.tenants"
            " SET attributes = jsonb_set(attributes, '{demo_seed,anchor}',"
            " to_jsonb(CAST(:anchor AS text)))"
            " WHERE tenant_id = :t"
        ),
        {"t": tenant_id, "anchor": anchor.isoformat()},
    )
    await db_session.commit()


async def _login(
    client: httpx.AsyncClient, username: str
) -> dict[str, str]:
    """JWT 登录 → Authorization 头（0005 种子账号，密码 ENV 可覆盖缺省值）。"""
    resp = await client.post(
        LOGIN, json={"username": username, "password": SEED_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _trigger(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    mode: str,
    *,
    adapter: str = "erp",
    since: str | None = None,
) -> str:
    """POST /{adapter}/sync → 202；断言触发契约后返回 sync_id（since 仅 replay 传）。"""
    payload: dict[str, Any] = {"mode": mode}
    if since is not None:
        payload["since"] = since
    resp = await client.post(
        f"{ADAPTERS}/{adapter}/sync", json=payload, headers=headers
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert set(body) == {"sync_id", "status", "started_at"}
    assert body["status"] == "RUNNING"
    return body["sync_id"]


async def _poll_finished(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    sync_id: str,
    *,
    adapter: str = "erp",
) -> dict[str, Any]:
    """轮询 /{adapter}/status 直至指定任务完成；返回 last_sync（超时 fail 附现场）。"""
    deadline = time.monotonic() + POLL_TIMEOUT
    while True:
        resp = await client.get(f"{ADAPTERS}/{adapter}/status", headers=headers)
        assert resp.status_code == 200, resp.text
        last_sync = resp.json()["last_sync"]
        if last_sync and last_sync["sync_id"] == sync_id and last_sync["finished_at"]:
            return last_sync
        if time.monotonic() > deadline:
            pytest.fail(
                f"同步任务 {sync_id} 未在 {POLL_TIMEOUT}s 内完成：{last_sync}"
            )
        await asyncio.sleep(POLL_INTERVAL)


async def _drain_background(timeout_s: float = 10.0) -> None:
    """等待后台同步执行体收尾（当前任务之外全空即收齐；带超时兜底）——
    防清场/引擎销毁与执行体竞态（模式同 test_quality_tasks）。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if not pending:
            return
        await asyncio.wait(pending, timeout=0.5)


async def _objects_count(db_session: AsyncSession, tenant_id: UUID) -> int:
    return (
        await db_session.execute(
            text(
                "SELECT count(*) FROM master.business_objects"
                " WHERE tenant_id = :t AND source_system = 'erp'"
            ),
            {"t": tenant_id},
        )
    ).scalar_one()


# ---- 1. full：202 + RUNNING → 轮询 SUCCEEDED（stats.registered=60）+ 60 行落库 ----


async def test_full_sync_202_then_succeeded(
    client: httpx.AsyncClient, db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    headers = await _login(client, "admin")
    sync_id = await _trigger(client, headers, "full")

    last_sync = await _poll_finished(client, headers, sync_id)
    assert last_sync["status"] == "SUCCEEDED"
    assert last_sync["error"] is None
    assert last_sync["stats"] == {
        "fetched": 60,
        "registered": 60,
        "duplicated": 0,
        "failed": 0,
    }

    # 三元组落库：default 租户 objects 表 60 行 source_system=erp
    assert await _objects_count(db_session, default_tenant_id) == 60

    # 任务落库（T5）：ops.tasks 行 adapter_sync 终态 + finished_at（内存态移除直证）
    task_row = (
        await db_session.execute(
            text(
                "SELECT task_type, ref_name, scope, status, finished_at, stats"
                " FROM ops.tasks WHERE task_id = :id"
            ),
            {"id": UUID(sync_id)},
        )
    ).one()
    assert task_row.task_type == "adapter_sync"
    assert task_row.ref_name == "erp"
    assert task_row.scope == "full"
    assert task_row.status == "SUCCEEDED"
    assert task_row.finished_at is not None
    assert task_row.stats == {
        "fetched": 60,
        "registered": 60,
        "duplicated": 0,
        "failed": 0,
    }

    # 清单联动：水位登记后 last_sync_at 非空、状态回落"空闲"
    listing = await client.get(ADAPTERS, headers=headers)
    assert listing.status_code == 200, listing.text
    erp = listing.json()["items"][0]
    assert erp["last_sync_at"] is not None
    assert erp["status"] == "空闲"


# ---- 2. incremental（full 后）：fetched=8（5 更新 + 3 新）----


async def test_incremental_after_full_fetches_delta(
    client: httpx.AsyncClient, db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    headers = await _login(client, "admin")
    await _poll_finished(client, headers, await _trigger(client, headers, "full"))

    sync_id = await _trigger(client, headers, "incremental")
    last_sync = await _poll_finished(client, headers, sync_id)
    assert last_sync["status"] == "SUCCEEDED"
    assert last_sync["stats"]["fetched"] == 8
    assert last_sync["stats"]["registered"] == 8
    # 5 更新不新增对象、3 新对象 → 60 + 3
    assert await _objects_count(db_session, default_tenant_id) == 63


# ---- 3. 未注册适配器：POST sync / GET status 均 404 ----


async def test_unknown_adapter_404(client: httpx.AsyncClient) -> None:
    headers = await _login(client, "admin")
    post = await client.post(
        f"{ADAPTERS}/nope/sync", json={"mode": "full"}, headers=headers
    )
    assert post.status_code == 404
    assert post.json()["error"]["code"] == "NOT_FOUND"
    assert post.json()["error"]["message"] == "适配器不存在"

    status = await client.get(f"{ADAPTERS}/nope/status", headers=headers)
    assert status.status_code == 404
    assert status.json()["error"]["code"] == "NOT_FOUND"

    jobs = await client.get(f"{ADAPTERS}/nope/jobs", headers=headers)
    assert jobs.status_code == 404
    assert jobs.json()["error"]["code"] == "NOT_FOUND"


# ---- 4. 权限：manager1（MANAGER，0008 有 adapters:write）POST → 202 ----


async def test_manager_has_write_permission(
    client: httpx.AsyncClient
) -> None:
    headers = await _login(client, "manager1")
    sync_id = await _trigger(client, headers, "full")
    last_sync = await _poll_finished(client, headers, sync_id)
    assert last_sync["status"] == "SUCCEEDED"


# ---- 5. 权限：analyst1（ANALYST，仅 adapters:read）POST → 403、GET → 200 ----


async def test_analyst_readonly_post_403_get_200(
    client: httpx.AsyncClient,
) -> None:
    headers = await _login(client, "analyst1")
    post = await client.post(
        f"{ADAPTERS}/erp/sync", json={"mode": "full"}, headers=headers
    )
    assert post.status_code == 403
    assert post.json()["error"]["code"] == "FORBIDDEN"

    status = await client.get(f"{ADAPTERS}/erp/status", headers=headers)
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["adapter"] == "erp"
    assert body["mode"] == "mock"
    assert body["last_sync"] is None  # 本测试未触发过同步（清场后任务表为空）

    # jobs（adapters:read）可读：空历史 envelope
    jobs = await client.get(f"{ADAPTERS}/erp/jobs", headers=headers)
    assert jobs.status_code == 200, jobs.text
    assert jobs.json() == {"items": [], "next_cursor": None}


# ---- 6. 清单：analyst1 GET /admin/adapters → 200 + 三适配器行契约（T6） ----


async def test_list_adapters_analyst_200(client: httpx.AsyncClient) -> None:
    headers = await _login(client, "analyst1")
    resp = await client.get(ADAPTERS, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["next_cursor"] is None  # 固定清单无分页（W3-24 收口，B.0 envelope）
    items = body["items"]
    assert len(items) == 4
    assert [item["adapter"] for item in items] == [
        "erp",
        "erp-demo",
        "mes-demo",
        "plm-demo",
    ]
    erp = items[0]
    assert set(erp) == {"adapter", "mode", "status", "health", "last_sync_at"}
    assert erp["mode"] == "mock"
    assert erp["status"] == "空闲"  # 未同步过
    assert erp["health"] == "OK"
    assert erp["last_sync_at"] is None  # 水位未登记（清场后）


# ---- 7. replay（T13）：erp-demo 全量重放 → fetched==duplicated、不推 revision ----


async def test_replay_duplicates_all_records(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    clean_demo_rows: None,
) -> None:
    headers = await _login(client, "admin")
    full_id = await _trigger(client, headers, "full", adapter="erp-demo")
    full = await _poll_finished(client, headers, full_id, adapter="erp-demo")
    assert full["status"] == "SUCCEEDED"
    assert full["stats"] == {
        "fetched": ERP_DEMO_COUNT,
        "registered": ERP_DEMO_COUNT,
        "duplicated": 0,
        "failed": 0,
    }

    replay_id = await _trigger(client, headers, "replay", adapter="erp-demo")
    replay = await _poll_finished(client, headers, replay_id, adapter="erp-demo")
    assert replay["status"] == "SUCCEEDED"
    assert replay["stats"] == {
        "fetched": ERP_DEMO_COUNT,
        "registered": 0,
        "duplicated": ERP_DEMO_COUNT,
        "failed": 0,
    }

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


# ---- 8. replay + since：仅近 5h 窗口记录（锚固定 → 确定性 3 条） ----


async def test_replay_since_filters_window(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    clean_demo_rows: None,
) -> None:
    # 固定锚（DEMO_ANCHOR 值，直写绕 ORM 审计）——since 相对锚计算确定
    anchor = datetime(2026, 9, 28, 8, 30, tzinfo=UTC)
    await _set_demo_anchor(db_session, default_tenant_id, anchor)

    headers = await _login(client, "admin")
    full_id = await _trigger(client, headers, "full", adapter="erp-demo")
    await _poll_finished(client, headers, full_id, adapter="erp-demo")

    since = (anchor - timedelta(hours=5)).isoformat()
    replay_id = await _trigger(
        client, headers, "replay", adapter="erp-demo", since=since
    )
    replay = await _poll_finished(client, headers, replay_id, adapter="erp-demo")
    assert replay["status"] == "SUCCEEDED"
    assert replay["stats"] == {
        "fetched": ERP_DEMO_LAST_5H,
        "registered": 0,
        "duplicated": ERP_DEMO_LAST_5H,
        "failed": 0,
    }

    # 窗口外记录未被触碰：erp 段对象仍为全集
    assert await _objects_count(db_session, default_tenant_id) == ERP_DEMO_COUNT


# ---- 9. 非法 mode：400 VALIDATION_ERROR（统一 envelope，不触发任务） ----


async def test_invalid_mode_rejected(client: httpx.AsyncClient) -> None:
    headers = await _login(client, "admin")
    resp = await client.post(
        f"{ADAPTERS}/erp-demo/sync", json={"mode": "bogus"}, headers=headers
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


# ---- 10. jobs 历史（T5）：两次 sync → 倒序两行 + next_cursor 翻页语义 ----


async def test_jobs_history_desc_with_cursor_pagination(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    headers = await _login(client, "admin")
    first_id = await _trigger(client, headers, "full")
    await _poll_finished(client, headers, first_id)
    second_id = await _trigger(client, headers, "incremental")
    await _poll_finished(client, headers, second_id)

    # 全量列表：按 started_at 倒序两行、行形状契约、无下一页
    resp = await client.get(f"{ADAPTERS}/erp/jobs", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"items", "next_cursor"}
    items = body["items"]
    assert [item["task_id"] for item in items] == [second_id, first_id]
    for item in items:
        assert set(item) == {
            "task_id",
            "status",
            "scope",
            "stats",
            "started_at",
            "finished_at",
        }
        assert item["status"] == "SUCCEEDED"
        assert item["finished_at"] is not None
    assert items[0]["scope"] == "incremental"
    assert items[1]["scope"] == "full"
    assert items[0]["stats"] == {
        "fetched": 8,
        "registered": 8,
        "duplicated": 0,
        "failed": 0,
    }
    assert body["next_cursor"] is None  # 全量两行无下一页

    # limit=1 首页 + next_cursor 翻页取次行（再无下一页）
    page1 = await client.get(f"{ADAPTERS}/erp/jobs?limit=1", headers=headers)
    assert page1.status_code == 200, page1.text
    p1 = page1.json()
    assert [item["task_id"] for item in p1["items"]] == [second_id]
    assert p1["next_cursor"] is not None
    page2 = await client.get(
        f"{ADAPTERS}/erp/jobs",
        params={"limit": 1, "cursor": p1["next_cursor"]},
        headers=headers,
    )
    assert page2.status_code == 200, page2.text
    p2 = page2.json()
    assert [item["task_id"] for item in p2["items"]] == [first_id]
    assert p2["next_cursor"] is None

    # DB 断言：两条 ops.tasks 行 task_type=adapter_sync（内存态移除的证明）
    rows = (
        await db_session.execute(
            text(
                "SELECT task_id, status FROM ops.tasks WHERE tenant_id = :t"
                " AND task_type = 'adapter_sync' AND ref_name = 'erp'"
                " ORDER BY started_at DESC"
            ),
            {"t": default_tenant_id},
        )
    ).all()
    assert [(str(row.task_id), row.status) for row in rows] == [
        (second_id, "SUCCEEDED"),
        (first_id, "SUCCEEDED"),
    ]

    # status=最近一条：响应形状不变（既有契约兼容）
    status = await client.get(f"{ADAPTERS}/erp/status", headers=headers)
    assert status.status_code == 200, status.text
    status_body = status.json()
    assert set(status_body) == {"adapter", "mode", "last_sync", "health"}
    last_sync = status_body["last_sync"]
    assert set(last_sync) == {"sync_id", "status", "finished_at", "stats", "error"}
    assert last_sync["sync_id"] == second_id
    assert last_sync["status"] == "SUCCEEDED"
    assert last_sync["error"] is None
    assert last_sync["stats"] == {
        "fetched": 8,
        "registered": 8,
        "duplicated": 0,
        "failed": 0,
    }


# ---- 11. FAILED 路径（T5 评审移交）：整批异常 → FAILED 终态 + error 提取 ----


async def test_sync_batch_failure_marks_failed_with_error(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_sync_per_record 整批级异常 → 任务 FAILED：error 自末条 ERROR 日志
    行提取（任务行无独立 error 列）、stats 空 → None（对齐「完成前 stats 为
    空」语义）、DB 行 FAILED + finished_at。"""

    async def _boom(engine, tenant_id, adapter, mode, since=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(ingest_service, "run_sync_per_record", _boom)

    headers = await _login(client, "admin")
    sync_id = await _trigger(client, headers, "full")
    last_sync = await _poll_finished(client, headers, sync_id)
    await _drain_background()

    assert last_sync["status"] == "FAILED"
    assert last_sync["error"] is not None and "boom" in last_sync["error"]
    assert last_sync["finished_at"] is not None
    assert last_sync["stats"] is None  # FAILED 路径 stats={} → None

    # DB 断言：任务行 FAILED 终态 + finished_at + ERROR 日志行落库
    row = (
        await db_session.execute(
            text(
                "SELECT status, finished_at, logs, stats FROM ops.tasks"
                " WHERE task_type = 'adapter_sync' AND task_id = :id"
            ),
            {"id": UUID(sync_id)},
        )
    ).one()
    assert row.status == "FAILED"
    assert row.finished_at is not None
    assert row.stats == {}  # W5-21-a：FAILED 即无最终计数（DB 行级直证）
    error_lines = [line for line in row.logs if line.get("level") == "ERROR"]
    assert error_lines and "boom" in error_lines[-1]["message"]
