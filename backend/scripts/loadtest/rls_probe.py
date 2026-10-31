"""RLS 开销双轨探针（W6 T6 / EDP-033）：edp_app（FORCE RLS 生效）vs
edp_migrator（POSTGRES_USER 超级用户，BYPASSRLS）× 三查询模式 × 200 次，
输出各模式双轨 P95（ms）与差值百分比表。

DSN env：EDP_APP_DB / EDP_MIGRATOR_DB（缺省 dev compose override 宿主映射
localhost:15432；账号见 deploy/pg-init/01-roles.sql 与 compose POSTGRES_USER）。
两轨同协议执行（每轮独立事务 + SET LOCAL app.tenant_id，对齐 core.db.bind_tenant
——migrator 轨 set_config 无 RLS 语义，仅保持协议对称）。租户 = slug 'default'。
三模式对齐 ORM 实际查询：events risk 过滤一页（含 count，events service）/
objects 类型过滤一页（registry service，无 count）/audit 过滤一页
（platform.audit_logs 控制面无 RLS，显式 tenant_id 条件——本身即零开销对照）。

用法（backend 目录）：
    uv run python scripts/loadtest/rls_probe.py | tee ../deploy/loadtest/rls-probe.txt
"""

from __future__ import annotations

import asyncio
import math
import os
import time

import asyncpg

ITERATIONS = 200
WARMUP = 20
DEFAULT_APP_DB = "postgresql://edp_app:edp_app@localhost:15432/edp"
DEFAULT_MIGRATOR_DB = "postgresql://edp_migrator:edp_dev@localhost:15432/edp"

EVENTS_PAGE_SQL = """
SELECT e.event_id, e.event_type, e.risk_level, e.occurred_at,
       o.status AS delivery_status, b.source_id AS object_source_id
FROM event.events e
LEFT JOIN event.outbox o
       ON o.aggregate_type = 'EVENT' AND o.aggregate_id = e.event_id
      AND o.tenant_id = e.tenant_id
LEFT JOIN master.business_objects b ON b.object_id = e.object_id
WHERE e.risk_level = $1
ORDER BY e.occurred_at DESC, e.event_id DESC
LIMIT 20
"""

EVENTS_COUNT_SQL = """
SELECT count(*) FROM event.events WHERE risk_level = $1
"""

OBJECTS_PAGE_SQL = """
SELECT object_id, object_type, source_system, source_id, status, revision, updated_at
FROM master.business_objects
WHERE object_type = $1
ORDER BY updated_at DESC, object_id DESC
LIMIT 20
"""

AUDIT_PAGE_SQL = """
SELECT audit_id, tenant_id, actor_type, actor_id, action, resource_type, occurred_at
FROM platform.audit_logs
WHERE tenant_id = $1 AND occurred_at >= now() - interval '1 day'
ORDER BY occurred_at DESC, audit_id DESC
LIMIT 20
"""

# 参数 None 占位 = 绑定租户 id（audit 模式显式租户条件）
MODES: dict[str, tuple[tuple[str, tuple], ...]] = {
    "events_risk_page": ((EVENTS_PAGE_SQL, ("P1",)), (EVENTS_COUNT_SQL, ("P1",))),
    "objects_type_page": ((OBJECTS_PAGE_SQL, ("ORDER",)),),
    "audit_filter_page": ((AUDIT_PAGE_SQL, (None,)),),
}


def p95(samples: list[float]) -> float:
    index = min(len(samples) - 1, math.ceil(0.95 * len(samples)) - 1)
    return sorted(samples)[index]


async def _run_once(
    conn: asyncpg.Connection, tenant_id: str, statements: tuple[tuple[str, tuple], ...]
) -> None:
    async with conn.transaction():
        await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_id)
        for sql, args in statements:
            await conn.fetch(sql, *[tenant_id if a is None else a for a in args])


async def run_track(dsn: str, tenant_id: str) -> dict[str, list[float]]:
    conn = await asyncpg.connect(dsn)
    try:
        results: dict[str, list[float]] = {}
        for name, statements in MODES.items():
            for _ in range(WARMUP):
                await _run_once(conn, tenant_id, statements)
            samples: list[float] = []
            for _ in range(ITERATIONS):
                start = time.perf_counter()
                await _run_once(conn, tenant_id, statements)
                samples.append((time.perf_counter() - start) * 1000)
            results[name] = samples
        return results
    finally:
        await conn.close()


async def main() -> None:
    app_dsn = os.getenv("EDP_APP_DB", DEFAULT_APP_DB)
    migrator_dsn = os.getenv("EDP_MIGRATOR_DB", DEFAULT_MIGRATOR_DB)
    setup = await asyncpg.connect(migrator_dsn)
    tenant_id = str(
        await setup.fetchval(
            "SELECT tenant_id FROM platform.tenants WHERE slug = 'default'"
        )
    )
    await setup.close()
    print(f"tenant=default ({tenant_id})  iterations={ITERATIONS}  warmup={WARMUP}")
    print(f"app      = {app_dsn}")
    print(f"migrator = {migrator_dsn}")
    app = await run_track(app_dsn, tenant_id)
    migrator = await run_track(migrator_dsn, tenant_id)
    print()
    print(f"{'mode':<20}{'app P95(ms)':>14}{'migrator P95(ms)':>18}{'diff':>10}")
    for name in MODES:
        a, m = p95(app[name]), p95(migrator[name])
        print(f"{name:<20}{a:>14.2f}{m:>18.2f}{(a - m) / m * 100:>9.1f}%")


if __name__ == "__main__":
    asyncio.run(main())
