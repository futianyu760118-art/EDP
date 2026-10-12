"""Admission 机器预审调度（V1.2 T32）：CLASSIFIED 自动预审编排。

- run_admission_job：单租户一批——PASS/WARNING 推进 SOURCE_REVIEW、
  FAIL 留态 + DataQuality.Exception（governance 服务单实现）；
- admission_loop：常驻周期循环（缺省 60s），逐租户独立事务/异常隔离；
- 表访问收敛：全部经 governance.service（模块 service 路径）。
"""

import asyncio
import logging

from edp_api.core.db import bind_tenant
from edp_api.modules.governance import service as governance_service
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from edp_worker.scheduler import active_tenant_ids

logger = logging.getLogger("edp.worker.admission")

DEFAULT_INTERVAL_S = 60.0
DEFAULT_BATCH_SIZE = 100


async def run_admission_job(
    engine: AsyncEngine, tenant_id, *, batch_size: int = DEFAULT_BATCH_SIZE
) -> dict[str, int]:
    """单租户一批自动预审（独立事务；单租户异常由调用方隔离）。"""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as sess:
        await bind_tenant(sess, tenant_id)
        stats = await governance_service.auto_source_machine_review(
            sess, tenant_id, batch_size=batch_size
        )
        await sess.commit()
    return stats


async def admission_loop(
    engine: AsyncEngine,
    *,
    interval: float = DEFAULT_INTERVAL_S,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> None:
    """常驻周期循环：活跃租户清单（30s 缓存）→ 逐租户预审批次。"""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    while True:
        try:
            async with factory() as sess:
                tenant_ids = await active_tenant_ids(sess)
        except Exception:  # noqa: BLE001 — 清单查询失败不致死循环退出
            logger.exception("active tenant list query failed")
            tenant_ids = []
        for tenant_id in tenant_ids:
            try:
                stats = await run_admission_job(engine, tenant_id, batch_size=batch_size)
            except Exception:  # noqa: BLE001 — 单租户异常隔离
                logger.exception("admission job failed tenant=%s", tenant_id)
                continue
            if any(stats.values()):
                logger.info(
                    "admission auto review tenant=%s advanced=%d blocked=%d",
                    tenant_id,
                    stats["advanced"],
                    stats["blocked"],
                )
        await asyncio.sleep(interval)
