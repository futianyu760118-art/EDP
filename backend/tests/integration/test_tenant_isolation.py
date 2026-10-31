"""T14 跨租户隔离矩阵（EDP-022 收口）：JWT × API Key × 资源全组合。

fixture：双租户——default（0005 种子：manager1 / dev API Key）+ tenant-b
（migrator 直造：用户 member1b、API Key 'tenant-b-key'、1 对象 + 2 事件）。
A 侧对象/事件经 API（A-Key）创建以携带 outbox 轨迹（history 用例），
B 侧直插（migrator 绕 RLS，等同 test_events 跨租户用例的造数方式）。

矩阵：读隔离（404/空列表，不泄露存在性）/ 写隔离（跨租户 object_id →
rejected、同自然键各自成对象）/ RLS 层直证（edp_app 绑 A 后 B 数据 0 可见）/
SUSPENDED 状态墙（Key 全接口 + JWT 登录 403，还原即恢复）/ 幂等键跨租户
同 Key（0007 复合 PK 回归：双方各自存档重放不串）/ 历史轨迹隔离 /
无凭据与坏凭据 401。

关于 JWT claims 篡改（手动用同一 secret 签 tenant_id=B 的 token）：该场景
等价于签名密钥泄露，属密钥管理域而非隔离层缺陷——RLS 绑定与 claims 一致
时数据面仍按绑定租户过滤，不会越权读到未授权租户的数据，超出 W1 隔离层
验证范围，此处不设用例（W2 密钥轮换/审计立项时补）。

应用引擎 = conftest.app_role_engine（NOBYPASSRLS，与生产 api 同角色）——
RLS 隔离在测试路径真实生效。
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.core.db import bind_tenant
from edp_api.core.security.apikey import hash_key
from edp_api.core.security.password import hash_password
from edp_api.main import create_app
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

LOGIN = "/api/v1/auth/login"
OBJECTS = "/api/v1/objects"
EVENTS = "/api/v1/events"

A_API_KEY = "edp-dev-agent-hub-key"
B_API_KEY = "tenant-b-key"
B_SLUG = "tenant-b"
B_PASSWORD = "TenantB@123!"
SEED_PASSWORD = "Admin@123!"

A_KEY_HEADERS = {"X-API-Key": A_API_KEY}
B_KEY_HEADERS = {"X-API-Key": B_API_KEY}

# B 对象的自然键（写隔离用例：A 以同键注册应各自成对象，uq_bo_natural_key
# 含 tenant_id 前导列，天然允许）
B_COMPOSITE: dict[str, str] = {
    "object_type": "ORDER",
    "source_system": "tenantb-src",
    "source_id": "SO-ISO-SHARED-0001",
}


@dataclass
class World:
    """双租户夹具数据（每测试独立重建，migrator 视角全量可见）。"""

    tenant_a: UUID
    tenant_b: UUID
    a_object: str  # default 租户对象（A-Key 经 API 创建，含 OBJECT_UPSERT 轨迹）
    b_object: str  # tenant-b 对象（migrator 直插）
    b_event_count: int = 2  # B 对象下预置事件数（写隔离"不落库"断言基线）


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS），registry/events
    路由随 create_app 装配。"""
    await core_db.dispose_engine()
    monkeypatch.setattr(core_db, "get_engine", lambda: app_role_engine)
    transport = httpx.ASGITransport(app=create_app())
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        await core_db.dispose_engine()  # 重置绑定到测试引擎的会话工厂


@pytest.fixture(autouse=True)
async def _clean_isolation_rows(db_session: AsyncSession) -> None:
    """每测试后清场：删除本模块痕迹（SO-ISO-% 对象、idem-iso-% 事件与幂等键、
    tenant-b 全部数据），保证用例间独立（migrator 绕 RLS）。"""
    yield
    b_ids = "SELECT tenant_id FROM platform.tenants WHERE slug = 'tenant-b'"
    await db_session.execute(
        text(
            "DELETE FROM event.outbox WHERE tenant_id IN (" + b_ids + ")"
            " OR aggregate_id IN"
            " (SELECT object_id FROM master.business_objects WHERE source_id LIKE 'SO-ISO-%')"
            " OR aggregate_id IN"
            " (SELECT event_id FROM event.events WHERE idempotency_key LIKE 'idem-iso-%')"
        )
    )
    await db_session.execute(
        text(
            "DELETE FROM event.events WHERE tenant_id IN (" + b_ids + ")"
            " OR idempotency_key LIKE 'idem-iso-%'"
        )
    )
    await db_session.execute(
        text(
            "DELETE FROM platform.idempotency_keys WHERE key LIKE 'idem-iso-%'"
            " OR tenant_id IN (" + b_ids + ")"
        )
    )
    await db_session.execute(
        text(
            "DELETE FROM master.business_objects WHERE source_id LIKE 'SO-ISO-%'"
            " OR tenant_id IN (" + b_ids + ")"
        )
    )
    await db_session.execute(
        text("DELETE FROM platform.api_keys WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM platform.tenant_members WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM platform.users WHERE tenant_id IN (" + b_ids + ")")
    )
    # T9：tenant-b 经 API 批量入库会累加 tenant_usage_daily（FK 引用 tenants）
    await db_session.execute(
        text("DELETE FROM platform.tenant_usage_daily WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM platform.tenants WHERE slug = 'tenant-b'")
    )
    await db_session.commit()


@pytest.fixture
async def world(client: httpx.AsyncClient, db_session: AsyncSession) -> World:
    """双租户世界：tenant-b 由 migrator 直造（绕 RLS）；A 侧对象 + 2 事件经
    API（A-Key）创建以携带 outbox 轨迹。"""
    tenant_a: UUID = (
        await db_session.execute(
            text("SELECT tenant_id FROM platform.tenants WHERE slug = 'default'")
        )
    ).scalar_one()
    tenant_b, user_b, member_b, key_b_id, b_object = (uuid4() for _ in range(5))
    b_events = [uuid4(), uuid4()]

    await db_session.execute(
        text(
            "INSERT INTO platform.tenants (tenant_id, slug, name, status)"
            " VALUES (:t, 'tenant-b', '租户B', 'ACTIVE')"
        ),
        {"t": tenant_b},
    )
    await db_session.execute(
        text(
            "INSERT INTO platform.users"
            " (user_id, tenant_id, username, email, password_hash, display_name,"
            "  principal_type, is_platform_admin, status)"
            " VALUES (:u, :t, 'member1b', 'member1b@tenant-b.local', :pw,"
            "         'B租户管理员', 'HUMAN', FALSE, 'ACTIVE')"
        ),
        {"u": user_b, "t": tenant_b, "pw": hash_password(B_PASSWORD)},
    )
    await db_session.execute(
        text(
            "INSERT INTO platform.tenant_members"
            " (member_id, tenant_id, user_id, member_roles, status)"
            " VALUES (:m, :t, :u, ARRAY['MANAGER'], 'ACTIVE')"
        ),
        {"m": member_b, "t": tenant_b, "u": user_b},
    )
    await db_session.execute(
        text(
            "INSERT INTO platform.api_keys"
            " (key_id, key_hash, tenant_id, principal_type, principal_id, scopes, status)"
            " VALUES (:k, :kh, :t, 'SERVICE', 'agent-b',"
            "         ARRAY['readonly','write:event','write:registry'], 'ACTIVE')"
        ),
        {"k": key_b_id, "kh": hash_key(B_API_KEY), "t": tenant_b},
    )
    await db_session.execute(
        text(
            "INSERT INTO master.business_objects"
            " (object_id, tenant_id, object_type, owner_domain, source_system, source_id)"
            " VALUES (:o, :t, 'ORDER', 'sales', 'tenantb-src', 'SO-ISO-SHARED-0001')"
        ),
        {"o": b_object, "t": tenant_b},
    )
    for event_id in b_events:
        await db_session.execute(
            text(
                "INSERT INTO event.events"
                " (event_id, tenant_id, event_type, object_id, source_system,"
                "  occurred_at, data)"
                " VALUES (:e, :t, 'iso.tenantb.created', :o, 'tenantb-src', now(),"
                "         CAST(:data AS JSONB))"
            ),
            {"e": event_id, "t": tenant_b, "o": b_object, "data": '{"who": "b"}'},
        )
    await db_session.commit()

    # A 侧经 API：对象（revision=1 + OBJECT_UPSERT 轨迹）与 2 事件
    created = await client.post(
        OBJECTS,
        json={
            "object_type": "ORDER",
            "owner_domain": "sales",
            "source_system": "iso-a-src",
            "source_id": "SO-ISO-A-0001",
            "attributes": {"who": "a"},
        },
        headers=A_KEY_HEADERS,
    )
    assert created.status_code == 201, created.text
    a_object = created.json()["object_id"]
    seeded = await client.post(
        EVENTS + "/batch",
        json={"events": [_event(a_object, 1), _event(a_object, 2)]},
        headers=_a_key_headers(f"idem-iso-a-seed-{uuid4()}"),
    )
    assert seeded.status_code == 200, seeded.text
    assert seeded.json()["accepted"] == 2

    return World(
        tenant_a=tenant_a, tenant_b=tenant_b, a_object=a_object, b_object=str(b_object)
    )


# ---- 造数与登录辅助 ----


def _event(object_id: str, seq: int, who: str = "a") -> dict[str, Any]:
    """批次事件项（occurred_at 秒位=seq 保证批次内 event_id 互异）。"""
    return {
        "event_type": f"iso.{who}.created",
        "object_id": object_id,
        "source_system": "agent-hub" if who == "a" else "tenantb-src",
        "occurred_at": f"2026-09-14T09:00:{seq:02d}Z",
        "actor_type": "AI" if who == "a" else "SERVICE",
        "actor_id": f"agent:{who}",
        "data": {"who": who, "seq": seq},
    }


def _a_key_headers(idem_key: str | None = None) -> dict[str, str]:
    headers = dict(A_KEY_HEADERS)
    if idem_key is not None:
        headers["Idempotency-Key"] = idem_key
    return headers


def _b_key_headers(idem_key: str | None = None) -> dict[str, str]:
    headers = dict(B_KEY_HEADERS)
    if idem_key is not None:
        headers["Idempotency-Key"] = idem_key
    return headers


async def _login_a(client: httpx.AsyncClient) -> str:
    resp = await client.post(
        LOGIN, json={"username": "manager1", "password": SEED_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


async def _login_b(client: httpx.AsyncClient) -> str:
    resp = await client.post(
        LOGIN,
        json={"username": "member1b", "password": B_PASSWORD, "tenant_slug": B_SLUG},
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


async def _set_tenant_status(
    db_session: AsyncSession, tenant_id: UUID, status: str
) -> None:
    await db_session.execute(
        text("UPDATE platform.tenants SET status = :status WHERE tenant_id = :tid"),
        {"status": status, "tid": tenant_id},
    )
    await db_session.commit()


# ---- 1. 读隔离：A 凭据读 B 资源 = 不存在（404 / 空列表，不泄露存在性） ----


async def test_read_isolation_jwt(world: World, client: httpx.AsyncClient) -> None:
    jwt_headers = {"Authorization": f"Bearer {await _login_a(client)}"}

    own = await client.get(f"{OBJECTS}/{world.a_object}", headers=jwt_headers)
    assert own.status_code == 200, own.text
    assert own.json()["object_id"] == world.a_object

    blocked = await client.get(f"{OBJECTS}/{world.b_object}", headers=jwt_headers)
    assert blocked.status_code == 404
    assert blocked.json()["error"]["code"] == "NOT_FOUND"

    listed = await client.get(
        EVENTS, params={"object_id": world.b_object}, headers=jwt_headers
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"] == []


async def test_read_isolation_api_key(world: World, client: httpx.AsyncClient) -> None:
    own = await client.get(f"{OBJECTS}/{world.a_object}", headers=A_KEY_HEADERS)
    assert own.status_code == 200, own.text

    blocked = await client.get(f"{OBJECTS}/{world.b_object}", headers=A_KEY_HEADERS)
    assert blocked.status_code == 404
    assert blocked.json()["error"]["code"] == "NOT_FOUND"

    listed = await client.get(
        EVENTS, params={"object_id": world.b_object}, headers=A_KEY_HEADERS
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"] == []


# ---- 2. 写隔离：跨租户 object_id → rejected 不落库；同自然键各自成对象 ----


async def test_write_isolation(
    world: World, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # A-Key 批次引用 B 的 object_id：RLS 下与"不存在"同义 → rejected，不整批失败
    resp = await client.post(
        EVENTS + "/batch",
        json={"events": [_event(world.b_object, 1)]},
        headers=_a_key_headers(f"idem-iso-x-{uuid4()}"),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["accepted"] == 0
    assert body["rejected"] == 1
    assert body["errors"][0]["index"] == 0
    assert "不存在" in body["errors"][0]["message"]
    # 不落库：B 对象下事件数不变（仍为 B 自己的预置事件）
    b_rows = (
        await db_session.execute(
            text("SELECT count(*) FROM event.events WHERE object_id = :oid"),
            {"oid": world.b_object},
        )
    ).scalar_one()
    assert b_rows == world.b_event_count

    # A-Key 以 B 的自然键注册对象：成功且属 A（新 object_id）
    created = await client.post(
        OBJECTS,
        json={**B_COMPOSITE, "owner_domain": "sales", "attributes": {"who": "a"}},
        headers=A_KEY_HEADERS,
    )
    assert created.status_code == 201, created.text
    a_new = created.json()["object_id"]
    assert a_new != world.b_object

    # B-JWT 查同自然键：只见 B 自己的对象，看不到 A 的同名对象
    b_jwt = {"Authorization": f"Bearer {await _login_b(client)}"}
    b_listed = await client.get(
        OBJECTS,
        params={
            "object_type": B_COMPOSITE["object_type"],
            "source_system": B_COMPOSITE["source_system"],
            "source_id": B_COMPOSITE["source_id"],
        },
        headers=b_jwt,
    )
    assert b_listed.status_code == 200, b_listed.text
    items = b_listed.json()["items"]
    assert [item["object_id"] for item in items] == [world.b_object]


# ---- 3. RLS 层直证：edp_app 角色绑定 A 后，B 数据 0 可见 ----


async def test_rls_direct_proof(world: World, app_session: AsyncSession) -> None:
    await bind_tenant(app_session, world.tenant_a)

    b_events = (
        await app_session.execute(
            text("SELECT count(*) FROM event.events WHERE tenant_id = :b"),
            {"b": world.tenant_b},
        )
    ).scalar_one()
    assert b_events == 0

    event_tenants = {
        row[0]
        for row in (
            await app_session.execute(text("SELECT DISTINCT tenant_id FROM event.events"))
        ).all()
    }
    assert event_tenants == {world.tenant_a}

    object_tenants = {
        row[0]
        for row in (
            await app_session.execute(
                text("SELECT DISTINCT tenant_id FROM master.business_objects")
            )
        ).all()
    }
    assert object_tenants == {world.tenant_a}


# ---- 4. SUSPENDED 状态墙：B-Key 全接口 + B-JWT 登录 403，还原即恢复 ----


async def test_suspended_tenant_blocked_and_restored(
    world: World, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    try:
        await _set_tenant_status(db_session, world.tenant_b, "SUSPENDED")

        blocked_list = await client.get(OBJECTS, headers=B_KEY_HEADERS)
        assert blocked_list.status_code == 403
        assert blocked_list.json()["error"]["code"] == "TENANT_SUSPENDED"

        blocked_ingest = await client.post(
            EVENTS + "/batch",
            json={"events": [_event(world.b_object, 1, who="b")]},
            headers=_b_key_headers(f"idem-iso-s-{uuid4()}"),
        )
        assert blocked_ingest.status_code == 403
        assert blocked_ingest.json()["error"]["code"] == "TENANT_SUSPENDED"

        blocked_login = await client.post(
            LOGIN,
            json={
                "username": "member1b",
                "password": B_PASSWORD,
                "tenant_slug": B_SLUG,
            },
        )
        assert blocked_login.status_code == 403
        assert blocked_login.json()["error"]["code"] == "TENANT_SUSPENDED"
    finally:
        await _set_tenant_status(db_session, world.tenant_b, "ACTIVE")

    restored_list = await client.get(OBJECTS, headers=B_KEY_HEADERS)
    assert restored_list.status_code == 200, restored_list.text
    assert [item["object_id"] for item in restored_list.json()["items"]] == [
        world.b_object
    ]

    restored_login = await client.post(
        LOGIN,
        json={"username": "member1b", "password": B_PASSWORD, "tenant_slug": B_SLUG},
    )
    assert restored_login.status_code == 200, restored_login.text


# ---- 5. 幂等键跨租户同 Key（0007 复合 PK 回归，T12 Concern #3） ----


async def test_idempotency_same_key_cross_tenant(
    world: World, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """A 与 B 用相同 Idempotency-Key 各自 POST（不同内容）→ 双方 200 各自正常
    计数（旧全局 PK 下 B 侧存档丢失/冲突）；A 重放 → deduplicated 且内容仍是
    A 的（批次规模互异使"串档"可探测）。"""
    key = f"idem-iso-shared-{uuid4()}"
    a_batch = {"events": [_event(world.a_object, 3), _event(world.a_object, 4)]}
    b_batch = {"events": [_event(world.b_object, 1, who="b")]}

    a1 = await client.post(
        EVENTS + "/batch", json=a_batch, headers=_a_key_headers(key)
    )
    assert a1.status_code == 200, a1.text
    assert a1.json()["accepted"] == 2

    b1 = await client.post(
        EVENTS + "/batch", json=b_batch, headers=_b_key_headers(key)
    )
    assert b1.status_code == 200, b1.text
    assert b1.json() == {
        "accepted": 1,
        "duplicated": 0,
        "rejected": 0,
        "deduplicated": False,
    }

    # A 重放：deduplicated 且存档内容仍是 A 的（accepted=2 ≠ B 的 1，不串档）
    a2 = await client.post(
        EVENTS + "/batch", json=a_batch, headers=_a_key_headers(key)
    )
    assert a2.status_code == 200, a2.text
    assert a2.json() == {**a1.json(), "deduplicated": True}

    # B 重放：同样 deduplicated 且是 B 自己的存档
    b2 = await client.post(
        EVENTS + "/batch", json=b_batch, headers=_b_key_headers(key)
    )
    assert b2.status_code == 200, b2.text
    assert b2.json() == {**b1.json(), "deduplicated": True}

    # 登记面：同 key 字符串两行、租户各异（复合 PK 成立的物理证据）
    archived_tenants = {
        row[0]
        for row in (
            await db_session.execute(
                text("SELECT tenant_id FROM platform.idempotency_keys WHERE key = :k"),
                {"k": key},
            )
        ).all()
    }
    assert archived_tenants == {world.tenant_a, world.tenant_b}


# ---- 6. 历史轨迹隔离：A 只见 A 的 actor；B 对象 history = 404 ----


async def test_history_isolation(world: World, client: httpx.AsyncClient) -> None:
    jwt_headers = {"Authorization": f"Bearer {await _login_a(client)}"}

    own = await client.get(f"{OBJECTS}/{world.a_object}/history", headers=jwt_headers)
    assert own.status_code == 200, own.text
    revisions = own.json()["revisions"]
    assert len(revisions) == 1  # world 内恰好一次创建（revision=1）
    assert revisions[0]["revision"] == 1
    assert revisions[0]["actor_id"] == "agent-hub"  # 全为 A 的 actor

    blocked = await client.get(
        f"{OBJECTS}/{world.b_object}/history", headers=jwt_headers
    )
    assert blocked.status_code == 404
    assert blocked.json()["error"]["code"] == "NOT_FOUND"


# ---- 7. 无凭据 / 坏凭据：401 UNAUTHENTICATED ----


async def test_missing_and_garbage_credentials(client: httpx.AsyncClient) -> None:
    bare = await client.get(OBJECTS)
    assert bare.status_code == 401
    assert bare.json()["error"]["code"] == "UNAUTHENTICATED"

    forged = await client.get(OBJECTS, headers={"Authorization": "Bearer forged.jwt.here"})
    assert forged.status_code == 401
    assert forged.json()["error"]["code"] == "UNAUTHENTICATED"

    bare_events = await client.get(EVENTS)
    assert bare_events.status_code == 401
    assert bare_events.json()["error"]["code"] == "UNAUTHENTICATED"
