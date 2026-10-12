"""EDP Outbox Worker 进程入口（compose：``python -m edp_worker.main``）。

装配：get_engine（EDP_DATABASE_URL，生产为 edp_app 角色——worker 受
FORCE RLS 约束，分发前 bind_tenant 见 outbox_dispatch）→ 注册内置订阅者
（LoggingSubscriber + EBMSNotifyStubSubscriber）→ run_forever 常驻。

优雅退出：SIGTERM/SIGINT 置停止事件（Windows ProactorEventLoop 不支持
add_signal_handler，降级为 KeyboardInterrupt 兜底）；退出前取消循环并
释放引擎连接池。
"""

import asyncio
import logging
import signal

from edp_api.core.db import dispose_engine, get_engine
from edp_api.core.events import (
    EBMSNotifyStubSubscriber,
    LoggingSubscriber,
    clear_subscribers,
    register_subscriber,
    subscribers,
)

from edp_worker.admission_job import admission_loop
from edp_worker.outbox_dispatch import run_forever

logger = logging.getLogger("edp.worker")


async def _install_signal_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows ProactorEventLoop
            logger.warning("signal handler unavailable on this loop: %s", sig.name)


async def _work() -> None:
    engine = get_engine()
    clear_subscribers()
    register_subscriber(LoggingSubscriber())
    register_subscriber(EBMSNotifyStubSubscriber())
    logger.info("worker started subscribers=%d", len(subscribers))
    # 并发常驻：outbox 分发 + admission 机器预审调度（V1.2 T32，缺省 60s）
    await asyncio.gather(
        run_forever(engine, list(subscribers)),
        admission_loop(engine),
    )


async def main() -> None:
    stop = asyncio.Event()
    await _install_signal_handlers(stop)

    task = asyncio.create_task(_work())
    stop_waiter = asyncio.create_task(stop.wait())
    done, _ = await asyncio.wait(
        {task, stop_waiter}, return_when=asyncio.FIRST_COMPLETED
    )
    stop_waiter.cancel()

    if task in done and task.exception() is not None:
        raise task.exception()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await dispose_engine()
    logger.info("worker stopped")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.getLogger("edp.worker").info("worker interrupted")
