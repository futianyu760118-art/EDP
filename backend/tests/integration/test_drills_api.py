"""T7 演练记录集成测试（EDP-502 后端）：GET /api/v1/admin/drills 读
drill-records.json（EDP_DRILLS_FILE 可覆盖）→ 三项形状与 executed_at null
透传 + readings dict 结构 / 文件缺失 → {items: []} / 坏 JSON → {items: []}
（不 500）/ 仓库骨架文件可解析（switchover W4 实测值在档）/ 鉴权矩阵
（W5-21-c 收紧后：ADMIN 200；MANAGER/ANALYST 403——quality:run 无此二
角色；SERVICE readonly Key 403、匿名 401）。

造数：tmp_path 临时 JSON（monkeypatch setenv EDP_DRILLS_FILE——不依赖
仓库文件，T14~T16 回填不破坏本测试）；readonly Key 直插（照
test_quality_api 模式）。端点只读无业务写，清场仅临时 Key。
"""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from edp_api.core import db as core_db
from edp_api.core.security.apikey import hash_key
from edp_api.main import create_app
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning"),
]

DRILLS = "/api/v1/admin/drills"
LOGIN = "/api/v1/auth/login"
SEED_PASSWORD = "Admin@123!"

REPO_ROOT = Path(__file__).resolve().parents[3]

READONLY_KEY = "t7-drills-readonly-key"
READONLY_PRINCIPAL = "t7-drills-readonly"

# 临时 JSON 样例：一项已执行（W4 switchover 实测值）+ 两项 PLANNED（null 透传）
SAMPLE_ITEMS = [
    {
        "drill_type": "switchover",
        "executed_at": "2026-09-18T08:19:22+08:00",
        "topology": "etcd×1 + patroni×2 + pgbackrest",
        "rto_seconds": 0,
        "rpo_seconds": 0,
        "result": "SUCCEEDED",
        "readings": {"切换成功率": "2/2", "最长中断": "0s（探测粒度 1s）"},
        "manual_url": "docs/demo/w5-drills.md",
    },
    {
        "drill_type": "pitr",
        "executed_at": None,
        "topology": "etcd×1 + patroni×2 + pgbackrest(repo=MinIO S3)",
        "rto_seconds": None,
        "rpo_seconds": None,
        "result": "PLANNED",
        "readings": {},
        "manual_url": "docs/demo/w5-drills.md",
    },
    {
        "drill_type": "tenant_restore",
        "executed_at": None,
        "topology": "etcd×1 + patroni×2 + pgbackrest(repo=MinIO S3)",
        "rto_seconds": None,
        "rpo_seconds": None,
        "result": "PLANNED",
        "readings": {},
        "manual_url": "docs/demo/w5-drills.md",
    },
]

_ITEM_KEYS = {
    "drill_type",
    "executed_at",
    "topology",
    "rto_seconds",
    "rpo_seconds",
    "result",
    "readings",
    "manual_url",
}


@pytest.fixture
async def client(
    app_role_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> httpx.AsyncClient:
    """ASGI 直连客户端：应用引擎绑定 edp_app 角色（受 RLS），drills
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
async def _clean_readonly_key(
    db_session: AsyncSession,
) -> AsyncIterator[None]:
    """每测试后清场：临时 readonly Key（端点只读无业务写，无需 purge）。"""
    yield
    await db_session.execute(
        text("DELETE FROM platform.api_keys WHERE principal_id = :p"),
        {"p": READONLY_PRINCIPAL},
    )
    await db_session.commit()


async def _login(client: httpx.AsyncClient, username: str) -> dict[str, str]:
    resp = await client.post(
        LOGIN, json={"username": username, "password": SEED_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _write_sample(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, items: list[dict]
) -> Path:
    """写临时 drill-records.json 并 setenv 指向（EDP_DRILLS_FILE 覆盖）。"""
    target = tmp_path / "drill-records.json"
    target.write_text(
        json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setenv("EDP_DRILLS_FILE", str(target))
    return target


# ---- 1. 三项返回 + executed_at null 透传 + readings dict 结构 ----


async def test_drills_items_shape_and_null_passthrough(
    client: httpx.AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_sample(monkeypatch, tmp_path, SAMPLE_ITEMS)
    admin = await _login(client, "admin")  # W5-21-c 收紧：quality:run（ADMIN）
    resp = await client.get(DRILLS, headers=admin)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"items"}
    assert [item["drill_type"] for item in body["items"]] == [
        "switchover",
        "pitr",
        "tenant_restore",
    ]
    assert all(set(item) == _ITEM_KEYS for item in body["items"])
    assert all(isinstance(item["readings"], dict) for item in body["items"])

    by_type = {item["drill_type"]: item for item in body["items"]}
    # 未执行项：executed_at/rto/rpo null 原样透传（PLANNED 态）
    assert by_type["pitr"]["executed_at"] is None
    assert by_type["pitr"]["rto_seconds"] is None
    assert by_type["pitr"]["rpo_seconds"] is None
    assert by_type["pitr"]["result"] == "PLANNED"
    assert by_type["tenant_restore"]["executed_at"] is None
    # 已执行项（W4 实测）：executed_at ISO 字符串 + readings 键值保留
    assert by_type["switchover"]["executed_at"] == "2026-09-18T08:19:22+08:00"
    assert by_type["switchover"]["rto_seconds"] == 0
    assert by_type["switchover"]["result"] == "SUCCEEDED"
    assert by_type["switchover"]["readings"]["切换成功率"] == "2/2"


# ---- 2. 文件缺失 → {items: []}（不报错，前端空态） ----


async def test_drills_missing_file_returns_empty_items(
    client: httpx.AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EDP_DRILLS_FILE", str(tmp_path / "absent.json"))
    admin = await _login(client, "admin")
    resp = await client.get(DRILLS, headers=admin)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"items": []}


# ---- 3. 坏 JSON → {items: []}（不 500） ----


async def test_drills_bad_json_returns_empty_items(
    client: httpx.AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "broken.json"
    target.write_text("{not-json", encoding="utf-8")
    monkeypatch.setenv("EDP_DRILLS_FILE", str(target))
    admin = await _login(client, "admin")
    resp = await client.get(DRILLS, headers=admin)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"items": []}


# ---- 4. 仓库骨架文件可解析（switchover W4 实测值在档，防 schema 漂移） ----


async def test_repo_drill_records_file_parses(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_file = REPO_ROOT / "deploy" / "drills" / "drill-records.json"
    assert repo_file.exists(), "deploy/drills/drill-records.json 骨架应在档"
    monkeypatch.setenv("EDP_DRILLS_FILE", str(repo_file))
    admin = await _login(client, "admin")
    resp = await client.get(DRILLS, headers=admin)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert {item["drill_type"] for item in items} == {
        "switchover",
        "pitr",
        "tenant_restore",
    }
    switchover = next(i for i in items if i["drill_type"] == "switchover")
    assert switchover["result"] == "SUCCEEDED"
    assert switchover["executed_at"] is not None  # W4 实测已回填
    assert switchover["readings"]  # staging-drill.md 摘录读数非空
    # T15b/T15c 实测回填：pitr/tenant_restore 均已执行且有读数
    for dt in ("pitr", "tenant_restore"):
        item = next(i for i in items if i["drill_type"] == dt)
        assert item["result"] == "SUCCEEDED"
        assert item["executed_at"] is not None
        assert item["rto_seconds"] is not None
        assert item["readings"]


# ---- 5. 鉴权矩阵（W5-21-c 收紧后）：ADMIN 200；MANAGER/ANALYST 403；
#         SERVICE readonly Key 403；匿名 401 ----


async def test_auth_matrix(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    default_tenant_id: UUID,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_sample(monkeypatch, tmp_path, SAMPLE_ITEMS)

    # ADMIN（quality:run）→ 200
    admin = await _login(client, "admin")
    allowed = await client.get(DRILLS, headers=admin)
    assert allowed.status_code == 200, allowed.text
    assert len(allowed.json()["items"]) == 3

    # W5-21-c 收紧回归：MANAGER/ANALYST 持 quality:read 不持 quality:run → 403
    for username in ("manager1", "analyst1"):
        denied_user = await _login(client, username)
        denied = await client.get(DRILLS, headers=denied_user)
        assert denied.status_code == 403, f"{username} 应 403：{denied.text}"
        assert denied.json()["error"]["code"] == "FORBIDDEN"

    # SERVICE readonly Key：quality 无 scope 轨道 → 403 FORBIDDEN
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
            "key_hash": hash_key(READONLY_KEY),
            "t": default_tenant_id,
            "principal": READONLY_PRINCIPAL,
            "scopes": ["readonly"],
        },
    )
    await db_session.commit()
    denied = await client.get(DRILLS, headers={"X-API-Key": READONLY_KEY})
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "FORBIDDEN"

    # 匿名 → 401
    assert (await client.get(DRILLS)).status_code == 401
