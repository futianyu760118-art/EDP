"""演示数据 seed CLI（T7）：python -m edp_api.modules.demo.cli seed [--reset]
[--scale N] [--anchor ISO]。

dev 环境（compose db 映射宿主 15432，edp_app 应用角色）用法：
    cd backend && uv run python -m edp_api.modules.demo.cli seed
    uv run python -m edp_api.modules.demo.cli seed --reset --tenant-slug default
    uv run python -m edp_api.modules.demo.cli seed --scale 116   # W6 压测量级
    # E2E 视觉回归固定锚（W6 T11：跨次运行页面时间文本确定）
    uv run python -m edp_api.modules.demo.cli seed --reset \
        --anchor 2026-08-01T00:00:00+00:00

连接：环境变量 EDP_DATABASE_URL（get_settings 读的同一变量），缺省 dev
compose 的 edp_app 连接串——seed 必须以应用角色运行让 RLS 生效，不用
migrator 超级用户。进程自装审计切面（与 create_app 同一入口，幂等）。

--scale N（W6 T5，EDP-033 压测前置）：1 = 十类场景基线（缺省，行为不变）；
N>1 在基线外追加 N-1 份确定性放大实体（量级换算见 demo.service 模块
docstring：目标 ≈5k 对象 / 50k 事件 / 10k 证据对应 N=116）。

--anchor ISO（W6 T11，EDP-603）：显式演示锚（仅配合 --reset；否则退出码
1）——视觉回归基线要求 seed 派生时间跨环境逐字节一致。

输出/退出码：stdout 打印 SeedStats（fetched/registered/duplicated/failed +
events_accepted/events_duplicated/case_created）；0 = 成功（failed>0 → 1）；
2 = 租户不存在。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from edp_api.modules.audit.aspect import install_audit_aspect
from edp_api.modules.demo import service as demo_service
from edp_api.modules.tenantmgmt import service as tenantmgmt_service

# dev compose override（宿主 5432 被占）映射 db→宿主 15432；与 config.py
# 缺省端口一致。EDP_DATABASE_URL 即 get_settings 已读变量（env_prefix="EDP_"）
DEFAULT_DATABASE_URL = "postgresql+asyncpg://edp_app:edp_app@localhost:15432/edp"

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_NOT_FOUND = 2


async def _resolve_tenant_id(engine: AsyncEngine, slug: str) -> UUID | None:
    """slug → tenant_id（tenants 控制面表不受 RLS，无需租户绑定）。"""
    async with async_sessionmaker(engine, expire_on_commit=False)() as sess:
        tenant = await tenantmgmt_service.get_tenant_by_slug(sess, slug)
    return tenant.tenant_id if tenant is not None else None


async def _cmd_seed(
    engine: AsyncEngine,
    tenant_id: UUID,
    *,
    reset: bool,
    scale: int,
    anchor: datetime | None,
) -> int:
    """seed：打印 SeedStats；存在失败记录 → 退出码 1。"""
    stats = await demo_service.seed(
        engine, tenant_id, reset=reset, scale=scale, anchor=anchor
    )
    print(
        f"fetched={stats.fetched} registered={stats.registered} "
        f"duplicated={stats.duplicated} failed={stats.failed} "
        f"events_accepted={stats.events_accepted} "
        f"events_duplicated={stats.events_duplicated} "
        f"case_created={stats.case_created}"
    )
    if stats.failed > 0:
        print(
            f"警告：{stats.failed} 条记录失败（已逐条隔离回滚），退出码 1",
            file=sys.stderr,
        )
        return EXIT_FAILURE
    return EXIT_OK


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edp_api.modules.demo.cli",
        description="EDP 演示数据 CLI：seed（幂等重放；--reset 复位重建）",
    )
    parser.add_argument(
        "--tenant-slug",
        default=demo_service.DEFAULT_TENANT_SLUG,
        help="租户 slug（缺省 default；不存在退出码 2）",
    )
    parser.add_argument(
        "command",
        choices=("seed",),
        help="seed=演示数据快照+回流段（可重放）",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="复位：逆依赖序清本租户业务数据（审计保留）+ 重锚后重建",
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=1,
        help="数据放大倍数（1=基线十场景；N>1 追加 N-1 份确定性放大实体，"
        "目标 ≈5k/50k/10k 对应 N=116）",
    )
    parser.add_argument(
        "--anchor",
        type=datetime.fromisoformat,
        default=None,
        help="显式演示锚 ISO-8601（仅配合 --reset；W6 T11 视觉回归固定基线，"
        "如 2026-08-01T00:00:00+00:00）",
    )
    return parser


async def _run(
    url: str,
    command: str,
    tenant_slug: str,
    *,
    reset: bool,
    scale: int,
    anchor: datetime | None,
) -> int:
    if anchor is not None and not reset:
        print("错误：--anchor 仅在 --reset 时生效（非 reset 复用存量锚）", file=sys.stderr)
        return EXIT_FAILURE
    if anchor is not None and anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)  # naive 输入按 UTC
    install_audit_aspect()
    engine = create_async_engine(url)
    try:
        tenant_id = await _resolve_tenant_id(engine, tenant_slug)
        if tenant_id is None:
            print(f"错误：租户不存在：{tenant_slug}", file=sys.stderr)
            return EXIT_NOT_FOUND
        return await _cmd_seed(
            engine, tenant_id, reset=reset, scale=scale, anchor=anchor
        )
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
            _run(
                url,
                args.command,
                args.tenant_slug,
                reset=args.reset,
                scale=args.scale,
                anchor=args.anchor,
            )
        )
    except Exception:
        logging.getLogger(__name__).exception("CLI 执行失败")
        return EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main())
