"""主数据定时增量兜底（V1.3 T46）：低频主数据双轨的拉取轨常驻调度。

- 与 CDC 实时轨互补（方案 V1.3 §2.4）：物料/供应商/客户等低频主数据
  保留 fetch_incremental 拉取——CDC 漏数可由本轨补偿，双轨对账见
  ingest.reconcile_capture（T47）；
- 互斥：与 API 触发的适配器同步同键（ops.task:adapter_sync:{adapter}
  advisory lock）——被占即跳过本轮该适配器，不与 adapters_admin 并发；
- 不落 ops.tasks 行（裁定：可观测性先经日志；任务轨道接入后续随
  worker 调度统一改造评估）；
- 复用 run_sync_per_record（逐记录独立事务 + 水位推进，幂等重放安全）。

配置：EDP_MASTERDATA_ADAPTERS（逗号分隔，空 = 禁用）、
EDP_MASTERDATA_INTERVAL_S（缺省 3600）。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from os import environ
from uuid import UUID

from edp_api.core.db import bind_tenant
from edp_api.modules.adapters_admin import service as adapters_admin_service
from edp_api.modules.ingest import service as ingest_service
from edp_api.modules.quality.service import task_lock_key, try_acquire_task_lock
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from edp_worker.scheduler import active_tenant_ids

logger = logging.getLogger("edp.worker.masterdata")

DEFAULT_INTERVAL_S = 3600.0
ADAPTER_TASK_TYPE = "adapter_sync"


@dataclass(slots=True)
class MasterdataSettings:
    adapters: tuple[str, ...]
    interval_s: float = DEFAULT_INTERVAL_S

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> MasterdataSettings | None:
        source = env if env is not None else environ
        raw = (source.get("EDP_MASTERDATA_ADAPTERS") or "").strip()
        if not raw:
            return None
        adapters = tuple(name.strip() for name in raw.split(",") if name.strip())
        interval_raw = source.get("EDP_MASTERDATA_INTERVAL_S")
        return cls(
            adapters=adapters,
            interval_s=float(interval_raw) if interval_raw else DEFAULT_INTERVAL_S,
        )


async def _run_incremental(engine, tenant_id, adapter, mode, since=None):
    """同步执行体（模块属性，测试可替身注入）。"""
    return await ingest_service.run_sync_per_record(engine, tenant_id, adapter, mode, since)


async def run_masterdata_round(
    engine: AsyncEngine,
    tenant_ids: list[UUID],
    adapter_names: tuple[str, ...],
    *,
    resolve=None,
) -> int:
    """单轮：逐租户 × 逐适配器 incremental 同步（互斥 + 异常隔离）。

    适配器解析（T50）：缺省走 adapters_admin——每租户先 refresh_dynamic
    （catalog systems 行装配，RLS 天然隔离）再 get_adapter（动态优先、
    静态 demo 回退）；``resolve`` 为测试注入缝（替身返回适配器对象）。
    返回成功执行的同步次数（跳过/失败不计）。
    """
    executed = 0
    factory = async_sessionmaker(engine, expire_on_commit=False)
    for tenant_id in tenant_ids:
        if resolve is None:
            try:
                async with factory() as sess:
                    await bind_tenant(sess, tenant_id)
                    await adapters_admin_service.refresh_dynamic(sess, tenant_id)
            except Exception:  # noqa: BLE001 — 装配失败按全跳过处理
                logger.exception("masterdata 适配器装配失败 tenant=%s", tenant_id)
        for name in adapter_names:
            try:
                if resolve is None:
                    adapter = adapters_admin_service.get_adapter(tenant_id, name)
                else:
                    adapter = await resolve(tenant_id, name)
            except LookupError:
                logger.warning("masterdata 兜底适配器未注册，跳过：%s", name)
                continue
            mutex = await try_acquire_task_lock(
                task_lock_key(ADAPTER_TASK_TYPE, ref_name=name)
            )
            if mutex is None:
                logger.info("masterdata 兜底互斥被占，跳过本轮：%s", name)
                continue
            try:
                stats = await _run_incremental(engine, tenant_id, adapter, "incremental")
                executed += 1
                logger.info(
                    "masterdata 兜底同步完成 tenant=%s adapter=%s"
                    " fetched=%d registered=%d duplicated=%d failed=%d",
                    tenant_id,
                    name,
                    stats.fetched,
                    stats.registered,
                    stats.duplicated,
                    stats.failed,
                )
            except Exception:  # noqa: BLE001 — 单次失败隔离，锁仍须释放
                logger.exception(
                    "masterdata 兜底同步失败 tenant=%s adapter=%s", tenant_id, name
                )
            finally:
                await mutex.release()
    return executed


async def masterdata_loop(
    engine: AsyncEngine,
    *,
    interval: float = DEFAULT_INTERVAL_S,
    adapters: tuple[str, ...] = (),
    stop: asyncio.Event | None = None,
) -> None:
    """常驻周期循环（worker gather 并发协程之一；adapters 为空即空转）。"""
    stop = stop or asyncio.Event()
    while not stop.is_set():
        try:
            factory_kwargs = {"expire_on_commit": False}
            from sqlalchemy.ext.asyncio import async_sessionmaker

            factory = async_sessionmaker(engine, **factory_kwargs)
            async with factory() as sess:
                tenant_ids = await active_tenant_ids(sess)
        except Exception:  # noqa: BLE001 — 清单查询失败不致死循环退出
            logger.exception("masterdata active tenant list query failed")
            tenant_ids = []
        try:
            await run_masterdata_round(engine, tenant_ids, adapters)
        except Exception:  # noqa: BLE001 — 轮级异常隔离
            logger.exception("masterdata round failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            continue
