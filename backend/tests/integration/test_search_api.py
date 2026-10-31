"""W6 T1 全局搜索集成测试：三组聚合命中 / summary 深层命中 / 跨租户 0 行 /
limit 截断 / 空结果空态 / 未认证 401 / 空白 q 400。

造数走 migrator 直插（绕 RLS，等同 test_tenant_isolation 的 B 侧造数方式），
痕迹统一 SO-SRCH-% / srch.% / srch- 前缀收尾清理；应用引擎 =
conftest.app_role_engine（NOBYPASSRLS，与生产 api 同角色）——RLS 隔离在
测试路径真实生效。
"""

from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.core.security.password import hash_password
from edp_api.main import create_app
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

SEARCH = "/api/v1/search"
LOGIN = "/api/v1/auth/login"
DEV_API_KEY = "edp-dev-agent-hub-key"
SEED_PASSWORD = "Admin@123!"

B_SLUG = "tenant-b-srch"
B_PASSWORD = "SearchB@123!"
B_USERNAME = "member1s"

KEY_HEADERS = {"X-API-Key": DEV_API_KEY}

SUMMARY_MARKER = "UNIQSRCHMARKER"


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS），search 路由随
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
async def _clean_search_rows(db_session: AsyncSession) -> None:
    """每测试后清场：删除本模块痕迹（srch-% 证据、srch.% 事件、SO-SRCH-%
    对象、tenant-b-srch 全部数据），保证用例间独立（migrator 绕 RLS）。"""
    yield
    b_ids = f"SELECT tenant_id FROM platform.tenants WHERE slug = '{B_SLUG}'"
    await db_session.execute(
        text("DELETE FROM evidence.records WHERE source_record_id LIKE 'srch-%'")
    )
    await db_session.execute(
        text("DELETE FROM event.events WHERE event_type LIKE 'srch.%'")
    )
    await db_session.execute(
        text("DELETE FROM master.business_objects WHERE source_id LIKE 'SO-SRCH-%'")
    )
    await db_session.execute(
        text("DELETE FROM platform.tenant_usage_daily WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM platform.tenant_members WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM platform.users WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM platform.tenants WHERE slug = '" + B_SLUG + "'")
    )
    await db_session.commit()


async def _default_tenant_id(db_session: AsyncSession) -> UUID:
    return (
        await db_session.execute(
            text("SELECT tenant_id FROM platform.tenants WHERE slug = 'default'")
        )
    ).scalar_one()


async def _seed_rows(
    db_session: AsyncSession, tenant_id: UUID, objects: int = 3
) -> list[UUID]:
    """migrator 直插搜索夹具：SO-SRCH-% 对象 + srch.% 事件两条（其一仅
    summary 可命中）+ srch- 证据一条；返回对象 id 列表。"""
    object_ids: list[UUID] = []
    for seq in range(1, objects + 1):
        object_id = uuid4()
        await db_session.execute(
            text(
                "INSERT INTO master.business_objects"
                " (object_id, tenant_id, object_type, owner_domain, source_system,"
                "  source_id)"
                " VALUES (:o, :t, 'ORDER', 'sales', 'srch-src', :sid)"
            ),
            {"o": object_id, "t": tenant_id, "sid": f"SO-SRCH-{seq:04d}"},
        )
        object_ids.append(object_id)
    await db_session.execute(
        text(
            "INSERT INTO event.events"
            " (event_id, tenant_id, event_type, object_id, source_system,"
            "  occurred_at, data)"
            " VALUES (:e, :t, 'srch.quality.check', :o, 'srch-src',"
            "  '2026-09-20T08:00:01Z', CAST(:data AS JSONB))"
        ),
        {
            "e": uuid4(),
            "t": tenant_id,
            "o": object_ids[0],
            "data": '{"summary": "例行质检通过"}',
        },
    )
    await db_session.execute(
        text(
            "INSERT INTO event.events"
            " (event_id, tenant_id, event_type, object_id, source_system,"
            "  occurred_at, data)"
            " VALUES (:e, :t, 'srch.quality.alert', :o, 'srch-src',"
            "  '2026-09-20T08:00:02Z', CAST(:data AS JSONB))"
        ),
        {
            "e": uuid4(),
            "t": tenant_id,
            "o": object_ids[0],
            "data": f'{{"summary": "{SUMMARY_MARKER} 摘要命中"}}',
        },
    )
    await db_session.execute(
        text(
            "INSERT INTO evidence.records"
            " (evidence_id, tenant_id, source_system, source_record_id, object_id,"
            "  checksum, snapshot, captured_at)"
            " VALUES (:e, :t, 'srch-sys', 'srch-ref-0001', :o, :ck,"
            "  CAST('{}' AS JSONB), '2026-09-20T08:00:03Z')"
        ),
        {"e": uuid4(), "t": tenant_id, "o": object_ids[0], "ck": "sha256:" + "0" * 64},
    )
    await db_session.commit()
    return object_ids


async def _create_tenant_b_user(db_session: AsyncSession) -> UUID:
    """migrator 直造 tenant-b-srch 租户 + 用户 member1s（MANAGER）。"""
    tenant_b, user_b, member_b = (uuid4() for _ in range(3))
    await db_session.execute(
        text(
            "INSERT INTO platform.tenants (tenant_id, slug, name, status)"
            " VALUES (:t, :slug, '搜索隔离租户B', 'ACTIVE')"
        ),
        {"t": tenant_b, "slug": B_SLUG},
    )
    await db_session.execute(
        text(
            "INSERT INTO platform.users"
            " (user_id, tenant_id, username, email, password_hash, display_name,"
            "  principal_type, is_platform_admin, status)"
            " VALUES (:u, :t, :username, 'member1s@tenant-b-srch.local', :pw,"
            "         'B租户搜索用户', 'HUMAN', FALSE, 'ACTIVE')"
        ),
        {"u": user_b, "t": tenant_b, "username": B_USERNAME, "pw": hash_password(B_PASSWORD)},
    )
    await db_session.execute(
        text(
            "INSERT INTO platform.tenant_members"
            " (member_id, tenant_id, user_id, member_roles, status)"
            " VALUES (:m, :t, :u, ARRAY['MANAGER'], 'ACTIVE')"
        ),
        {"m": member_b, "t": tenant_b, "u": user_b},
    )
    await db_session.commit()
    return tenant_b


async def _login(
    client: httpx.AsyncClient,
    username: str,
    password: str = SEED_PASSWORD,
    tenant_slug: str | None = None,
) -> str:
    payload: dict[str, Any] = {"username": username, "password": password}
    if tenant_slug:
        payload["tenant_slug"] = tenant_slug
    resp = await client.post(LOGIN, json=payload)
    assert resp.status_code == 200, resp.text
    return str(resp.json()["access_token"])


async def _jwt_headers(client: httpx.AsyncClient) -> dict[str, str]:
    return {"Authorization": f"Bearer {await _login(client, 'manager1')}"}


# ---- 1. 三组各命中（source_id / event_type / 证据 ref 片段）----


async def test_search_hits_all_three_groups(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_rows(db_session, await _default_tenant_id(db_session))
    resp = await client.get(SEARCH, params={"q": "srch"}, headers=await _jwt_headers(client))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["query"] == "srch"
    assert {item["source_id"] for item in body["objects"]} == {
        "SO-SRCH-0001",
        "SO-SRCH-0002",
        "SO-SRCH-0003",
    }
    assert all(item["object_type"] == "ORDER" for item in body["objects"])
    assert all(item["object_id"] for item in body["objects"])
    assert {item["event_type"] for item in body["events"]} == {
        "srch.quality.check",
        "srch.quality.alert",
    }
    assert [item["source_record_id"] for item in body["evidence"]] == ["srch-ref-0001"]
    assert body["evidence"][0]["source_system"] == "srch-sys"
    assert body["total"] == 6

    # API Key 双轨同权：聚合只读不设资源 scope
    keyed = await client.get(SEARCH, params={"q": "srch"}, headers=KEY_HEADERS)
    assert keyed.status_code == 200, keyed.text
    assert keyed.json()["total"] == 6


# ---- 2. summary 深层命中：event_type 不含 q，仅 data->>'summary' 命中 ----


async def test_search_matches_event_summary(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_rows(db_session, await _default_tenant_id(db_session))
    resp = await client.get(
        SEARCH, params={"q": SUMMARY_MARKER}, headers=await _jwt_headers(client)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["objects"] == []
    assert body["evidence"] == []
    assert [item["event_type"] for item in body["events"]] == ["srch.quality.alert"]
    assert body["total"] == 1


# ---- 3. limit 截断：每组上限独立生效，total = 三组返回行数合计 ----


async def test_search_limit_truncates_each_group(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_rows(db_session, await _default_tenant_id(db_session), objects=6)
    resp = await client.get(
        SEARCH, params={"q": "srch", "limit": 2}, headers=await _jwt_headers(client)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["objects"]) == 2
    assert len(body["events"]) == 2
    assert len(body["evidence"]) == 1
    assert body["total"] == 5


# ---- 4. 无匹配 q：三空数组 + total 0（前端空态依据）----


async def test_search_no_match_returns_empty_state(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_rows(db_session, await _default_tenant_id(db_session))
    resp = await client.get(
        SEARCH, params={"q": "zzz-no-such-hit"}, headers=await _jwt_headers(client)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["objects"] == []
    assert body["events"] == []
    assert body["evidence"] == []
    assert body["total"] == 0


# ---- 5. 跨租户：default 行对 tenant-b-srch 用户 0 可见（RLS）----


async def test_search_cross_tenant_zero_rows(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_rows(db_session, await _default_tenant_id(db_session))
    await _create_tenant_b_user(db_session)
    # 行确实存在（migrator 绕 RLS 计数）
    total_objects = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM master.business_objects"
                " WHERE source_id LIKE 'SO-SRCH-%'"
            )
        )
    ).scalar_one()
    assert total_objects == 3

    b_headers = {
        "Authorization": f"Bearer {await _login(client, B_USERNAME, B_PASSWORD, B_SLUG)}"
    }
    resp = await client.get(SEARCH, params={"q": "srch"}, headers=b_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["objects"] == []
    assert body["events"] == []
    assert body["evidence"] == []
    assert body["total"] == 0

    # default 用户同查询仍全量命中（对照）
    a_resp = await client.get(
        SEARCH, params={"q": "srch"}, headers=await _jwt_headers(client)
    )
    assert a_resp.status_code == 200, a_resp.text
    assert a_resp.json()["total"] == 6


# ---- 6. 未认证 401 ----


async def test_search_unauthenticated_401(client: httpx.AsyncClient) -> None:
    bare = await client.get(SEARCH, params={"q": "srch"})
    assert bare.status_code == 401
    assert bare.json()["error"]["code"] == "UNAUTHENTICATED"

    forged = await client.get(
        SEARCH, params={"q": "srch"}, headers={"Authorization": "Bearer forged.jwt.here"}
    )
    assert forged.status_code == 401


# ---- 7. q 缺失 / 空串 / 空白：400 ----


async def test_search_blank_q_400(client: httpx.AsyncClient) -> None:
    headers = await _jwt_headers(client)
    missing = await client.get(SEARCH, headers=headers)
    assert missing.status_code == 400, missing.text
    assert missing.json()["error"]["code"] == "VALIDATION_ERROR"
    for blank in ("", "   "):
        resp = await client.get(SEARCH, params={"q": blank}, headers=headers)
        assert resp.status_code == 400, resp.text
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
