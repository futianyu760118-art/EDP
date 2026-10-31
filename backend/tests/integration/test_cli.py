"""T15 管道 CLI 集成测试：以子进程运行 python -m edp_api.modules.ingest.cli，
断言退出码与 stdout 摘要——full 注册 60 / reconcile 零偏差 / incremental
注册 8 / 删一条证据后 reconcile 偏差 exit 1 / 未知租户 exit 2。

连接注入：EDP_DATABASE_URL = app_database_url（edp_app 角色，RLS 生效——
管道必须走应用角色）。清场与 test_pipeline 同口径（erp mock 痕迹，测试
前后各清一次，用例自包含互不依赖、可独立运行）。
"""

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.integration]

BACKEND_DIR = Path(__file__).resolve().parents[2]
CLI_MODULE = "edp_api.modules.ingest.cli"
CLI_TIMEOUT_SECONDS = 300

_BO_SCOPE = "(source_id LIKE 'SO-2026-%' OR source_id LIKE 'C-1%' OR source_id LIKE 'M-3%')"
_EV_SCOPE = (
    "(source_record_id LIKE 'SO-2026-%' OR source_record_id LIKE 'C-1%'"
    " OR source_record_id LIKE 'M-3%')"
)


@pytest.fixture
def cli_runner(
    migrated_db: str, app_database_url: str
) -> Callable[..., subprocess.CompletedProcess[str]]:
    """子进程跑 CLI：EDP_DATABASE_URL 注入 edp_app URL（RLS 生效）。"""

    def _run(*args: str) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "EDP_DATABASE_URL": app_database_url,
            "PYTHONIOENCODING": "utf-8",
        }
        return subprocess.run(
            [sys.executable, "-m", CLI_MODULE, *args],
            cwd=str(BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CLI_TIMEOUT_SECONDS,
            check=False,
        )

    return _run


async def _clean_pipeline_rows(db_session: AsyncSession) -> None:
    """清 erp mock 痕迹（与 test_pipeline 同口径；migrator 绕 RLS）。"""
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
    await db_session.commit()


@pytest.fixture(autouse=True)
async def _clean_around_test(db_session: AsyncSession) -> None:
    """每测试前后各清一次：前清保证独立（前序文件残留），后清不留痕。"""
    await _clean_pipeline_rows(db_session)
    yield
    await _clean_pipeline_rows(db_session)


# ---- 1. full：exit 0，stdout 摘要 fetched=60 / registered=60 ----


def test_cli_full_registers_60(cli_runner: Callable[..., subprocess.CompletedProcess[str]]) -> None:
    result = cli_runner("full")
    assert result.returncode == 0, result.stderr
    assert "fetched=60" in result.stdout
    assert "registered=60" in result.stdout


# ---- 2. reconcile（full + incremental 后）：exit 0，三行全 ok、偏差行数 0 ----
#
# reconcile 的源全集 = BASE+DELTA（68 条记录级），full 仅落 BASE 60——
# 需 incremental 补齐 DELTA 后源-库一致才零偏差（T14 对账语义）。


def test_cli_reconcile_zero_deviation_after_full(
    cli_runner: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    assert cli_runner("full").returncode == 0
    assert cli_runner("incremental").returncode == 0
    result = cli_runner("reconcile")
    assert result.returncode == 0, result.stderr
    assert "偏差行数 0 / 共 3 行" in result.stdout
    assert "False" not in result.stdout


# ---- 3. incremental（full 后）：水位推进 → fetched=8 / registered=8 ----


def test_cli_incremental_registers_8(
    cli_runner: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    assert cli_runner("full").returncode == 0
    result = cli_runner("incremental")
    assert result.returncode == 0, result.stderr
    assert "fetched=8" in result.stdout
    assert "registered=8" in result.stdout


# ---- 4. 破坏：migrator 删 1 行证据 → reconcile exit 1、偏差行数 1 ----


async def test_cli_reconcile_exits_1_on_missing_evidence(
    cli_runner: Callable[..., subprocess.CompletedProcess[str]], db_session: AsyncSession
) -> None:
    assert cli_runner("full").returncode == 0
    deleted = (
        await db_session.execute(
            text(
                "DELETE FROM evidence.records WHERE source_record_id = 'SO-2026-00201#v1'"
            )
        )
    ).rowcount
    await db_session.commit()
    assert deleted == 1

    result = cli_runner("reconcile")
    assert result.returncode == 1
    assert "偏差行数 1 / 共 3 行" in result.stdout
    assert "False" in result.stdout


# ---- 5. 未知租户 slug → exit 2 ----


def test_cli_unknown_tenant_exits_2(
    cli_runner: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    result = cli_runner("reconcile", "--tenant-slug", "no-such-tenant")
    assert result.returncode == 2
    assert "租户不存在" in result.stderr
