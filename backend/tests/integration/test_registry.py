"""T11 registry 集成测试（B.2 契约）：upsert/乐观锁/并发/查询/history/隔离。

应用引擎 = conftest.app_role_engine（NOBYPASSRLS，与生产 api 同角色）——
RLS 隔离（跨租户 404）在测试路径真实生效。双轨认证：API Key（write:registry
+ readonly）负责写路径，JWT（manager1=MANAGER / analyst1=ANALYST）负责读与
越权用例。

并发用例（4）确定性保证：monkeypatch service._find_by_composite 加双读门闩
——两个并发 upsert 的组合键 SELECT 都完成（各读到 revision=2）后才放行，
杜绝"B 在 A 提交后才读、恰好看成 expected=3 匹配"的调度偶然性。
"""

import asyncio
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.main import create_app
from edp_api.modules.registry import service as registry_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

OBJECTS = "/api/v1/objects"
LOGIN = "/api/v1/auth/login"
DEV_API_KEY = "edp-dev-agent-hub-key"
SEED_PASSWORD = "Admin@123!"

KEY_HEADERS = {"X-API-Key": DEV_API_KEY}

# 本模块全部对象共用一个自然键（source_id 前缀 SO-REG- 供清理识别）
COMPOSITE: dict[str, Any] = {
    "object_type": "ORDER",
    "owner_domain": "sales",
    "source_system": "erp",
    "source_id": "SO-REG-2026-00123",
}


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS），registry 路由随
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
async def _clean_registry_rows(db_session: AsyncSession) -> None:
    """每测试后清场：删除本模块痕迹（SO-REG-% 对象 + 关联 outbox + 临时租户），
    保证 test_tenant_context 的 count=0 前提与用例间独立（migrator 绕 RLS）。"""
    yield
    await db_session.execute(
        text(
            "DELETE FROM event.outbox WHERE aggregate_id IN"
            " (SELECT object_id FROM master.business_objects WHERE source_id LIKE 'SO-REG-%')"
        )
    )
    await db_session.execute(
        text("DELETE FROM master.business_objects WHERE source_id LIKE 'SO-REG-%'")
    )
    await db_session.execute(
        text(
            "DELETE FROM platform.tenant_usage_daily WHERE tenant_id IN"
            " (SELECT tenant_id FROM platform.tenants WHERE slug = 'tenant-b-pytest')"
        )
    )
    await db_session.execute(
        text("DELETE FROM platform.tenants WHERE slug = 'tenant-b-pytest'")
    )
    await db_session.commit()


async def _post_object(
    client: httpx.AsyncClient, attributes: dict, expected_revision: int | None = None
) -> httpx.Response:
    payload: dict[str, Any] = {**COMPOSITE, "attributes": attributes}
    if expected_revision is not None:
        payload["idempotency"] = {"expected_revision": expected_revision}
    return await client.post(OBJECTS, json=payload, headers=KEY_HEADERS)


async def _ensure_revision(client: httpx.AsyncClient, target: int) -> str:
    """幂等前置：将 COMPOSITE 对象经 API Key 连续 upsert 至 revision=target，
    返回 object_id（每测试独立清场 → 从 revision=1 起连发 target 次）。"""
    object_id: str | None = None
    for seq in range(1, target + 1):
        resp = await _post_object(client, {"seq": seq})
        assert resp.status_code in (200, 201), resp.text
        object_id = resp.json()["object_id"]
    assert object_id is not None
    return object_id


async def _login(client: httpx.AsyncClient, username: str) -> str:
    resp = await client.post(
        LOGIN, json={"username": username, "password": SEED_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


# ---- 1. API Key 首次注册：201 revision=1 status=ACTIVE ----


async def test_first_upsert_created_201(client: httpx.AsyncClient) -> None:
    resp = await _post_object(client, {"amount": 120000.0})
    assert resp.status_code == 201
    body = resp.json()
    assert set(body) == {"object_id", "revision", "status", "created_at"}
    UUID(body["object_id"])
    assert body["revision"] == 1
    assert body["status"] == "ACTIVE"
    assert body["created_at"]


# ---- 2. 同键再 POST（无 expected_revision）：200 且 revision 递增 ----


async def test_repeat_upsert_bumps_revision_200(client: httpx.AsyncClient) -> None:
    object_id = await _ensure_revision(client, 1)
    resp = await _post_object(client, {"amount": 999.0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["object_id"] == object_id
    assert body["revision"] == 2


# ---- 3. expected_revision 失配：409 CONFLICT + current_revision ----


async def test_wrong_expected_revision_conflict_409(
    client: httpx.AsyncClient,
) -> None:
    await _ensure_revision(client, 2)
    resp = await _post_object(
        client, {"amount": 1.0}, expected_revision=99
    )
    assert resp.status_code == 409
    error = resp.json()["error"]
    assert error["code"] == "CONFLICT"
    assert error["current_revision"] == 2


# ---- 4. 并发：两个 expected_revision 同键 upsert 恰一成功 ----


async def test_concurrent_upserts_exactly_one_wins(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    object_id = await _ensure_revision(client, 2)

    # 双读门闩：两个并发请求的组合键 SELECT 均完成（读到 revision=2）后放行，
    # 使 expected=3 的请求在应用层版本检查即 409（不依赖事件循环调度时序）
    gate = asyncio.Event()
    reads = 0
    original = registry_service._find_by_composite

    async def both_read_before_write(
        sess: AsyncSession, tenant_id: UUID, req: Any
    ) -> Any:
        nonlocal reads
        row = await original(sess, tenant_id, req)
        reads += 1
        if reads >= 2:
            gate.set()
        await asyncio.wait_for(gate.wait(), timeout=10)
        return row

    monkeypatch.setattr(
        registry_service, "_find_by_composite", both_read_before_write
    )

    resp_a, resp_b = await asyncio.gather(
        _post_object(client, {"winner": "a"}, expected_revision=2),
        _post_object(client, {"winner": "b"}, expected_revision=3),
    )
    statuses = sorted((resp_a.status_code, resp_b.status_code))
    assert statuses == [200, 409], (resp_a.text, resp_b.text)

    conflict = resp_a if resp_a.status_code == 409 else resp_b
    assert conflict.json()["error"]["code"] == "CONFLICT"
    assert conflict.json()["error"]["current_revision"] == 2

    detail = await client.get(f"{OBJECTS}/{object_id}", headers=KEY_HEADERS)
    assert detail.status_code == 200
    assert detail.json()["revision"] == 3


# ---- 5. JWT 读路径：组合键查询 / 点查 / history 轨迹 ----


async def test_jwt_manager_composite_detail_history(
    client: httpx.AsyncClient,
) -> None:
    object_id = await _ensure_revision(client, 3)
    jwt_headers = {"Authorization": f"Bearer {await _login(client, 'manager1')}"}

    listed = await client.get(
        OBJECTS,
        params={
            "object_type": "ORDER",
            "source_system": "erp",
            "source_id": COMPOSITE["source_id"],
        },
        headers=jwt_headers,
    )
    assert listed.status_code == 200
    body = listed.json()
    # 列表路由 exclude_none：无更多页时 next_cursor 键缺省（等价 null）
    assert body.get("next_cursor") is None
    assert len(body["items"]) == 1
    assert body["items"][0]["object_id"] == object_id
    assert body["items"][0]["revision"] == 3

    detail = await client.get(f"{OBJECTS}/{object_id}", headers=jwt_headers)
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["object_type"] == "ORDER"
    assert detail_body["source_system"] == "erp"
    assert detail_body["source_id"] == COMPOSITE["source_id"]
    assert detail_body["owner_domain"] == "sales"
    assert detail_body["revision"] == 3
    assert detail_body["status"] == "ACTIVE"
    assert detail_body["merged_into"] is None
    assert detail_body["attributes"] == {"seq": 3}

    history = await client.get(f"{OBJECTS}/{object_id}/history", headers=jwt_headers)
    assert history.status_code == 200
    revisions = history.json()["revisions"]
    assert [entry["revision"] for entry in revisions] == [1, 2, 3]
    assert {entry["action"] for entry in revisions} == {"OBJECT_UPSERT"}
    assert {entry["actor_id"] for entry in revisions} == {"agent-hub"}
    assert all(entry["occurred_at"] for entry in revisions)


# ---- 6. 跨租户：RLS 使对方对象 = 不存在（404，不泄露） ----


async def test_cross_tenant_object_not_found(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    tenant_b = uuid4()
    b_object = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO platform.tenants (tenant_id, slug, name, status)"
            " VALUES (:t, 'tenant-b-pytest', '租户B', 'ACTIVE')"
        ),
        {"t": tenant_b},
    )
    await db_session.execute(
        text(
            "INSERT INTO master.business_objects"
            " (object_id, tenant_id, object_type, owner_domain, source_system, source_id)"
            " VALUES (:o, :t, 'ORDER', 'sales', 'tenantb-src', 'SO-REG-B-0001')"
        ),
        {"o": b_object, "t": tenant_b},
    )
    await db_session.commit()

    jwt_headers = {"Authorization": f"Bearer {await _login(client, 'manager1')}"}
    resp = await client.get(f"{OBJECTS}/{b_object}", headers=jwt_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"

    listed = await client.get(
        OBJECTS, params={"source_id": "SO-REG-B-0001"}, headers=jwt_headers
    )
    assert listed.status_code == 200
    assert listed.json()["items"] == []


# ---- 7. 无写权限（ANALYST JWT）POST：403 FORBIDDEN ----


async def test_analyst_write_forbidden_403(client: httpx.AsyncClient) -> None:
    jwt_headers = {"Authorization": f"Bearer {await _login(client, 'analyst1')}"}
    resp = await client.post(OBJECTS, json=COMPOSITE, headers=jwt_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    # 无副作用：组合键查询仍为空（读权限本身正常）
    listed = await client.get(
        OBJECTS,
        params={"source_id": COMPOSITE["source_id"]},
        headers=jwt_headers,
    )
    assert listed.status_code == 200
    assert listed.json()["items"] == []
