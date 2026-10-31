"""T3 Trace 集成测试（EDP-013，B.10）：轨迹写入/查询含 tool_calls。

覆盖：
1. 主流程（B.10 示例逐字段）：一条 trace + 3 tool_calls 201 → 落库字段齐
   （evidence_refs UUID[]/token_usage/JSONB、created_by）→ 详情 3 条 seq
   升序字段齐（called_at 请求值/缺省 now）→ **同 trace_id 重发 200 幂等
   返回既有（tool_calls 不重写，仍 3 条；TRACE_CREATE 审计仅一条）**；
2. 列表：默认序 started_at DESC；agent_id/task_id/capability_id/since
   过滤；limit+游标翻页；列表简投影不含大 JSON/tool_calls；
3. 鉴权：HUMAN（manager1 JWT）POST 403（无角色持有 trace:write）；仅
   readonly scope 的 Key POST 403；manager1/analyst1 JWT 读 200（0011
   trace:read 同步 rbac 矩阵）；
4. capability_id 不存在 → 400 VALIDATION_ERROR（失败不残留行）；
5. 跨租户：B 租户读详情 404 / 列表空；B 租户以 write:trace 重发同
   trace_id → 409 CONFLICT（主键撞、RLS 不可见）。

会话形态：应用引擎 = conftest.app_role_engine（edp_app，FORCE RLS）；断言以
migrator db_session 直查（绕 RLS）。清场：trace 两表行 + 切面/显式审计行 +
本测试注册的 capabilities 行 + 临时 Key/tenant-traces（migrator 绕 RLS）。
"""

from uuid import UUID, uuid4

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.core.security.apikey import hash_key
from edp_api.main import create_app
from edp_api.modules.audit.aspect import install_audit_aspect
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

BASE = "/api/v1"
DEV_KEY = "edp-dev-agent-hub-key"
DEV_HEADERS = {"X-API-Key": DEV_KEY}
LOGIN = "/api/v1/auth/login"
SEED_PASSWORD = "Admin@123!"

# 仅 readonly scope 的临时 API Key（写 403 用例；每测试自行插入/清场）
READONLY_KEY = "t3-traces-readonly-key"
READONLY_PRINCIPAL = "t3-traces-readonly"

# 跨租户用例的 B 租户（migrator 直造；readonly + write:trace Key）
TENANT_B_SLUG = "tenant-traces"
TENANT_B_KEY = "t3-traces-tenant-b-key"
TENANT_B_PRINCIPAL = "t3-traces-tenant-b"

CAPABILITY_PAYLOAD = {
    "name": "Delivery.OrderRisk",
    "domain": "delivery",
    "input_schema": {"type": "object"},
    "output_schema": {"type": "object"},
    "risk_level": "L2",
    "permission": "READ_ONLY",
}


def _trace_payload(**overrides: object) -> dict:
    """B.10 请求示例（逐字段；trace_id/evidence_refs/capability_id 测试内填）。"""
    payload: dict = {
        "trace_id": str(uuid4()),
        "agent_id": "agent:delivery-order-risk",
        "task_id": "task-0928-001",
        "capability_id": None,
        "started_at": "2026-09-28T08:00:00Z",
        "finished_at": "2026-09-28T08:00:41Z",
        "status": "SUCCEEDED",
        "input_context": {"order_no": "SO-2026-00123"},
        "output_structured": {"risk_level": "P1", "score": 0.86},
        "token_usage": {"prompt": 3120, "completion": 480, "total": 3600},
        "evidence_refs": [str(uuid4())],
        "tool_calls": [
            {
                "seq": 1,
                "tool_name": "get_inventory",
                "input": {"material_code": "X-100"},
                "output": {"total_available": 3200},
                "status_code": 200,
                "latency_ms": 85,
            },
            {
                "seq": 2,
                "tool_name": "get_order",
                "input": {"order_no": "SO-2026-00123"},
                "output": {"status": "SHIPPED"},
                "status_code": 200,
                "latency_ms": 42,
                "called_at": "2026-09-28T08:00:10Z",
            },
            {
                "seq": 3,
                "tool_name": "call_weather",
                "input": {"city": "Shanghai"},
                "status_code": 503,
                "error": {"code": "UPSTREAM_UNAVAILABLE"},
                "latency_ms": 8,
            },
        ],
    }
    payload.update(overrides)
    return payload


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS），traces 路由
    随 create_app 装配。"""
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
    """与 create_app 同一装配（catalog 写路径依赖切面落审计）。"""
    install_audit_aspect()


@pytest.fixture(autouse=True)
async def _clean_trace_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    """每测试后清场：trace 两表行（tool_calls → traces，FK 序）+ 审计行
    （resource_type=traces/capabilities）+ 本测试注册的能力行 + 临时
    Key/tenant-traces（migrator 绕 RLS）。"""
    yield
    await db_session.execute(
        text("DELETE FROM trace.tool_calls WHERE tenant_id = :t"),
        {"t": default_tenant_id},
    )
    await db_session.execute(
        text("DELETE FROM trace.traces WHERE tenant_id = :t"),
        {"t": default_tenant_id},
    )
    await db_session.execute(
        text(
            "DELETE FROM platform.audit_logs WHERE tenant_id = :t"
            " AND resource_type IN ('traces', 'capabilities')"
        ),
        {"t": default_tenant_id},
    )
    await db_session.execute(
        text("DELETE FROM platform.capabilities WHERE tenant_id = :t"),
        {"t": default_tenant_id},
    )
    await db_session.execute(
        text("DELETE FROM platform.api_keys WHERE principal_id = :p"),
        {"p": READONLY_PRINCIPAL},
    )
    b_ids = "SELECT tenant_id FROM platform.tenants WHERE slug = 'tenant-traces'"
    await db_session.execute(
        text("DELETE FROM platform.api_keys WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM trace.tool_calls WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM trace.traces WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text(
            "DELETE FROM platform.tenant_usage_daily WHERE tenant_id IN"
            " (SELECT tenant_id FROM platform.tenants WHERE slug = 'tenant-traces')"
        )
    )
    await db_session.execute(
        text("DELETE FROM platform.tenants WHERE slug = 'tenant-traces'")
    )
    await db_session.commit()


async def _insert_api_key(
    db_session: AsyncSession,
    tenant_id: UUID,
    *,
    key: str,
    principal_id: str,
    scopes: list[str],
) -> None:
    """直插临时 API Key（照 test_catalog 模式；hash_key 与生产同实现）。"""
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


async def _create_capability(client: httpx.AsyncClient) -> str:
    """注册一个能力（catalog API）供 capability_id 关联/过滤用例。"""
    resp = await client.post(
        f"{BASE}/capabilities", headers=DEV_HEADERS, json=CAPABILITY_PAYLOAD
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["capability_id"]


async def _login(client: httpx.AsyncClient, username: str) -> dict[str, str]:
    resp = await client.post(
        LOGIN, json={"username": username, "password": SEED_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ---- 1. 主流程：写入 + 详情 seq 升序 + 重发幂等 ----


async def test_trace_create_detail_and_idempotent_replay(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    capability_id = await _create_capability(client)
    evidence_ref = str(uuid4())
    payload = _trace_payload(capability_id=capability_id, evidence_refs=[evidence_ref])

    resp = await client.post(f"{BASE}/traces", headers=DEV_HEADERS, json=payload)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["trace_id"] == payload["trace_id"]
    assert body["status"] == "SUCCEEDED"
    assert body["created_at"]

    row = (
        await db_session.execute(
            text(
                "SELECT agent_id, task_id, capability_id::text, started_at,"
                " finished_at, status, input_context, output_structured,"
                " token_usage, evidence_refs::text[], created_by"
                " FROM trace.traces WHERE trace_id = :t"
            ),
            {"t": payload["trace_id"]},
        )
    ).one()
    assert row.agent_id == "agent:delivery-order-risk"
    assert row.task_id == "task-0928-001"
    assert row.capability_id == capability_id
    assert str(row.started_at) == "2026-09-28 08:00:00+00:00"
    assert str(row.finished_at) == "2026-09-28 08:00:41+00:00"
    assert row.status == "SUCCEEDED"
    assert row.input_context == payload["input_context"]
    assert row.output_structured == payload["output_structured"]
    assert row.token_usage == payload["token_usage"]
    assert row.evidence_refs == [evidence_ref]
    assert row.created_by == "agent-hub"

    # tool_calls 落库：3 行；tc2 called_at 取请求值，其余缺省 now()
    calls = (
        await db_session.execute(
            text(
                "SELECT seq, tool_name, status_code, error, latency_ms,"
                " called_at FROM trace.tool_calls WHERE trace_id = :t"
                " ORDER BY seq"
            ),
            {"t": payload["trace_id"]},
        )
    ).all()
    assert [c.seq for c in calls] == [1, 2, 3]
    assert calls[2].error == {"code": "UPSTREAM_UNAVAILABLE"}
    assert str(calls[1].called_at) == "2026-09-28 08:00:10+00:00"
    for call in (calls[0], calls[2]):
        assert call.called_at is not None

    # 详情：完整轨迹 + tool_calls seq 升序字段齐
    resp = await client.get(
        f"{BASE}/traces/{payload['trace_id']}", headers=DEV_HEADERS
    )
    assert resp.status_code == 200, resp.text
    detail = resp.json()
    assert detail["trace_id"] == payload["trace_id"]
    assert detail["input_context"] == payload["input_context"]
    assert detail["token_usage"] == payload["token_usage"]
    assert detail["evidence_refs"] == [evidence_ref]
    assert [tc["seq"] for tc in detail["tool_calls"]] == [1, 2, 3]
    first = detail["tool_calls"][0]
    assert first["tool_name"] == "get_inventory"
    assert first["input"] == {"material_code": "X-100"}
    assert first["output"] == {"total_available": 3200}
    assert first["status_code"] == 200
    assert first["latency_ms"] == 85
    assert first["call_id"]
    assert first["called_at"]

    # 同 trace_id 重发（载荷变更：仅 1 条 tool_call、status FAILED）→ 200
    # 幂等返回既有（SUCCEEDED / 原 created_at），不重写 tool_calls
    replay = _trace_payload(
        trace_id=payload["trace_id"],
        status="FAILED",
        tool_calls=[{"seq": 9, "tool_name": "extra", "status_code": 200}],
    )
    resp = await client.post(f"{BASE}/traces", headers=DEV_HEADERS, json=replay)
    assert resp.status_code == 200, resp.text
    replay_body = resp.json()
    assert replay_body["trace_id"] == payload["trace_id"]
    assert replay_body["status"] == "SUCCEEDED"
    assert replay_body["created_at"] == body["created_at"]

    assert (
        await db_session.execute(
            text("SELECT count(*) FROM trace.tool_calls WHERE trace_id = :t"),
            {"t": payload["trace_id"]},
        )
    ).scalar_one() == 3
    assert (
        await db_session.execute(
            text(
                "SELECT count(*) FROM trace.tool_calls"
                " WHERE trace_id = :t AND seq = 9"
            ),
            {"t": payload["trace_id"]},
        )
    ).scalar_one() == 0
    # 幂等重发不补审计（TRACE_CREATE 仅一条）
    assert (
        await db_session.execute(
            text(
                "SELECT count(*) FROM platform.audit_logs"
                " WHERE resource_type = 'traces' AND resource_id = :r"
            ),
            {"r": payload["trace_id"]},
        )
    ).scalar_one() == 1

    resp = await client.get(
        f"{BASE}/traces/{payload['trace_id']}", headers=DEV_HEADERS
    )
    assert resp.status_code == 200, resp.text
    assert [tc["seq"] for tc in resp.json()["tool_calls"]] == [1, 2, 3]


# ---- 2. 列表：过滤 + started_at DESC + 游标翻页 + 简投影 ----


async def test_trace_list_filters_and_cursor(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    capability_id = await _create_capability(client)

    def _mk(
        trace_id: str, agent: str, task: str, started: str, **extra: object
    ) -> dict:
        return _trace_payload(
            trace_id=trace_id,
            agent_id=agent,
            task_id=task,
            started_at=started,
            finished_at=None,
            capability_id=capability_id,
            tool_calls=[],
            **extra,
        )

    t1 = str(uuid4())
    t2 = str(uuid4())
    t3 = str(uuid4())
    for payload in (
        _mk(t1, "agent-a", "task-1", "2026-09-28T08:00:00Z"),
        _mk(t2, "agent-a", "task-2", "2026-09-28T09:00:00Z"),
        _mk(t3, "agent-b", "task-1", "2026-09-28T10:00:00Z"),
    ):
        resp = await client.post(f"{BASE}/traces", headers=DEV_HEADERS, json=payload)
        assert resp.status_code == 201, resp.text

    # 默认序 started_at DESC（t3 → t2 → t1）；简投影不含大 JSON/tool_calls
    resp = await client.get(f"{BASE}/traces", headers=DEV_HEADERS)
    assert resp.status_code == 200, resp.text
    page = resp.json()
    assert [item["trace_id"] for item in page["items"]] == [t3, t2, t1]
    assert page.get("next_cursor") is None
    item = page["items"][0]
    assert set(item) == {
        "trace_id",
        "agent_id",
        "task_id",
        "capability_id",
        "started_at",
        "status",
    }
    assert item["agent_id"] == "agent-b"

    # 过滤：agent_id / task_id / capability_id / since
    for params, expected in (
        ({"agent_id": "agent-a"}, [t2, t1]),
        ({"task_id": "task-1"}, [t3, t1]),
        ({"capability_id": capability_id}, [t3, t2, t1]),
        ({"capability_id": str(uuid4())}, []),
        ({"since": "2026-09-28T08:30:00Z"}, [t3, t2]),
        ({"agent_id": "agent-a", "since": "2026-09-28T08:30:00Z"}, [t2]),
    ):
        resp = await client.get(
            f"{BASE}/traces", params=params, headers=DEV_HEADERS
        )
        assert resp.status_code == 200, resp.text
        assert [i["trace_id"] for i in resp.json()["items"]] == expected, params

    # 游标翻页：limit=2 → 首页 [t3, t2]，次页 [t1] 止
    resp = await client.get(
        f"{BASE}/traces",
        params={"limit": 2},
        headers=DEV_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    page1 = resp.json()
    assert [i["trace_id"] for i in page1["items"]] == [t3, t2]
    assert page1["next_cursor"]

    resp = await client.get(
        f"{BASE}/traces",
        params={"limit": 2, "cursor": page1["next_cursor"]},
        headers=DEV_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    page2 = resp.json()
    assert [i["trace_id"] for i in page2["items"]] == [t1]
    assert page2.get("next_cursor") is None


# ---- 3. 鉴权：HUMAN 写 403 / readonly Key 写 403 / JWT 读 200 ----


async def test_trace_auth_tracks(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    manager = await _login(client, "manager1")
    analyst = await _login(client, "analyst1")

    # HUMAN（JWT）无角色持有 trace:write → 403 FORBIDDEN
    resp = await client.post(
        f"{BASE}/traces", headers=manager, json=_trace_payload()
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    # 仅 readonly scope 的 Key：写需 write:trace → 403
    await _insert_api_key(
        db_session,
        default_tenant_id,
        key=READONLY_KEY,
        principal_id=READONLY_PRINCIPAL,
        scopes=["readonly"],
    )
    resp = await client.post(
        f"{BASE}/traces",
        headers={"X-API-Key": READONLY_KEY},
        json=_trace_payload(),
    )
    assert resp.status_code == 403, resp.text

    # JWT 读轨道（0011 trace:read 同步 rbac 矩阵）：MANAGER/ANALYST 200
    for headers in (manager, analyst):
        resp = await client.get(f"{BASE}/traces", headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["items"] == []

    # readonly Key 读亦通（scope 轨道）
    resp = await client.get(f"{BASE}/traces", headers={"X-API-Key": READONLY_KEY})
    assert resp.status_code == 200, resp.text


# ---- 4. capability 不存在 → 400（失败不残留） ----


async def test_trace_missing_capability_rejected(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    resp = await client.post(
        f"{BASE}/traces",
        headers=DEV_HEADERS,
        json=_trace_payload(capability_id=str(uuid4())),
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert (
        await db_session.execute(
            text("SELECT count(*) FROM trace.traces WHERE tenant_id = :t"),
            {"t": default_tenant_id},
        )
    ).scalar_one() == 0
    assert (
        await db_session.execute(
            text("SELECT count(*) FROM trace.tool_calls WHERE tenant_id = :t"),
            {"t": default_tenant_id},
        )
    ).scalar_one() == 0


# ---- 5. 跨租户：详情 404 / 列表空；同 trace_id 重发 → 409 ----


async def test_trace_cross_tenant_isolated(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    payload = _trace_payload()
    resp = await client.post(f"{BASE}/traces", headers=DEV_HEADERS, json=payload)
    assert resp.status_code == 201, resp.text

    tenant_b = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO platform.tenants (tenant_id, slug, name, status)"
            " VALUES (:t, :slug, '租户TraceB', 'ACTIVE')"
        ),
        {"t": tenant_b, "slug": TENANT_B_SLUG},
    )
    await db_session.commit()
    await _insert_api_key(
        db_session,
        tenant_b,
        key=TENANT_B_KEY,
        principal_id=TENANT_B_PRINCIPAL,
        scopes=["readonly", "write:trace"],
    )
    headers = {"X-API-Key": TENANT_B_KEY}

    # 详情跨租户 404（不泄露存在性）；列表空
    resp = await client.get(f"{BASE}/traces/{payload['trace_id']}", headers=headers)
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "NOT_FOUND"

    resp = await client.get(f"{BASE}/traces", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []

    # B 租户以 write:trace 重发同 trace_id：主键撞但 RLS 不可见 → 409
    resp = await client.post(
        f"{BASE}/traces",
        headers=headers,
        json=_trace_payload(trace_id=payload["trace_id"], tool_calls=[]),
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "CONFLICT"
