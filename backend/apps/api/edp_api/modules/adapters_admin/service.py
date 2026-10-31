"""适配器 sync 后台任务服务（B.12 最小版 / T16；W5 T5 任务历史落库收口）。

任务状态自 T5 起持久化于 ops.tasks（W4-07 收口，W3-41/42 jobs 语义）：
trigger_sync 在请求事务内登记 RUNNING 行（task_type=adapter_sync、
ref_name=适配器名、scope=mode）→ 202；后台执行体先按 T4 模式等行可见
（有界重试 ``quality.service.wait_task_visible``——T5 评审移交、T6 收口的
公共单一实现，本模块原复制件已删除，语义与改动记录见其 docstring），
再复用 ingest.run_sync_per_record（engine + 每记录独立
事务）执行；stats（fetched/registered/duplicated/failed 四计数语义不变）
与起止/错误 logs 落任务行，完成置终态 + finished_at（终态回写经独立会话/
事务尽力落库，回写失败仅告警）。ORM 映射 OpsTask 经 quality.service 引用
（import-linter 跨模块仅准 service 路径）。

**任务互斥（W6 T3 / Redis B 轻量项）**：同一适配器并发触发 → 入口
``quality.service.try_acquire_task_lock``（键 ops.task:adapter_sync:
{adapter}——同一适配器互斥、不同适配器并行）被占方 409 CONFLICT，不登记
行；拿到锁才建行/派发，锁句柄随后台执行体走（执行体 finally 释放；锁
语义与连接生命周期见 ``quality.service.TaskMutex`` docstring）。多副本
安全（advisory lock 服务端串行）；进程崩溃连接断开即解锁。W5-21-a：
整批级异常置 FAILED 时 stats 置空 ``{}``（「FAILED 即无最终计数」——
单条失败仍逐条隔离计数于 stats.failed，仅整批级异常无最终计数）。

执行策略/RLS/水位：engine 经 core_db.get_engine() 取 API 进程全局引擎
（模块属性引用，便于测试 monkeypatch），RLS 依赖 bind_tenant 在
per-record 事务内完成，与请求会话完全解耦；单条记录失败由
run_sync_per_record 逐条隔离（failed+1），仅整批级异常才置 FAILED。

清单/水位：list_adapters 经调用方（请求）会话读 systems.last_watermark
（platform.systems 受 RLS——请求会话已被 tenant_scoped bind_tenant）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from edp_adapters import (
    AdapterRegistry,
    DbPullAdapter,
    DbTableSpec,
    DemoErpAdapter,
    DemoMesAdapter,
    DemoPlmAdapter,
    ErpMockAdapter,
)
from sqlalchemy import and_, or_, select, text

from edp_api.core import db as core_db
from edp_api.core.pagination import decode_cursor, encode_cursor
from edp_api.modules.adapters_admin.schemas import (
    AdapterJobItem,
    AdapterListItem,
    AdapterStatusResponse,
    LastSyncSummary,
)
from edp_api.modules.ingest import service as ingest_service

# 跨模块仅准 service（import-linter）——OpsTask 映射经 quality.service 透出；
# wait_task_visible 为 T5 评审移交、T6 收口的公共单一实现（原本地复制件已删）；
# TaskMutex/raise_task_conflict 为 W6 T3 任务互斥公共实现
from edp_api.modules.quality.service import (
    TASK_VISIBILITY_ATTEMPTS,
    OpsTask,
    TaskMutex,
    raise_task_conflict,
    task_lock_key,
    try_acquire_task_lock,
    wait_task_visible,
)

if TYPE_CHECKING:
    from edp_adapters.base import SourceAdapter
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from edp_api.modules.adapters_admin.schemas import SyncMode

logger = logging.getLogger(__name__)

ERROR_MAX_LEN = 500
ADAPTER_MODE_MOCK = "mock"
ADAPTER_TASK_TYPE = "adapter_sync"

# jobs 历史（W3-41/42 语义收口）：游标分页 limit 上下界
DEFAULT_JOBS_LIMIT = 20
MAX_JOBS_LIMIT = 100

# 清单/状态展示文案（与 MSW 13.6 数据故事一致：运行中/空闲/异常、OK/DEGRADED）
_STATUS_TEXT: dict[str, str] = {"RUNNING": "运行中", "SUCCEEDED": "空闲", "FAILED": "异常"}
_HEALTH_TEXT: dict[bool, str] = {True: "OK", False: "DEGRADED"}

# 进程内注册表：erp（W2 基线）+ erp-demo/plm-demo/mes-demo（W3 演示数据集，
# T6 + EDP-017 剩余）——静态注册（demo/mock，无租户语义）；
# 动态适配器（V1.3 T50）：catalog systems 行（adapter_config 非空）装配为
# DbPullAdapter，键 (tenant_id, name)——RLS 下每租户各自装配，跨租户同名
# 配置互不干扰（uq_systems_name 为 (tenant_id, name)）。装配来源
# refresh_dynamic（catalog CRUD 后 / worker 每轮调用）。
_registry = AdapterRegistry()
_registry.register(ErpMockAdapter())
_registry.register(DemoErpAdapter())
_registry.register(DemoPlmAdapter())
_registry.register(DemoMesAdapter())

# (tenant_id, name) → DbPullAdapter（进程内装配缓存；refresh 按租户替换）
_dynamic: dict[tuple[UUID, str], DbPullAdapter] = {}
# (tenant_id, name) → catalog systems 行 id（前端编辑/删除入口用）——
# 含已注册未装配（无 adapter_config）的 SOURCE 系统
_dynamic_system_ids: dict[tuple[UUID, str], UUID] = {}

# 已注册未装配名（catalog ACTIVE SOURCE 且 adapter_config 缺失/非法）：
# 清单可见（mode=unconfigured），但不进 get_adapter（sync/status 404 语义）
_unconfigured: set[tuple[UUID, str]] = set()

_SYSTEMS_SQL = text("""
    SELECT system_id, name, type, adapter_config FROM platform.systems
    WHERE status = 'ACTIVE' AND type = 'SOURCE'
""")

UNCONFIGURED_MODE = "unconfigured"
UNCONFIGURED_TEXT = "未配置"


def build_adapter_from_config(
    name: str, adapter_config: dict | str | None
) -> DbPullAdapter | None:
    """adapter_config → DbPullAdapter；缺 dsn/tables 或条目非法 → None。

    原生 SQL 驱动（asyncpg）jsonb 返回 JSON 文本；ORM 返回 dict——两种
    形态均归一。tables 条目：table（必填）/ increment_column（缺省 None
    全量）/ owner_domain（缺省 master）/ excluded_columns（缺省空）。
    """
    if isinstance(adapter_config, str):
        try:
            adapter_config = json.loads(adapter_config)
        except json.JSONDecodeError:
            return None
    if not isinstance(adapter_config, dict):
        return None
    dsn = adapter_config.get("dsn")
    tables = adapter_config.get("tables")
    if not dsn or not isinstance(tables, list) or not tables:
        return None
    specs: list[DbTableSpec] = []
    for item in tables:
        if not isinstance(item, dict) or not item.get("table"):
            return None
        specs.append(
            DbTableSpec(
                table=item["table"],
                increment_column=item.get("increment_column"),
                owner_domain=item.get("owner_domain") or "master",
                excluded_columns=tuple(item.get("excluded_columns") or ()),
            )
        )
    return DbPullAdapter(name=name, dsn=dsn, table_specs=specs)


async def refresh_dynamic(sess: AsyncSession, tenant_id: UUID) -> None:
    """按租户重载动态适配器（RLS 会话仅见本租户 systems 行——天然隔离）。

    catalog CRUD 收尾 / worker 每轮调用；本租户既有装配全量替换（删除的
    配置随之下线）。三类去向：adapter_config 可装配 → _dynamic（real）；
    缺失/非法 → _unconfigured（清单可见不可同步）；其余（CONSUMER 等）
    不进适配器清单。
    """
    rows = (await sess.execute(_SYSTEMS_SQL)).mappings().all()
    rebuilt: dict[tuple[UUID, str], DbPullAdapter] = {
        key: adapter for key, adapter in _dynamic.items() if key[0] != tenant_id
    }
    rebuilt_ids: dict[tuple[UUID, str], UUID] = {
        key: sid for key, sid in _dynamic_system_ids.items() if key[0] != tenant_id
    }
    unconfigured: set[tuple[UUID, str]] = {
        key for key in _unconfigured if key[0] != tenant_id
    }
    for row in rows:
        key = (tenant_id, row["name"])
        adapter = build_adapter_from_config(row["name"], row["adapter_config"])
        if adapter is not None:
            rebuilt[key] = adapter
            rebuilt_ids[key] = row["system_id"]
        else:
            unconfigured.add(key)
            rebuilt_ids[key] = row["system_id"]
    _dynamic.clear()
    _dynamic.update(rebuilt)
    _dynamic_system_ids.clear()
    _dynamic_system_ids.update(rebuilt_ids)
    _unconfigured.clear()
    _unconfigured.update(unconfigured)


def get_adapter(tenant_id: UUID, adapter_name: str) -> SourceAdapter:
    """(租户, 名) 查询：动态（真实装配）优先，静态（demo/mock）回退；
    未注册 → LookupError（router 转 404）。"""
    adapter = _dynamic.get((tenant_id, adapter_name))
    if adapter is not None:
        return adapter
    return _registry.get(adapter_name)


def is_dynamic(tenant_id: UUID, adapter_name: str) -> bool:
    """该适配器是否 DB 装配（清单 mode 展示 real/mock 用）。"""
    return (tenant_id, adapter_name) in _dynamic

# create_task 强引用防 GC（官方建议模式；完成回调自清理）
_tasks: set[asyncio.Task[None]] = set()


async def latest_task(sess: AsyncSession, adapter_name: str) -> OpsTask | None:
    """该适配器最近一次 adapter_sync 任务行（未跑过 → None）。"""
    return (
        await sess.execute(
            select(OpsTask)
            .where(
                OpsTask.task_type == ADAPTER_TASK_TYPE,
                OpsTask.ref_name == adapter_name,
            )
            .order_by(OpsTask.started_at.desc(), OpsTask.task_id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def trigger_sync(
    sess: AsyncSession,
    tenant_id: UUID,
    adapter_name: str,
    mode: SyncMode,
    since: datetime | None = None,
    actor: str | None = None,
) -> OpsTask:
    """登记 ops.tasks 行并派发后台同步（须在事件循环内调用）→ 202 语义。

    **任务互斥（W6 T3）**：入口先 ``try_acquire_task_lock``（键
    ops.task:adapter_sync:{adapter_name}——同一适配器互斥）——被占 →
    409 CONFLICT（不登记行）；拿到锁才建行/派发，锁句柄随后台执行体走
    （执行体 finally 释放，见 ``quality.service.TaskMutex`` docstring）。

    行随请求事务落库（审计 TASK_CREATE 同事务派生）；后台先等行可见再
    执行（见 ``_run``）。since 仅 replay 语义消费（重放窗口下界），其余
    模式透传忽略。

    T50：触发前 refresh_dynamic 装配本租户动态适配器（catalog 行；RLS
    会话仅见本租户配置）。
    """
    await refresh_dynamic(sess, tenant_id)
    adapter = get_adapter(tenant_id, adapter_name)  # LookupError → router 转 404
    mutex = await try_acquire_task_lock(
        task_lock_key(ADAPTER_TASK_TYPE, ref_name=adapter_name)
    )
    if mutex is None:
        await raise_task_conflict(
            sess, tenant_id, ADAPTER_TASK_TYPE, ref_name=adapter_name
        )
    try:
        task = OpsTask(
            task_id=uuid4(),
            tenant_id=tenant_id,
            task_type=ADAPTER_TASK_TYPE,
            status="RUNNING",
            scope=mode,
            ref_name=adapter_name,
            started_at=datetime.now(UTC),
            created_by=actor,
        )
        sess.add(task)
        await sess.flush()  # 审计 TASK_CREATE 随请求事务落库
        background = asyncio.create_task(
            _run(
                task_id=task.task_id,
                tenant_id=tenant_id,
                adapter=adapter,
                mode=mode,
                since=since,
                actor=actor,
                mutex=mutex,
            )
        )
        _tasks.add(background)
        background.add_done_callback(_tasks.discard)
    except Exception:
        await mutex.release()  # 登记/派发失败就地释放（后台未接手）
        raise
    return task


async def _run(
    *,
    task_id: UUID,
    tenant_id: UUID,
    adapter: SourceAdapter,
    mode: SyncMode,
    since: datetime | None = None,
    actor: str | None = None,
    mutex: TaskMutex | None = None,
) -> None:
    """后台执行体：等行可见 → 逐记录独立事务同步 → 终态回写。

    互斥锁：入口已取得的 ``mutex`` 句柄随执行体走——**finally 释放**
    （任务终态/提前退出均达；缺省 None 容忍无锁直调）。

    行可见性按 T4 模式有界重试（``quality.service.wait_task_visible``
    公共单一实现）：READ COMMITTED 下请求事务未提交的 INSERT 行不可见，
    deadline 后仍不可见 = 请求事务已
    回滚（行不存在 → 提前退出，无处回写终态）。单条记录失败由
    run_sync_per_record 逐条隔离（failed+1），仅整批级异常才置 FAILED
    （stats 置空 {}——W5-21-a「FAILED 即无最终计数」；错误信息落 ERROR
    日志行——任务行无独立 error 列，status 端点从 logs 末条 ERROR 行提取）。
    """
    factory = core_db.get_session_local()
    logs = [_log_line("INFO", f"任务启动：mode={mode}")]
    try:
        async with factory() as sess:
            if not await wait_task_visible(sess, tenant_id, task_id):
                logger.warning(
                    "同步任务行 %d 次探测均不可见（deadline 后仍不可见，"
                    "请求事务已回滚）：%s",
                    TASK_VISIBILITY_ATTEMPTS,
                    task_id,
                )
                return
        try:
            stats = await ingest_service.run_sync_per_record(
                core_db.get_engine(), tenant_id, adapter, mode, since
            )
        except Exception as exc:
            logger.error(
                "适配器同步任务失败：%s(%s, %s)",
                adapter.name,
                task_id,
                mode,
                exc_info=True,
            )
            logs.append(_log_line("ERROR", f"任务失败：{str(exc)[:ERROR_MAX_LEN]}"))
            await _finish_task(
                factory, tenant_id, task_id, status="FAILED", stats={}, logs=logs, actor=actor
            )
            return
        logs.append(_log_line("INFO", "任务完成：SUCCEEDED"))
        await _finish_task(
            factory,
            tenant_id,
            task_id,
            status="SUCCEEDED",
            stats=asdict(stats),
            logs=logs,
            actor=actor,
        )
    finally:
        if mutex is not None:
            await mutex.release()  # 互斥窗 = 入口取锁至执行体收尾（终态/提前退出均达）


async def _finish_task(
    factory: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    task_id: UUID,
    *,
    status: str,
    stats: dict,
    logs: list[dict],
    actor: str | None,
) -> None:
    """终态回写（独立会话/事务尽力落库——回写自身异常仅告警）。stats/logs
    整行重赋值（JSONB 原位修改对 ORM 变更检测不可见）；行不存在（请求
    事务回滚）静默跳过——审计 TASK_UPDATE 随本事务落库。"""
    try:
        async with factory() as sess:
            await core_db.bind_tenant(sess, tenant_id)
            task = (
                await sess.execute(
                    select(OpsTask).where(OpsTask.task_id == task_id)
                )
            ).scalar_one_or_none()
            if task is None:
                return
            task.stats = stats
            task.logs = logs
            task.updated_by = actor
            task.status = status
            task.finished_at = datetime.now(UTC)
            await sess.commit()
    except Exception:
        logger.error("同步任务终态回写失败：%s", task_id, exc_info=True)


def _log_line(level: str, message: str) -> dict:
    """log 行（形状对齐 quality 任务 logs / mocks QualityTask：{ts, level, message}）。"""
    return {"ts": datetime.now(UTC).isoformat(), "level": level, "message": message}


def _summary_from(task: OpsTask) -> LastSyncSummary:
    """任务行 → LastSyncSummary（契约不变：sync_id=task_id str 化；error
    取末条 ERROR 日志行——任务行无独立 error 列；RUNNING 中 stats 为 {} →
    None，对齐旧内存态「完成前 stats 为空」语义）。"""
    error = next(
        (
            line.get("message")
            for line in reversed(task.logs)
            if line.get("level") == "ERROR"
        ),
        None,
    )
    return LastSyncSummary(
        sync_id=str(task.task_id),
        status=task.status,
        finished_at=task.finished_at,
        stats=task.stats or None,
        error=error,
    )


async def probe_health(adapter: SourceAdapter) -> str:
    """适配器探活（T50）：真实适配器 health_check 内跑 asyncio.run（线程
    契约）——请求上下文经 to_thread 调用；返回 _HEALTH_TEXT 键。"""
    health = await asyncio.to_thread(adapter.health_check)
    return _HEALTH_TEXT[health.ok]


async def adapter_status(
    sess: AsyncSession, tenant_id: UUID, adapter_name: str
) -> AdapterStatusResponse:
    """status 端点组装：注册表适配器 + 最近任务行 + 探活（未跑过 last_sync=null）。"""
    adapter = get_adapter(tenant_id, adapter_name)  # LookupError → router 转 404
    task = await latest_task(sess, adapter_name)
    last_sync = _summary_from(task) if task is not None else None
    return AdapterStatusResponse(
        adapter=adapter_name,
        mode="real" if is_dynamic(tenant_id, adapter_name) else ADAPTER_MODE_MOCK,
        last_sync=last_sync,
        health=await probe_health(adapter),
    )


async def list_jobs(
    sess: AsyncSession,
    tenant_id: UUID,
    adapter_name: str,
    *,
    limit: int = DEFAULT_JOBS_LIMIT,
    cursor: str | None = None,
) -> tuple[list[AdapterJobItem], str | None]:
    """适配器同步任务历史（ops.tasks；W3-41/42 jobs 语义收口）：游标分页
    started_at DESC + task_id DESC tiebreak，锚 ``{"s","i"}``；取 limit+1
    探测下一页；非法 cursor 视为首页。"""
    get_adapter(tenant_id, adapter_name)  # LookupError → router 转 404
    limit = max(1, min(limit, MAX_JOBS_LIMIT))
    stmt = select(OpsTask).where(
        OpsTask.task_type == ADAPTER_TASK_TYPE,
        OpsTask.ref_name == adapter_name,
    )

    decoded = decode_cursor(cursor)
    if decoded is not None:
        anchor = _parse_anchor(decoded)
        if anchor is not None:
            started_at, task_id_anchor = anchor
            stmt = stmt.where(
                or_(
                    OpsTask.started_at < started_at,
                    and_(
                        OpsTask.started_at == started_at,
                        OpsTask.task_id < task_id_anchor,
                    ),
                )
            )

    stmt = stmt.order_by(OpsTask.started_at.desc(), OpsTask.task_id.desc()).limit(
        limit + 1
    )
    rows = (await sess.execute(stmt)).scalars().all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(
            {"s": last.started_at.isoformat(), "i": str(last.task_id)}
        )
    items = [
        AdapterJobItem(
            task_id=row.task_id,
            status=row.status,
            scope=row.scope,
            stats=row.stats or None,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )
        for row in page_rows
    ]
    return items, next_cursor


def _parse_anchor(decoded: dict) -> tuple[datetime, UUID] | None:
    """cursor 载荷 → (started_at, task_id)；缺字段/格式非法 → None。"""
    try:
        return datetime.fromisoformat(str(decoded["s"])), UUID(str(decoded["i"]))
    except (KeyError, TypeError, ValueError):
        return None


async def list_adapters(
    sess: AsyncSession, tenant_id: UUID
) -> list[AdapterListItem]:
    """清单行：静态注册表 + 本租户 catalog SOURCE 系统（已装配 mode=real
    / 未装配 mode=unconfigured）+ 任务状态 + last_sync_at=水位。

    未装配行不探活（无适配器对象）：health/status 均「未配置」；同步/
    状态/日志端点对其 404（get_adapter LookupError）。"""
    await refresh_dynamic(sess, tenant_id)
    items: list[AdapterListItem] = []
    names = sorted(
        set(_registry.list())
        | {name for (tid, name) in _dynamic if tid == tenant_id}
        | {name for (tid, name) in _unconfigured if tid == tenant_id}
    )
    for name in names:
        task = await latest_task(sess, name)
        status = _STATUS_TEXT[task.status] if task is not None else "空闲"
        watermark = await ingest_service.get_watermark(sess, tenant_id, name)
        if is_dynamic(tenant_id, name):
            adapter = get_adapter(tenant_id, name)
            mode = "real"
            health = await probe_health(adapter)
        elif (tenant_id, name) in _unconfigured:
            mode = UNCONFIGURED_MODE
            status = UNCONFIGURED_TEXT
            health = UNCONFIGURED_TEXT
        else:
            adapter = get_adapter(tenant_id, name)
            mode = ADAPTER_MODE_MOCK
            health = await probe_health(adapter)
        items.append(
            AdapterListItem(
                adapter=name,
                mode=mode,
                status=status,
                health=health,
                last_sync_at=watermark,
                system_id=_dynamic_system_ids.get((tenant_id, name)),
            )
        )
    return items
