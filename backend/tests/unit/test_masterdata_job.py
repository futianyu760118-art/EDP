"""V1.3 T46 单测：主数据定时增量兜底（注入替身，不碰 DB/Kafka）。

覆盖：
1. 配置解析：EDP_MASTERDATA_ADAPTERS/INTERVAL（空 = 禁用）；
2. run_masterdata_round：逐租户 × 逐适配器 incremental 同步 + 互斥锁
   取/放；锁被占（与 API 触发 sync 同键）→ 跳过本轮该适配器；
3. masterdata_loop：按 interval 周期执行、stop 优雅退出。
"""

import asyncio

import edp_worker.masterdata_job as mj
import pytest
from edp_worker.masterdata_job import masterdata_loop, run_masterdata_round


class _Mutex:
    def __init__(self, busy: bool = False):
        self.busy = busy
        self.released = False

    async def release(self):
        self.released = True


class _Adapters:
    def __init__(self):
        self.synced: list[tuple[str, str]] = []  # (tenant, adapter)
        self.fail_on: str | None = None

    async def __call__(self, engine, tenant_id, adapter, mode, since=None):
        from edp_api.modules.ingest.service import SyncStats

        if self.fail_on == adapter.name:
            raise RuntimeError("sync boom")
        self.synced.append((str(tenant_id), adapter.name))
        return SyncStats(fetched=1, registered=1)


@pytest.fixture
def adapters(monkeypatch):
    fake = _Adapters()
    monkeypatch.setattr(mj, "_run_incremental", fake)
    return fake


@pytest.fixture
def locks(monkeypatch):
    state = {"held": None, "acquired": [], "released": []}

    async def fake_try_acquire(key):
        state["acquired"].append(key)
        if state["held"] == key:
            return None
        m = _Mutex()
        state.setdefault("mutexes", {})[key] = m
        return m

    monkeypatch.setattr(mj, "try_acquire_task_lock", fake_try_acquire)
    return state


class TestConfig:
    def test_disabled_without_adapters(self):
        assert mj.MasterdataSettings.from_env({}) is None

    def test_full_config(self):
        settings = mj.MasterdataSettings.from_env(
            {
                "EDP_MASTERDATA_ADAPTERS": "erp-demo, plm-demo",
                "EDP_MASTERDATA_INTERVAL_S": "120",
            }
        )
        assert settings is not None
        assert settings.adapters == ("erp-demo", "plm-demo")
        assert settings.interval_s == 120.0


class TestRound:
    async def test_syncs_each_tenant_adapter_incremental(self, adapters, locks):
        calls = await run_masterdata_round(
            engine=None,
            tenant_ids=["t1", "t2"],
            adapter_names=("erp-demo", "plm-demo"),
        )
        assert calls == 4
        assert sorted(adapters.synced) == [
            ("t1", "erp-demo"),
            ("t1", "plm-demo"),
            ("t2", "erp-demo"),
            ("t2", "plm-demo"),
        ]
        # 每次同步都取锁并释放（与 API 触发 sync 同键互斥）
        assert len(locks["acquired"]) == 4
        assert all(m.released for m in locks["mutexes"].values())

    async def test_busy_lock_skips_adapter(self, adapters, locks):
        locks["held"] = mj.task_lock_key("adapter_sync", ref_name="erp-demo")
        calls = await run_masterdata_round(
            engine=None, tenant_ids=["t1"], adapter_names=("erp-demo", "plm-demo")
        )
        assert calls == 1
        assert adapters.synced == [("t1", "plm-demo")]

    async def test_unknown_adapter_isolated(self, adapters, locks):
        # 未注册适配器 → 该次跳过，不连坐其他适配器
        calls = await run_masterdata_round(
            engine=None, tenant_ids=["t1"], adapter_names=("nope", "plm-demo")
        )
        assert calls == 1
        assert adapters.synced == [("t1", "plm-demo")]

    async def test_sync_failure_releases_lock_and_continues(self, adapters, locks):
        adapters.fail_on = "erp-demo"
        calls = await run_masterdata_round(
            engine=None, tenant_ids=["t1"], adapter_names=("erp-demo", "plm-demo")
        )
        assert calls == 1
        assert all(m.released for m in locks["mutexes"].values())


class TestLoop:
    async def test_loop_runs_rounds_and_stops(self, adapters, locks, monkeypatch):
        rounds = []

        async def fake_round(engine=None, tenant_ids=None, adapter_names=None):
            rounds.append(1)
            return 0

        monkeypatch.setattr(mj, "run_masterdata_round", fake_round)

        async def fake_tenants(engine):
            return ["t1"]

        monkeypatch.setattr(mj, "active_tenant_ids", fake_tenants)

        stop = asyncio.Event()

        async def _stop_after_two():
            for _ in range(500):  # 有界轮询替代 while+sleep（ASYNC110）
                if len(rounds) >= 2:
                    break
                await asyncio.sleep(0.01)
            stop.set()

        guard = asyncio.create_task(_stop_after_two())
        await masterdata_loop(None, interval=0.01, adapters=("erp-demo",), stop=stop)
        await guard
        assert len(rounds) >= 2
