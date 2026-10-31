"""管道 CLI（T15）：python -m edp_api.modules.ingest.cli
{full,incremental,reconcile,reconcile-capture}。

dev 环境（compose db 映射宿主 15432，edp_app 应用角色）用法：
    cd backend && uv run python -m edp_api.modules.ingest.cli full
    uv run python -m edp_api.modules.ingest.cli incremental --tenant-slug default

连接：环境变量 EDP_DATABASE_URL（get_settings 读的同一变量），缺省 dev
compose 的 edp_app 连接串——管道必须以应用角色运行让 RLS 生效，不用
migrator 超级用户。进程自装审计切面（与 create_app 同一入口，幂等）。

输出/退出码：stdout 打印 SyncStats（fetched/registered/duplicated/failed）
或对账表格与偏差行数；0 = 成功（reconcile 要求全行 ok）；1 = 存在失败
记录 / 对账偏差 / 运行错误；2 = 租户不存在。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from collections.abc import Sequence
from uuid import UUID

from edp_adapters import ErpMockAdapter
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from edp_api.core.db import bind_tenant
from edp_api.modules.audit.aspect import install_audit_aspect
from edp_api.modules.ingest import service as ingest_service
from edp_api.modules.tenantmgmt import service as tenantmgmt_service

# dev compose override（宿主 5432 被占）映射 db→宿主 15432；与 config.py
# 缺省端口一致。EDP_DATABASE_URL 即 get_settings 已读变量（env_prefix="EDP_"）
DEFAULT_DATABASE_URL = "postgresql+asyncpg://edp_app:edp_app@localhost:15432/edp"
DEFAULT_TENANT_SLUG = "default"

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_NOT_FOUND = 2

_RECONCILE_HEADERS = (
    "source_system",
    "object_type",
    "source",
    "objects",
    "events",
    "evidence",
    "ok",
)

_CAPTURE_RECONCILE_HEADERS = (
    "pull_source",
    "capture_source",
    "object_type",
    "pull",
    "capture",
    "ok",
)


async def _resolve_tenant_id(engine: AsyncEngine, slug: str) -> UUID | None:
    """slug → tenant_id（tenants 控制面表不受 RLS，无需租户绑定）。"""
    async with async_sessionmaker(engine, expire_on_commit=False)() as sess:
        tenant = await tenantmgmt_service.get_tenant_by_slug(sess, slug)
    return tenant.tenant_id if tenant is not None else None


async def _cmd_sync(engine: AsyncEngine, tenant_id: UUID, mode: str) -> int:
    """full / incremental：逐记录独立事务同步，打印 SyncStats。"""
    stats = await ingest_service.run_sync_per_record(
        engine, tenant_id, ErpMockAdapter(), mode
    )
    print(
        f"fetched={stats.fetched} registered={stats.registered} "
        f"duplicated={stats.duplicated} failed={stats.failed}"
    )
    if stats.failed > 0:
        print(
            f"警告：{stats.failed} 条记录失败（已逐条隔离回滚），退出码 1",
            file=sys.stderr,
        )
        return EXIT_FAILURE
    return EXIT_OK


async def _cmd_reconcile(engine: AsyncEngine, tenant_id: UUID) -> int:
    """reconcile：对账表格 + 偏差行数；存在 ok=False 行 → 退出码 1。"""
    async with async_sessionmaker(engine, expire_on_commit=False)() as sess:
        await bind_tenant(sess, tenant_id)
        rows = await ingest_service.reconcile(sess, tenant_id, ErpMockAdapter())
    _print_reconcile_table(rows)
    deviated = sum(1 for row in rows if not row.ok)
    print(f"偏差行数 {deviated} / 共 {len(rows)} 行")
    return EXIT_FAILURE if deviated > 0 else EXIT_OK


async def _cmd_reconcile_capture(
    engine: AsyncEngine, tenant_id: UUID, capture_source: str
) -> int:
    """reconcile-capture（V1.3 T47）：CDC 轨 vs 拉取轨双轨对账。"""
    async with async_sessionmaker(engine, expire_on_commit=False)() as sess:
        await bind_tenant(sess, tenant_id)
        rows = await ingest_service.reconcile_capture(
            sess, tenant_id, ErpMockAdapter(), capture_source_system=capture_source
        )
    table = [
        (
            row.source_system,
            row.capture_source_system,
            row.object_type,
            str(row.source_count),
            str(row.capture_count),
            str(row.ok),
        )
        for row in rows
    ]
    widths = [
        max([len(_CAPTURE_RECONCILE_HEADERS[i])] + [len(line[i]) for line in table])
        for i in range(len(_CAPTURE_RECONCILE_HEADERS))
    ]
    fmt = "  ".join(f"{{:{width}}}" for width in widths)
    print(fmt.format(*_CAPTURE_RECONCILE_HEADERS))
    for line in table:
        print(fmt.format(*line))
    deviated = sum(1 for row in rows if not row.ok)
    print(f"偏差行数 {deviated} / 共 {len(rows)} 行")
    return EXIT_FAILURE if deviated > 0 else EXIT_OK


def _print_reconcile_table(rows: Sequence[ingest_service.ReconciliationRow]) -> None:
    """对齐列打印（纯 ASCII 分隔，GBK 控制台安全）。"""
    table = [
        (
            row.source_system,
            row.object_type,
            str(row.source_count),
            str(row.edp_count_objects),
            str(row.edp_count_events),
            str(row.edp_count_evidence),
            str(row.ok),
        )
        for row in rows
    ]
    widths = [
        max([len(_RECONCILE_HEADERS[i])] + [len(line[i]) for line in table])
        for i in range(len(_RECONCILE_HEADERS))
    ]
    fmt = "  ".join(f"{{:{width}}}" for width in widths)
    print(fmt.format(*_RECONCILE_HEADERS))
    for line in table:
        print(fmt.format(*line))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edp_api.modules.ingest.cli",
        description="EDP 接入管道 CLI：全量/增量同步（逐记录独立事务）与源-库对账",
    )
    parser.add_argument(
        "--tenant-slug",
        default=DEFAULT_TENANT_SLUG,
        help="租户 slug（缺省 default；不存在退出码 2）",
    )
    parser.add_argument(
        "command",
        choices=("full", "incremental", "reconcile", "reconcile-capture"),
        help="full=全量同步 incremental=自水位增量 reconcile=对账"
        " reconcile-capture=CDC/拉取双轨对账",
    )
    parser.add_argument(
        "--capture-source",
        default="scm",
        help="reconcile-capture 的 CDC 轨 source_system（缺省 scm）",
    )
    return parser


async def _run(url: str, command: str, tenant_slug: str, capture_source: str) -> int:
    install_audit_aspect()
    engine = create_async_engine(url)
    try:
        tenant_id = await _resolve_tenant_id(engine, tenant_slug)
        if tenant_id is None:
            print(f"错误：租户不存在：{tenant_slug}", file=sys.stderr)
            return EXIT_NOT_FOUND
        if command == "reconcile":
            return await _cmd_reconcile(engine, tenant_id)
        if command == "reconcile-capture":
            return await _cmd_reconcile_capture(engine, tenant_id, capture_source)
        return await _cmd_sync(engine, tenant_id, command)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    # Windows GBK 控制台防炸：输出统一 utf-8、不可编码字符降级替换
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    url = os.environ.get("EDP_DATABASE_URL") or DEFAULT_DATABASE_URL
    try:
        return asyncio.run(
            _run(url, args.command, args.tenant_slug, args.capture_source)
        )
    except Exception:
        logging.getLogger(__name__).exception("CLI 执行失败")
        return EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main())
