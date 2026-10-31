"""T12 health/ops_metrics 集成测试（B.13 子集）：事件流页 KPI 真数据源
+ W6 扩展 5 字段（backup/audit_events_7d/policy_hits_today/
adapters_success_rate/evidence_valid_rate——总览页 KPI 真数据源）。

覆盖：
1. 基础字段齐备/类型：status/db/outbox_pending/last_sync/version +
   ops_metrics 六键（字段名对齐 MSW ``HealthResponse.ops_metrics``）；
   空租户基线全 0；非 deep 响应无 db_ha（response_model_exclude_none）；
2. events_24h 随 batch 插入递增；ingest_peak_24h 同小时桶 = 新增数；
3. idempotency_hit_rate 在 batch 重放（新 Key → event_id 幂等）后 = 0.5 > 0；
4. dlq 在 outbox FAILED 后 +1（migrator 直改状态）；
5. deep=true：DEV Key（SERVICE，无 audit:read）→ 403 FORBIDDEN；admin JWT
   （ADMIN 角色集含 audit:read）→ 200 且 db_ha={primary, lag 0, replicas 0}；
6. 无凭据 → 401；
7. demo seed 后 KPI 真数据：events_24h = fetched + accepted、
   p95_latency_ms > 0（seed 确定性回填 60~299ms）、last_sync 含
   erp-demo/plm-demo 且 ISO 可解析；
8. W6 五字段：seed 后非空态（backup 取最近备份相关演练 / audit 7d 窗 /
   policy_hits 当日窗 / adapter_sync 最近 20 成功率 / recheck checksum
   派生率）+ 空库缺失态（backup 无 drills 记录 → 无该键、adapters/
   evidence 无任务 → 无该键、两计数 0 仍在）。

偏差留痕（T9 评审遗留，本轮不修，T14 契约清单）：归档命中（同
Idempotency-Key）不累加 duplicated → hit_rate 漏该路径；P95 口径 =
「函数入口 → INSERT 前」（见 health/service.py docstring）。

会话形态：应用引擎 = conftest.app_role_engine（edp_app，FORCE RLS）；造数/
断言经 migrator db_session 直查（绕 RLS）。清场：purge_tenant_business_data
（逆依赖序）+ 本模块审计行（actor=agent-hub/adapter:erp）。
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.main import create_app
from edp_api.modules.demo import service as demo_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

BASE = "/api/v1/health"
OBJECTS = "/api/v1/objects"
EVENTS = "/api/v1/events"
LOGIN = "/api/v1/auth/login"
DEV_KEY = "edp-dev-agent-hub-key"
DEV_HEADERS = {"X-API-Key": DEV_KEY}
SEED_PASSWORD = "Admin@123!"

OPS_KEYS = {
    "events_24h",
    "ingest_peak_24h",
    "p95_latency_ms",
    "idempotency_hit_rate",
    "dlq",
    "evidence_count",
}
INT_METRICS = ("events_24h", "ingest_peak_24h", "p95_latency_ms", "dlq", "evidence_count")


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS），health 路由随
    create_app 装配。"""
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


async def _purge(db_session: AsyncSession, tenant_id: UUID) -> None:
    """清 default 租户业务行（含 seed 全量）+ 本模块审计行（migrator 绕 RLS）。"""
    await demo_service.purge_tenant_business_data(db_session, tenant_id)
    await db_session.execute(
        text(
            "DELETE FROM platform.audit_logs WHERE tenant_id = :t"
            " AND actor_id IN ('agent-hub', 'adapter:erp')"
        ),
        {"t": tenant_id},
    )
    await db_session.commit()


@pytest.fixture(autouse=True)
async def _clean_health_rows(
    db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    """每测试前后清场：KPI 断言依赖空租户基线（前清防他模块残留）。"""
    await _purge(db_session, default_tenant_id)
    yield
    await _purge(db_session, default_tenant_id)


async def _create_objects(client: httpx.AsyncClient, count: int) -> list[str]:
    """经 API Key 注册 count 个对象（source_id=SO-HLT-000n），返回 object_id。"""
    ids: list[str] = []
    for seq in range(1, count + 1):
        resp = await client.post(
            OBJECTS,
            json={
                "object_type": "ORDER",
                "owner_domain": "sales",
                "source_system": "erp",
                "source_id": f"SO-HLT-{seq:04d}",
                "attributes": {"seq": seq},
            },
            headers=DEV_HEADERS,
        )
        assert resp.status_code == 201, resp.text
        ids.append(resp.json()["object_id"])
    return ids


def _event(object_id: str, seq: int) -> dict[str, Any]:
    return {
        "event_type": "evt.health.created",
        "object_id": object_id,
        "source_system": "agent-hub",
        "occurred_at": f"2026-09-14T08:00:{seq:02d}Z",
        "actor_type": "AI",
        "actor_id": "agent:test",
        "data": {"seq": seq},
    }


def _batch(object_ids: list[str]) -> dict[str, Any]:
    return {"events": [_event(oid, seq) for seq, oid in enumerate(object_ids, 1)]}


def _key() -> str:
    return f"idem-hlt-{uuid4()}"


def _key_headers(key: str) -> dict[str, str]:
    return {**DEV_HEADERS, "Idempotency-Key": key}


async def _login(client: httpx.AsyncClient, username: str) -> dict[str, str]:
    resp = await client.post(
        LOGIN, json={"username": username, "password": SEED_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _health(
    client: httpx.AsyncClient, headers: dict[str, str] | None = None
) -> dict[str, Any]:
    resp = await client.get(BASE, headers=headers or DEV_HEADERS)
    assert resp.status_code == 200, resp.text
    return resp.json()

# ---- 1. 基础字段齐备/类型 + 空租户基线 ----


async def test_health_basic_shape(
    client: httpx.AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # W6 扩展 backup 派生自 drills 文件：指向缺失路径 → 无该键（确定性）
    monkeypatch.setenv("EDP_DRILLS_FILE", str(tmp_path / "absent-drills.json"))
    body = await _health(client)
    assert body["status"] == "OK"
    assert body["db"] == "OK"
    assert body["version"] == "2.0.0"
    assert body["outbox_pending"] == 0
    assert body["last_sync"] == {}
    assert "db_ha" not in body  # 仅 deep=true 返回

    metrics = body["ops_metrics"]
    assert OPS_KEYS <= set(metrics)  # W6 起 5 可选字段按数据出现
    assert "backup" not in metrics  # 无 drills 记录 → 缺失态
    for key in INT_METRICS:
        assert isinstance(metrics[key], int), key
        assert metrics[key] == 0, key
    assert metrics["idempotency_hit_rate"] == 0.0


# ---- 2. events_24h / ingest_peak_24h 随 batch 插入递增 ----


async def test_events_24h_increments_with_batch(client: httpx.AsyncClient) -> None:
    object_ids = await _create_objects(client, 3)
    assert (await _health(client))["ops_metrics"]["events_24h"] == 0

    resp = await client.post(
        EVENTS + "/batch", json=_batch(object_ids), headers=_key_headers(_key())
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["accepted"] == 3

    metrics = (await _health(client))["ops_metrics"]
    assert metrics["events_24h"] == 3
    assert metrics["ingest_peak_24h"] == 3  # 3 条同落一个当前小时桶
    assert metrics["p95_latency_ms"] >= 0
    assert metrics["dlq"] == 0


# ---- 3. idempotency_hit_rate：新 Key 重放（event_id 幂等）后 > 0 ----


async def test_idempotency_hit_rate_after_replay(client: httpx.AsyncClient) -> None:
    object_ids = await _create_objects(client, 3)
    batch = _batch(object_ids)
    first = await client.post(
        EVENTS + "/batch", json=batch, headers=_key_headers(_key())
    )
    assert first.json()["accepted"] == 3

    replay = await client.post(
        EVENTS + "/batch", json=batch, headers=_key_headers(_key())
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == {
        "accepted": 0,
        "duplicated": 3,
        "rejected": 0,
        "deduplicated": False,
    }

    metrics = (await _health(client))["ops_metrics"]
    assert metrics["events_24h"] == 3  # 无新行
    assert metrics["idempotency_hit_rate"] == pytest.approx(0.5)  # 3/(3+3)
    assert metrics["idempotency_hit_rate"] > 0


# ---- 4. dlq 随 outbox FAILED +1 ----


async def test_dlq_increments_after_outbox_failed(
    client: httpx.AsyncClient, db_session: AsyncSession, default_tenant_id: UUID
) -> None:
    object_ids = await _create_objects(client, 1)
    key = _key()
    resp = await client.post(
        EVENTS + "/batch", json=_batch(object_ids), headers=_key_headers(key)
    )
    assert resp.json()["accepted"] == 1
    assert (await _health(client))["ops_metrics"]["dlq"] == 0

    await db_session.execute(
        text(
            "UPDATE event.outbox SET status = 'FAILED' WHERE tenant_id = :t"
            " AND aggregate_id IN (SELECT event_id FROM event.events"
            "                      WHERE idempotency_key LIKE :k)"
        ),
        {"t": default_tenant_id, "k": f"{key}:%"},
    )
    await db_session.commit()

    metrics = (await _health(client))["ops_metrics"]
    assert metrics["dlq"] == 1


# ---- 5. deep=true：audit:read 门禁（SERVICE 403 / ADMIN 200 + db_ha） ----


async def test_deep_requires_audit_read(client: httpx.AsyncClient) -> None:
    resp = await client.get(BASE, params={"deep": "true"}, headers=DEV_HEADERS)
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    headers = await _login(client, "admin")
    resp = await client.get(BASE, params={"deep": "true"}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["db_ha"] == {
        "role": "primary",
        "replication_lag_mb": 0,
        "replicas": 0,
    }

    # 非 deep 不返回 db_ha（exclude_none）
    assert "db_ha" not in (await _health(client, headers))


# ---- 6. 无凭据 → 401（tenant_scoped） ----


async def test_unauthenticated_401(client: httpx.AsyncClient) -> None:
    resp = await client.get(BASE)
    assert resp.status_code == 401, resp.text
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


# ---- 7. demo seed 后 KPI 真数据 ----


async def test_health_after_demo_seed(
    client: httpx.AsyncClient, app_role_engine: AsyncEngine, default_tenant_id: UUID
) -> None:
    stats = await demo_service.seed(app_role_engine, default_tenant_id)
    assert stats.failed == 0
    assert stats.events_accepted > 0

    body = await _health(client)
    metrics = body["ops_metrics"]
    assert metrics["events_24h"] == stats.fetched + stats.events_accepted
    assert metrics["evidence_count"] >= stats.fetched
    assert metrics["p95_latency_ms"] > 0  # seed 确定性回填 60~299ms
    assert metrics["ingest_peak_24h"] >= 1
    assert metrics["dlq"] == 0
    assert metrics["idempotency_hit_rate"] == 0.0  # 首跑全新增

    assert set(body["last_sync"]) == {"erp-demo", "plm-demo"}
    for value in body["last_sync"].values():
        assert datetime.fromisoformat(value).tzinfo is not None


# ---- 8. W6 扩展 5 字段：seed 非空态 + 空库缺失态 ----

_BACKUP_DRILLS = {
    "items": [
        {
            "drill_type": "pitr",
            "executed_at": "2026-09-21T03:00:00+00:00",
            "topology": "etcd×1 + patroni×2",
            "rto_seconds": 22.1,
            "rpo_seconds": 0,
            "result": "SUCCEEDED",
            "readings": {"恢复备份集": "20260921-025634F"},
            "manual_url": "docs/demo/w5-drills.md",
        },
        {
            # 更新的非备份演练（HA）：不应被 backup 选中
            "drill_type": "switchover",
            "executed_at": "2026-09-21T05:00:00+00:00",
            "topology": "etcd×1 + patroni×2",
            "rto_seconds": 0,
            "rpo_seconds": 0,
            "result": "SUCCEEDED",
            "readings": {"切换成功率": "2/2"},
            "manual_url": "docs/demo/w5-drills.md",
        },
        {
            # 最新备份相关演练：backup 应取此项
            "drill_type": "tenant_restore",
            "executed_at": "2026-09-21T05:11:21+00:00",
            "topology": "etcd×1 + patroni×2",
            "rto_seconds": 23.8,
            "rpo_seconds": 0,
            "result": "SUCCEEDED",
            "readings": {"增量备份": "20260921-025634F_20260921-051115I"},
            "manual_url": "docs/demo/w5-drills.md",
        },
    ]
}


async def _purge_w6_rows(db_session: AsyncSession, tenant_id: UUID) -> None:
    """W6 用例专用清场：本模块审计行 + ops.tasks 行（前清保空基线确定性）。"""
    await db_session.execute(
        text("DELETE FROM platform.audit_logs WHERE tenant_id = :t"),
        {"t": tenant_id},
    )
    await db_session.execute(
        text("DELETE FROM ops.tasks WHERE tenant_id = :t"),
        {"t": tenant_id},
    )
    await db_session.commit()


async def _insert_audit_row(
    db_session: AsyncSession,
    tenant_id: UUID,
    *,
    occurred_at: datetime,
    with_policy_hits: bool = False,
) -> None:
    detail = {"policy_hits": [str(uuid4())]} if with_policy_hits else {"note": "plain"}
    await db_session.execute(
        text(
            """
            INSERT INTO platform.audit_logs
                (tenant_id, actor_type, actor_id, action, resource_type,
                 resource_id, detail, occurred_at)
            VALUES (:t, 'SERVICE', 'test:ops-metrics', 'EVENT_CREATE', 'events',
                    NULL, CAST(:detail AS jsonb), :occurred_at)
            """
        ),
        {
            "t": tenant_id,
            "detail": json.dumps(detail),
            "occurred_at": occurred_at,
        },
    )


async def _insert_task_row(
    db_session: AsyncSession,
    tenant_id: UUID,
    *,
    task_type: str,
    status: str,
    scope: str | None,
    stats: dict[str, Any],
    created_at: datetime,
) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO ops.tasks
                (task_id, tenant_id, task_type, status, scope, stats, logs,
                 created_at, updated_at)
            VALUES (:task_id, :t, :task_type, :status, :scope,
                    CAST(:stats AS jsonb), '[]'::jsonb, :created_at, :created_at)
            """
        ),
        {
            "task_id": uuid4(),
            "t": tenant_id,
            "task_type": task_type,
            "status": status,
            "scope": scope,
            "stats": json.dumps(stats),
            "created_at": created_at,
        },
    )


async def test_ops_metrics_w6_five_fields_seeded(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drills = tmp_path / "drill-records.json"
    drills.write_text(json.dumps(_BACKUP_DRILLS), encoding="utf-8")
    monkeypatch.setenv("EDP_DRILLS_FILE", str(drills))
    await _purge_w6_rows(db_session, default_tenant_id)

    now = datetime.now(UTC)
    # audit：7d 窗内 2 行（1 今日含 policy_hits + 1 前日含 hits）+ 窗外 1 行
    await _insert_audit_row(
        db_session,
        default_tenant_id,
        occurred_at=now - timedelta(hours=1),
        with_policy_hits=True,
    )
    await _insert_audit_row(
        db_session,
        default_tenant_id,
        occurred_at=now - timedelta(days=2),
        with_policy_hits=True,
    )
    await _insert_audit_row(
        db_session,
        default_tenant_id,
        occurred_at=now - timedelta(days=8),
        with_policy_hits=True,
    )
    # ops.tasks：adapter_sync 25 条（最旧 5 条 SUCCEEDED 在窗口外，最近 20
    # = 19 FAILED + 1 SUCCEEDED → 0.05，钉住「最近 20」窗口）
    for i in range(25):
        await _insert_task_row(
            db_session,
            default_tenant_id,
            task_type="adapter_sync",
            status="SUCCEEDED" if i < 5 or i == 24 else "FAILED",
            scope=None,
            stats={},
            created_at=now - timedelta(hours=50 - i),  # i 大 = 新
        )
    # quality_recheck：ALL（含 checksum 段，sampled=4/failed=1 → 0.75）
    # + 更新的 ORPHAN（无 checksum 段，被 scope 过滤跳过——仍取 ALL 行）
    await _insert_task_row(
        db_session,
        default_tenant_id,
        task_type="quality_recheck",
        status="SUCCEEDED",
        scope="ALL",
        stats={"checksum": {"sampled": 4, "failed": 1}},
        created_at=now - timedelta(hours=3),
    )
    await _insert_task_row(
        db_session,
        default_tenant_id,
        task_type="quality_recheck",
        status="SUCCEEDED",
        scope="ORPHAN",
        stats={"orphans": {"event_orphans": 0, "evidence_orphans": 0}},
        created_at=now - timedelta(hours=1),
    )
    await db_session.commit()

    metrics = (await _health(client))["ops_metrics"]
    assert metrics["backup"] == {
        "last_backup_at": "2026-09-21T05:11:21+00:00",
        "status": "SUCCEEDED",
        "source": "drills",
    }
    assert metrics["audit_events_7d"] == 2  # 8d 前行不计
    assert metrics["policy_hits_today"] == 1  # 前日命中不计
    assert metrics["adapters_success_rate"] == pytest.approx(0.05)
    assert metrics["evidence_valid_rate"] == pytest.approx(0.75)

    await _purge_w6_rows(db_session, default_tenant_id)


async def test_ops_metrics_w6_five_fields_empty(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EDP_DRILLS_FILE", str(tmp_path / "absent-drills.json"))
    await _purge_w6_rows(db_session, default_tenant_id)

    metrics = (await _health(client))["ops_metrics"]
    # 计数型：0 是合法值仍出现
    assert metrics["audit_events_7d"] == 0
    assert metrics["policy_hits_today"] == 0
    # 无数据 → 缺失态（response_model_exclude_none）
    assert "backup" not in metrics
    assert "adapters_success_rate" not in metrics
    assert "evidence_valid_rate" not in metrics
    assert set(metrics) == OPS_KEYS | {"audit_events_7d", "policy_hits_today"}
