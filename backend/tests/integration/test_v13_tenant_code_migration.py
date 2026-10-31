"""V1.3 集成测试：0020 迁移语义（租户编码自动生成——计数表 + 存量重写）。

覆盖（设计 docs/superpowers/specs/2026-10-16-tenant-code-autogen-design.md）：
1. 计数表存在且 edp_app 可 upsert-returning 原子取号（service.
   next_tenant_code 同款 SQL）；
2. 存量重写：旧格式行按年分组确定性编号 ten-YYYY-NNNN、legacy_slug
   备份、default 锚点不动、已是新格式行幂等跳过、撞号顺延；
3. 计数表回填各年最大序号；
4. downgrade 精确还原 legacy_slug；
5. 取号跨年重置与 5 位溢出（直接操作计数表造高压序号）。

重放方式：造存量后 alembic downgrade 0019 → upgrade head（编程式，
与 conftest.migrated_db 同法）；测试收尾自清存量行并保证库在 head。
"""

import asyncio
import os
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from edp_api.modules.tenantmgmt.service import next_tenant_code
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.integration]

BACKEND_DIR = Path(__file__).resolve().parents[2]
CODE_PATTERN = r"ten-\d{4}-\d{4,}"

_TENANT_COLUMNS = (
    "INSERT INTO platform.tenants"
    " (tenant_id, slug, name, plan, status, created_at, updated_at)"
    " VALUES (:tid, :slug, :name, 'TRIAL', 'ACTIVE', :created, :created)"
)


async def _insert_tenant(
    db_session: AsyncSession, slug: str, name: str, year: int, day: int
) -> str:
    tenant_id = uuid4()
    await db_session.execute(
        text(_TENANT_COLUMNS),
        {
            "tid": tenant_id,
            "slug": slug,
            "name": name,
            "created": datetime(year, 6, day, tzinfo=UTC),
        },
    )
    await db_session.commit()
    return str(tenant_id)


async def _slugs_of(db_session: AsyncSession, tenant_id: str) -> tuple[str, bool]:
    """(当前 slug, 是否携带 legacy_slug)。"""
    row = (
        await db_session.execute(
            text(
                "SELECT slug, attributes ? 'legacy_slug' AS backed"
                " FROM platform.tenants WHERE tenant_id = :tid"
            ),
            {"tid": tenant_id},
        )
    ).mappings().one()
    return row["slug"], row["backed"]


@pytest.fixture
async def stock_tenants(db_session: AsyncSession) -> AsyncIterator[dict[str, str]]:
    """造存量：2025 两个旧格式 + 2026 两个旧格式 + 预置一个新格式行
    （ten-2025-0001，撞号防御位）+ default（种子已有）。created_at 同年
    内各异日（迁移按 (created_at, tenant_id) 排序，同刻随机 UUID 使排序
    不可复现）。

    前置清场：删除全部非 default 租户——其他模块可能残留直插的旧格式
    租户行，若不清，迁移重放会将其一并重写，计数表反填与断言被污染
    （且其原按 slug 的清场此后永远失配）。收尾全清本模块行。"""
    for table in (
        "tenant_members",
        "users",
        "tenant_quotas",
        "tenant_usage_daily",
    ):
        await db_session.execute(
            text(
                "DELETE FROM platform." + table + " WHERE tenant_id IN"
                " (SELECT tenant_id FROM platform.tenants WHERE slug <> 'default')"
            )
        )
    await db_session.execute(
        text("DELETE FROM platform.tenants WHERE slug <> 'default'")
    )
    await db_session.commit()
    ids = {
        "y25a": await _insert_tenant(db_session, "legacy-erp", "存量ERP", 2025, 1),
        "y25b": await _insert_tenant(db_session, "legacy-mes", "存量MES", 2025, 2),
        "y26a": await _insert_tenant(db_session, "pilot-x", "试点X", 2026, 1),
        "y26b": await _insert_tenant(db_session, "acme", "Acme", 2026, 2),
        "preset": await _insert_tenant(
            db_session, "ten-2025-0001", "预置新格式", 2025, 3
        ),
    }
    yield ids
    for tenant_id in ids.values():
        await db_session.execute(
            text("DELETE FROM platform.tenants WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
    # 清掉本模块回填的计数行（表可能因断言中断停在 0019——先判存在再删：
    # DELETE 目标表在计划期即须存在，WHERE 内 to_regclass 守卫无效）
    seq_exists = (
        await db_session.execute(
            text("SELECT to_regclass('platform.tenant_code_seq')")
        )
    ).scalar()
    if seq_exists is not None:
        await db_session.execute(
            text(
                "DELETE FROM platform.tenant_code_seq WHERE year IN (2025, 2026)"
            )
        )
    await db_session.commit()


def _alembic(database_url: str, command_name: str, revision: str) -> None:
    """同步 alembic command 包装（环境变量注入 database_url）。

    env.py 为异步——内部 asyncio.run()，在 pytest-asyncio 事件循环内直接
    调用会 RuntimeError；调用方经 asyncio.to_thread 在无循环线程中执行。
    """
    env_key = "EDP_DATABASE_URL"
    saved = os.environ.get(env_key)
    os.environ[env_key] = database_url
    try:
        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
        if command_name == "downgrade":
            command.downgrade(cfg, revision)
        else:
            command.upgrade(cfg, revision)
    finally:
        if saved is None:
            os.environ.pop(env_key, None)
        else:
            os.environ[env_key] = saved


async def _replay_0020(database_url: str) -> None:
    """downgrade 0019 → upgrade head：重放 0020（造数已 commit 可见）。"""
    await asyncio.to_thread(
        _alembic, database_url, "downgrade", "0019_v13_adapter_config"
    )
    await asyncio.to_thread(_alembic, database_url, "upgrade", "head")


async def test_0020_counter_table_and_atomic_draw(
    db_session: AsyncSession,
) -> None:
    """计数表建成；upsert-returning 连续取号不重号（next_tenant_code 原子性）。"""
    year = 2098  # 独立年份隔离计数表状态
    try:
        codes = [await next_tenant_code(db_session, year) for _ in range(3)]
        assert codes == [f"ten-{year}-0001", f"ten-{year}-0002", f"ten-{year}-0003"]
        last = (
            await db_session.execute(
                text("SELECT last_no FROM platform.tenant_code_seq WHERE year = :y"),
                {"y": year},
            )
        ).scalar_one()
        assert last == 3
        await db_session.rollback()  # 取号回滚即让号（不留空洞语义）
        emptied = (
            await db_session.execute(
                text("SELECT count(*) FROM platform.tenant_code_seq WHERE year = :y"),
                {"y": year},
            )
        ).scalar_one()
        assert emptied == 0
    finally:
        await db_session.rollback()
        await db_session.execute(
            text("DELETE FROM platform.tenant_code_seq WHERE year = :y"), {"y": year}
        )
        await db_session.commit()


async def test_0020_stock_rewrite_semantics(
    db_session: AsyncSession, stock_tenants: dict[str, str], database_url: str
) -> None:
    """存量重写：按年分组编号 / legacy 备份 / default 不动 / 新格式幂等 /
    撞号顺延 + 计数表回填。"""
    await _replay_0020(database_url)

    # 2025 组：预置行占 ten-2025-0001 → 存量从 0002 起（撞号顺延）
    slug, backed = await _slugs_of(db_session, stock_tenants["y25a"])
    assert slug == "ten-2025-0002"
    assert backed
    slug_b, backed_b = await _slugs_of(db_session, stock_tenants["y25b"])
    assert slug_b == "ten-2025-0003"
    assert backed_b
    preset_slug, preset_backed = await _slugs_of(db_session, stock_tenants["preset"])
    assert preset_slug == "ten-2025-0001"  # 已是新格式：幂等跳过、无备份
    assert not preset_backed

    # 2026 组：独立年段从 0001 起（按年重置）
    slug_x, _ = await _slugs_of(db_session, stock_tenants["y26a"])
    assert slug_x == "ten-2026-0001"
    slug_acme, _ = await _slugs_of(db_session, stock_tenants["y26b"])
    assert slug_acme == "ten-2026-0002"

    # default 锚点不动
    default = (
        await db_session.execute(
            text("SELECT slug FROM platform.tenants WHERE slug = 'default'")
        )
    ).scalar_one_or_none()
    assert default == "default"

    # legacy_slug 备份值精确
    legacy = (
        await db_session.execute(
            text(
                "SELECT attributes->>'legacy_slug' FROM platform.tenants"
                " WHERE tenant_id = :tid"
            ),
            {"tid": stock_tenants["y26b"]},
        )
    ).scalar_one()
    assert legacy == "acme"

    # 计数表回填各年最大序号
    counters = {
        row["year"]: row["last_no"]
        for row in (
            await db_session.execute(
                text(
                    "SELECT year, last_no FROM platform.tenant_code_seq"
                    " WHERE year IN (2025, 2026) ORDER BY year"
                )
            )
        ).mappings()
    }
    assert counters == {2025: 3, 2026: 2}

    # 后续 API 取号从存量后续起（不撞已重写行）
    nxt = await next_tenant_code(db_session, 2026)
    assert nxt == "ten-2026-0003"
    await db_session.rollback()


async def test_0020_downgrade_restores_legacy(
    db_session: AsyncSession, stock_tenants: dict[str, str], database_url: str
) -> None:
    """downgrade：legacy_slug 精确还原 + 计数表删除；预置新格式行保持。"""
    await _replay_0020(database_url)
    await db_session.rollback()  # 释放读事务快照，避免与 alembic DDL 相互等待

    await asyncio.to_thread(
        _alembic, database_url, "downgrade", "0019_v13_adapter_config"
    )
    slug, backed = await _slugs_of(db_session, stock_tenants["y26b"])
    assert slug == "acme"  # 旧 slug 精确还原
    assert not backed  # 备份键移除
    preset_slug, _ = await _slugs_of(db_session, stock_tenants["preset"])
    assert preset_slug == "ten-2025-0001"  # 无 legacy 的行保持新格式（裁定）
    exists = (
        await db_session.execute(
            text("SELECT to_regclass('platform.tenant_code_seq')")
        )
    ).scalar()
    assert exists is None
    await db_session.rollback()

    # 回 head：清场后库恢复迁移态（供同 session 后续用例）
    await _replay_0020(database_url)


async def test_next_tenant_code_overflow_widens(db_session: AsyncSession) -> None:
    """序号 >9999 自然溢出 5 位（f-string 语义锁定）。"""
    year = 2097
    try:
        await db_session.execute(
            text(
                "INSERT INTO platform.tenant_code_seq (year, last_no)"
                " VALUES (:y, 9999)"
            ),
            {"y": year},
        )
        code = await next_tenant_code(db_session, year)
        assert code == f"ten-{year}-10000"
        assert re.fullmatch(CODE_PATTERN, code)
    finally:
        await db_session.rollback()
        await db_session.execute(
            text("DELETE FROM platform.tenant_code_seq WHERE year = :y"), {"y": year}
        )
        await db_session.commit()
