"""T10 决策案例最小版集成测试（EDP-018）：创建/列表/详情 + Human-Only Guard。

覆盖：
1. 创建 201：case_no DC-YYYYMMDD-NNN 格式、CASE links（重复 evidence_id 幂等
   只建一条）、context.source_event_id 落库、created_by=服务主体；
2. source_id 事件不存在 / evidence_ids 证据不存在 → 400 VALIDATION_ERROR
   且案例创建同事务回滚（0 残留）；
3. 列表（status/risk_level 过滤）与详情（evidence_refs checksum/source_system
   + decisions 空）；列表不填充 total；
4. SERVICE 主体 POST records → 403 GUARD_POLICY_DENIED + GUARD_DENIED 审计
   （resource_type=decision.records，独立会话提交）且案例仍 OPEN、0 记录；
5. HUMAN（manager1 JWT，MANAGER 含 decision:decide）POST records → 201 +
   案例 DECIDED/decided_at + decided_by=用户 id；
6. 重复决策 → 409 CONFLICT；
7. HUMAN 无 decision:decide（analyst1）读 200 / 决策 403 FORBIDDEN；
8. 跨租户：tenant-decisions 读 default 案例 → 详情 404 / 列表空；
9. SERVICE 无 write:decision scope 创建 → 403 FORBIDDEN。

会话形态：应用引擎 = conftest.app_role_engine（edp_app，FORCE RLS）；断言以
migrator db_session 直查（绕 RLS）。清场：purge_tenant_business_data（逆依赖
序，与 seed 复位同一实现）+ 本模块审计行/临时 Key/tenant-decisions。
"""

import re
from uuid import UUID, uuid4

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.core.errors import EdpError, ErrorCode
from edp_api.core.security.apikey import hash_key
from edp_api.core.security.principal import Principal
from edp_api.main import create_app
from edp_api.modules.audit.aspect import install_audit_aspect
from edp_api.modules.decisions import service as decisions_service
from edp_api.modules.decisions.schemas import DecisionCreateRequest
from edp_api.modules.demo import service as demo_service
from edp_api.modules.demo.dataset import DEMO_CASE
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

BASE = "/api/v1/decisions"
DEV_KEY = "edp-dev-agent-hub-key"
DEV_HEADERS = {"X-API-Key": DEV_KEY}
LOGIN = "/api/v1/auth/login"
SEED_PASSWORD = "Admin@123!"

# 无 write:decision scope 的临时 API Key（403 用例；每测试自行插入/清场）
NO_SCOPE_KEY = "t10-decisions-no-scope-key"
NO_SCOPE_PRINCIPAL = "t10-decisions-no-scope"

# 跨租户用例的 B 租户（migrator 直造；readonly Key）
TENANT_B_SLUG = "tenant-decisions"
TENANT_B_KEY = "t10-decisions-tenant-b-key"
TENANT_B_PRINCIPAL = "t10-decisions-tenant-b"


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS），decisions 路由
    随 create_app 装配（含 GUARD_DENIED 独立会话路径）。"""
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
    """ORM 写（案例/记录/links）依赖切面落审计——与 create_app 同一装配。"""
    install_audit_aspect()


@pytest.fixture
async def demo(
    app_role_engine: AsyncEngine, default_tenant_id: UUID
) -> demo_service.SeedStats:
    """default 租户演示数据集（T7 seed 等价路径）；清场见 _clean_decisions_rows。"""
    stats = await demo_service.seed(app_role_engine, default_tenant_id)
    assert stats.failed == 0
    return stats


@pytest.fixture(autouse=True)
async def _clean_decisions_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    """每测试后清场：default 业务行（含 seed 全量）+ 本模块审计行/临时 Key/
    tenant-decisions（migrator 绕 RLS；audit_logs 仅追加约束只作用于 edp_app）。"""
    yield
    await demo_service.purge_tenant_business_data(db_session, default_tenant_id)
    manager1_id = (
        await db_session.execute(
            text("SELECT user_id FROM platform.users WHERE username = 'manager1'")
        )
    ).scalar_one()
    await db_session.execute(
        text(
            "DELETE FROM platform.audit_logs WHERE tenant_id = :t"
            " AND (actor_id IN ('adapter:erp', 'agent-hub', :manager1)"
            "      OR (action = 'GUARD_DENIED'"
            "          AND resource_type = 'decision.records'))"
        ),
        {"t": default_tenant_id, "manager1": str(manager1_id)},
    )
    b_ids = "SELECT tenant_id FROM platform.tenants WHERE slug = 'tenant-decisions'"
    await db_session.execute(
        text("DELETE FROM platform.api_keys WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM platform.api_keys WHERE principal_id = :p"),
        {"p": NO_SCOPE_PRINCIPAL},
    )
    await db_session.execute(
        text("DELETE FROM platform.tenant_members WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text("DELETE FROM platform.users WHERE tenant_id IN (" + b_ids + ")")
    )
    await db_session.execute(
        text(
            "DELETE FROM platform.tenant_usage_daily WHERE tenant_id IN"
            " (SELECT tenant_id FROM platform.tenants WHERE slug = 'tenant-decisions')"
        )
    )
    await db_session.execute(
        text("DELETE FROM platform.tenants WHERE slug = 'tenant-decisions'")
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
    """直插临时 API Key（照 test_tools 模式；hash_key 与生产同实现）。"""
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


async def _login(client: httpx.AsyncClient, username: str) -> dict[str, str]:
    resp = await client.post(
        LOGIN, json={"username": username, "password": SEED_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed_case_id(db_session: AsyncSession, tenant_id: UUID) -> UUID:
    return (
        await db_session.execute(
            text("SELECT case_id FROM decision.cases WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
    ).scalar_one()


async def _order_event_id(
    db_session: AsyncSession, tenant_id: UUID, order_no: str
) -> UUID:
    return (
        await db_session.execute(
            text(
                "SELECT event_id FROM event.events WHERE tenant_id = :t"
                " AND event_type = 'capability.result.order_risk'"
                " AND data->>'order_no' = :order_no"
            ),
            {"t": tenant_id, "order_no": order_no},
        )
    ).scalar_one()


async def _evidence_ids(
    db_session: AsyncSession, tenant_id: UUID, limit: int = 2
) -> list[UUID]:
    rows = await db_session.execute(
        text(
            "SELECT evidence_id FROM evidence.records WHERE tenant_id = :t"
            " ORDER BY captured_at DESC, evidence_id DESC LIMIT :n"
        ),
        {"t": tenant_id, "n": limit},
    )
    return [row[0] for row in rows]


# ---- 1. 创建 201：case_no 格式 + links 幂等 + context.source_event_id ----


async def test_create_case_201_case_no_and_links(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    event_id = await _order_event_id(db_session, default_tenant_id, "SO-2026-00124")
    e1, e2 = await _evidence_ids(db_session, default_tenant_id)

    resp = await client.post(
        f"{BASE}/cases",
        headers=DEV_HEADERS,
        json={
            "question": "订单 SO-2026-00124 是否调整交期？",
            "context": {"order_amount": 80000, "source_event_id": str(event_id)},
            "options": [
                {"key": "CONFIRM", "label": "确认交期"},
                {"key": "REJECT", "label": "拒绝建议"},
            ],
            "risk_level": "P2",
            "source_type": "capability.result",
            "source_id": str(event_id),
            "evidence_ids": [str(e1), str(e2), str(e2)],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    UUID(body["case_id"])
    assert re.fullmatch(r"DC-\d{8}-\d{3}", body["case_no"])
    assert body["status"] == "OPEN"
    assert body["created_at"]

    row = (
        await db_session.execute(
            text(
                "SELECT case_no, context, options, risk_level, source_type,"
                " source_id, status, created_by"
                " FROM decision.cases WHERE case_id = :c"
            ),
            {"c": body["case_id"]},
        )
    ).one()
    assert row.case_no == body["case_no"]
    assert row.context["source_event_id"] == str(event_id)
    assert [option["key"] for option in row.options] == ["CONFIRM", "REJECT"]
    assert row.risk_level == "P2"
    assert row.source_type == "capability.result"
    assert row.source_id == str(event_id)
    assert row.status == "OPEN"
    assert row.created_by == "agent-hub"

    # links 幂等：重复 evidence_id 只建一条
    link_count = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM evidence.links WHERE tenant_id = :t"
                " AND ref_type = 'CASE' AND ref_id = :c"
            ),
            {"t": default_tenant_id, "c": body["case_id"]},
        )
    ).scalar_one()
    assert link_count == 2


# ---- 1b. seed 案例创建经 decisions 服务落审计（T7 评审 Important 回归） ----


async def test_seed_case_creation_is_audited(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    """seed 的案例/links 走 ORM（切面审计）——不再是无审计的 raw SQL 直写。"""
    case_audits = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM platform.audit_logs"
                " WHERE tenant_id = :t AND actor_id = 'adapter:erp'"
                " AND action = 'CASE_CREATE'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one()
    assert case_audits == 1

    case_link_audits = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM platform.audit_logs"
                " WHERE tenant_id = :t AND actor_id = 'adapter:erp'"
                " AND action = 'LINKS_CREATE'"
                " AND detail->'after'->>'ref_type' = 'CASE'"
            ),
            {"t": default_tenant_id},
        )
    ).scalar_one()
    assert case_link_audits == 3


# ---- 2. source_id 事件 / evidence_ids 证据不存在 → 400 + 回滚 ----


async def test_create_case_rejects_missing_source_event_and_evidence(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    resp = await client.post(
        f"{BASE}/cases",
        headers=DEV_HEADERS,
        json={
            "question": "不存在的源事件",
            "source_type": "capability.result",
            "source_id": str(uuid4()),
        },
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    resp = await client.post(
        f"{BASE}/cases",
        headers=DEV_HEADERS,
        json={"question": "不存在的证据", "evidence_ids": [str(uuid4())]},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    # 两次失败创建均同事务回滚：仅剩 seed 场景 2 案例
    case_count = (
        await db_session.execute(
            text("SELECT count(*) FROM decision.cases WHERE tenant_id = :t"),
            {"t": default_tenant_id},
        )
    ).scalar_one()
    assert case_count == 1


# ---- 3. 列表过滤 + 详情（evidence_refs + decisions） ----


async def test_list_and_detail(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    case_id = await _seed_case_id(db_session, default_tenant_id)

    resp = await client.get(
        f"{BASE}/cases", params={"status": "OPEN"}, headers=DEV_HEADERS
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 列表路由 exclude_none：无更多页时 next_cursor 键缺省（等价 null）；
    # Page.total 仅 events 填充，本列表不外溢
    assert body.get("next_cursor") is None
    assert "total" not in body
    assert [item["case_id"] for item in body["items"]] == [str(case_id)]
    item = body["items"][0]
    assert re.fullmatch(r"DC-\d{8}-\d{3}", item["case_no"])
    assert item["risk_level"] == "P1"
    assert item["status"] == "OPEN"

    for params in ({"status": "DECIDED"}, {"risk_level": "P0"}):
        filtered = await client.get(f"{BASE}/cases", params=params, headers=DEV_HEADERS)
        assert filtered.status_code == 200, filtered.text
        assert filtered.json()["items"] == []

    resp = await client.get(f"{BASE}/cases/{case_id}", headers=DEV_HEADERS)
    assert resp.status_code == 200, resp.text
    detail = resp.json()
    assert detail["case_id"] == str(case_id)
    assert detail["question"] == DEMO_CASE.question
    assert detail["context"]["order_amount"] == 120000
    assert detail["context"]["material_gap"] == 1000
    assert detail["context"]["source_event_id"]
    assert [option["key"] for option in detail["options"]] == [
        "EXPEDITE",
        "SUBSTITUTE",
        "REJECT",
    ]
    assert detail["risk_level"] == "P1"
    assert detail["status"] == "OPEN"
    assert detail["decisions"] == []
    assert len(detail["evidence_refs"]) == 3
    for ref in detail["evidence_refs"]:
        UUID(ref["evidence_id"])
        assert ref["checksum"].startswith("sha256:")
        # 场景 2 证据链：源快照（erp/plm）+ 结果证据（agent-hub，T9 回流自动落）
        assert ref["source_system"] in {"erp", "plm", "agent-hub"}

    db_refs = (
        (
            await db_session.execute(
                text(
                    "SELECT evidence_id FROM evidence.links WHERE tenant_id = :t"
                    " AND ref_type = 'CASE' AND ref_id = :c"
                ),
                {"t": default_tenant_id, "c": case_id},
            )
        )
        .scalars()
        .all()
    )
    assert {str(ref) for ref in db_refs} == {
        ref["evidence_id"] for ref in detail["evidence_refs"]
    }


# ---- 4. SERVICE POST records → 403 GUARD_POLICY_DENIED + 审计 ----


async def test_service_submit_record_guard_denied_and_audited(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    case_id = await _seed_case_id(db_session, default_tenant_id)

    resp = await client.post(
        f"{BASE}/cases/{case_id}/records",
        headers=DEV_HEADERS,
        json={"chosen_option": "EXPEDITE", "comment": "AI 尝试决策"},
    )
    assert resp.status_code == 403, resp.text
    error = resp.json()["error"]
    assert error["code"] == "GUARD_POLICY_DENIED"
    assert error["message"] == "该操作仅限人工执行"

    rows = (
        (
            await db_session.execute(
                text(
                    "SELECT actor_type, actor_id, resource_type, resource_id, detail"
                    " FROM platform.audit_logs"
                    " WHERE action = 'GUARD_DENIED'"
                    " AND resource_type = 'decision.records'"
                    " AND actor_id = 'agent-hub'"
                )
            )
        )
        .mappings()
        .all()
    )
    assert len(rows) == 1
    assert rows[0]["actor_type"] == "SERVICE"
    assert rows[0]["resource_id"] == str(case_id)
    assert rows[0]["detail"]["reason"] == "Human-Only"
    assert rows[0]["detail"]["path"] == f"{BASE}/cases/{case_id}/records"

    # 守卫先于写：案例仍 OPEN、0 决策记录
    assert (
        await db_session.execute(
            text("SELECT status FROM decision.cases WHERE case_id = :c"),
            {"c": case_id},
        )
    ).scalar_one() == "OPEN"
    assert (
        await db_session.execute(
            text("SELECT count(*) FROM decision.records WHERE tenant_id = :t"),
            {"t": default_tenant_id},
        )
    ).scalar_one() == 0


# ---- 5. HUMAN POST records → 201 + 案例 DECIDED ----


async def test_human_submit_record_decides_case(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    case_id = await _seed_case_id(db_session, default_tenant_id)
    headers = await _login(client, "manager1")

    resp = await client.post(
        f"{BASE}/cases/{case_id}/records",
        headers=headers,
        json={
            "chosen_option": "EXPEDITE",
            "decision_type": "HUMAN",
            "comment": "同意，优先保交付",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    UUID(body["decision_id"])
    assert body["case_id"] == str(case_id)
    assert body["case_status"] == "DECIDED"
    assert body["decision_time"]

    user_id = (
        await db_session.execute(
            text("SELECT user_id FROM platform.users WHERE username = 'manager1'")
        )
    ).scalar_one()
    record = (
        await db_session.execute(
            text(
                "SELECT chosen_option, decision_type, decided_by, comment"
                " FROM decision.records WHERE decision_id = :d"
            ),
            {"d": body["decision_id"]},
        )
    ).one()
    assert record.chosen_option == "EXPEDITE"
    assert record.decision_type == "HUMAN"
    assert record.decided_by == str(user_id)
    assert record.comment == "同意，优先保交付"

    case = (
        await db_session.execute(
            text(
                "SELECT status, decided_at FROM decision.cases WHERE case_id = :c"
            ),
            {"c": case_id},
        )
    ).one()
    assert case.status == "DECIDED"
    assert case.decided_at is not None

    # 切面审计消歧回归（Important-1）：decision.records → DECISION_CREATE，
    # 不得再与 evidence.records 的 EVIDENCE_CREATE 混名
    decision_audits = (
        (
            await db_session.execute(
                text(
                    "SELECT action FROM platform.audit_logs"
                    " WHERE resource_id = :r"
                ),
                {"r": str(body["decision_id"])},
            )
        )
        .scalars()
        .all()
    )
    assert "DECISION_CREATE" in decision_audits
    assert "EVIDENCE_CREATE" not in decision_audits


# ---- 5b. 服务层守卫直调（不经 HTTP 依赖）→ 独立会话审计 + GUARD_POLICY_DENIED ----


async def test_direct_service_guard_denied_is_audited(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    """直调 decisions_service.submit_record（SERVICE 主体）同样拒绝留痕：
    审计走独立会话提交，不随被拒调用方事务回滚（Minor-2 行为直证）。"""
    case_id = uuid4()
    principal = Principal(id="agent-direct", kind="SERVICE", tenant_id=default_tenant_id)

    with pytest.raises(EdpError) as ei:
        await decisions_service.submit_record(
            db_session,
            principal,
            case_id,
            DecisionCreateRequest(chosen_option="EXPEDITE"),
        )
    assert ei.value.code == ErrorCode.GUARD_POLICY_DENIED
    assert ei.value.message == "该操作仅限人工执行"

    rows = (
        (
            await db_session.execute(
                text(
                    "SELECT actor_id, detail FROM platform.audit_logs"
                    " WHERE action = 'GUARD_DENIED'"
                    " AND resource_type = 'decision.records'"
                    " AND resource_id = :r"
                ),
                {"r": str(case_id)},
            )
        )
        .mappings()
        .all()
    )
    assert len(rows) == 1
    assert rows[0]["actor_id"] == "agent-direct"
    assert rows[0]["detail"]["reason"] == "Human-Only"
    assert rows[0]["detail"]["path"] is None


# ---- 6. 重复决策 → 409 CONFLICT ----


async def test_repeat_decision_conflict_409(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    case_id = await _seed_case_id(db_session, default_tenant_id)
    headers = await _login(client, "manager1")
    payload = {"chosen_option": "EXPEDITE"}

    first = await client.post(
        f"{BASE}/cases/{case_id}/records", headers=headers, json=payload
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        f"{BASE}/cases/{case_id}/records",
        headers=headers,
        json={"chosen_option": "REJECT"},
    )
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "CONFLICT"

    # 仅一条决策记录
    assert (
        await db_session.execute(
            text("SELECT count(*) FROM decision.records WHERE tenant_id = :t"),
            {"t": default_tenant_id},
        )
    ).scalar_one() == 1


# ---- 7. HUMAN 权限轨道：analyst1 读 200 / 决策 403 ----


async def test_analyst_read_ok_but_decide_forbidden(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    case_id = await _seed_case_id(db_session, default_tenant_id)
    headers = await _login(client, "analyst1")

    resp = await client.get(f"{BASE}/cases", headers=headers)
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["items"]) == 1

    resp = await client.post(
        f"{BASE}/cases/{case_id}/records",
        headers=headers,
        json={"chosen_option": "EXPEDITE"},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"


# ---- 7b. HUMAN 权限轨道：analyst1 创建案例 → 403（无 decision:decide） ----


async def test_analyst_create_case_forbidden(client: httpx.AsyncClient) -> None:
    headers = await _login(client, "analyst1")

    resp = await client.post(
        f"{BASE}/cases", headers=headers, json={"question": "无权限创建"}
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"


# ---- 8. 跨租户：tenant-decisions 读 default 案例 = 404/空 ----


async def test_cross_tenant_not_leaked(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    demo: demo_service.SeedStats,
) -> None:
    case_id = await _seed_case_id(db_session, default_tenant_id)
    tenant_b = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO platform.tenants (tenant_id, slug, name, status)"
            " VALUES (:t, :slug, '租户DecisionsB', 'ACTIVE')"
        ),
        {"t": tenant_b, "slug": TENANT_B_SLUG},
    )
    await db_session.commit()
    await _insert_api_key(
        db_session,
        tenant_b,
        key=TENANT_B_KEY,
        principal_id=TENANT_B_PRINCIPAL,
        scopes=["readonly"],
    )
    headers = {"X-API-Key": TENANT_B_KEY}

    resp = await client.get(f"{BASE}/cases/{case_id}", headers=headers)
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "NOT_FOUND"

    resp = await client.get(f"{BASE}/cases", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []


# ---- 9. SERVICE 无 write:decision scope → 403 FORBIDDEN ----


async def test_create_case_requires_write_decision_scope(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
) -> None:
    await _insert_api_key(
        db_session,
        default_tenant_id,
        key=NO_SCOPE_KEY,
        principal_id=NO_SCOPE_PRINCIPAL,
        scopes=["readonly"],
    )

    resp = await client.post(
        f"{BASE}/cases",
        headers={"X-API-Key": NO_SCOPE_KEY},
        json={"question": "无权限创建"},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"
