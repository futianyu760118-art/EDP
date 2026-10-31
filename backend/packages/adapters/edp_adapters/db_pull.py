"""通用 DB 拉取适配器（V1.3 T50）：配置驱动的主数据拉取连接器。

取代 T49 的硬编码 SpcPullAdapter——表规格（表名/增量列/归属域/排除列）
与 DSN 全部外置（catalog POST /systems 的 adapter_config），新系统接入
零代码：

- **增量列名任意**（update_time/updated_at/…），无增量列表走全量
  （增量模式下同样拉全集，幂等去重收敛）；
- **敏感列 SQL 级排除**（不进 SELECT 列，非事后剔除）；
- **occurred_at 语义**：有增量列表取增量列值（源系统冻结时间，禁
  now()）；全量表用固定纪元常量（确定性重放——同记录恒同 event_id，
  重拉计 duplicated）；
- source_system = 适配器名（与 CDC 轨同名即双轨同源同口径，对账归并）。

并发约定：fetch_* 以 ``asyncio.run`` 内跑 asyncpg（每次独立连接——低频
任务可接受）；因此**必须在无事件循环的线程中调用**——ingest 管道经
``asyncio.to_thread`` 包裹（见 ingest.service._fetch_records），直接在
async 上下文调用会 RuntimeError。
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from edp_adapters.base import AdapterHealth, SourceAdapter, SourceRecord

# 全量表（无增量列）的 occurred_at 固定纪元：确定性重放保证
FULL_PULL_OCCURRED_AT = datetime(1970, 1, 1, tzinfo=UTC)

_SCHEMA = "public"


@dataclass(slots=True, frozen=True)
class DbTableSpec:
    """单表规格（adapter_config.tables 条目）。"""

    table: str
    increment_column: str | None  # None = 全量拉取
    owner_domain: str = "master"
    excluded_columns: tuple[str, ...] = ()


def _naive_utc(value: datetime) -> datetime:
    """水位参数归一：naive UTC（asyncpg 对 timestamptz 参数按 UTC 解释）。

    datetime.min 等极端值 astimezone 会 OverflowError——降级为直接去 tz
    （极端值下 UTC 换算无意义，安全下限语义保持）。
    """
    if value.tzinfo is None:
        return value
    try:
        return value.astimezone(UTC).replace(tzinfo=None)
    except (OverflowError, ValueError):  # datetime.min 哨兵（ingest _EPOCH）
        return value.replace(tzinfo=None)


def _json_safe(value: Any) -> Any:
    """DB 值 → JSON 原生类型（datetime/date/time→isoformat；Decimal→str）。

    管道 process_record 对 payload 做 json.dumps（RAW/证据快照）——真实
    适配器必须输出 JSON 原生值（mock 天然满足）。
    """
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):  # date / time
        return value.isoformat()
    return value


def build_select_columns(
    all_columns: list[str], excluded: tuple[str, ...]
) -> list[str]:
    """查询列构造：标识符加引号 + 敏感列 SQL 级排除。"""
    return [f'"{c}"' for c in all_columns if c not in excluded]


def build_fetch_sql(
    spec: DbTableSpec, select_columns: list[str], *, incremental: bool
) -> str:
    """拉取 SQL：增量表带 WHERE > $1（占位符，asyncpg 位置参数）。"""
    cols = ", ".join(select_columns)
    table = f'"{_SCHEMA}"."{spec.table}"'
    if incremental and spec.increment_column is not None:
        return (
            f"SELECT {cols} FROM {table}"
            f' WHERE "{spec.increment_column}" > $1'
            f' ORDER BY "{spec.increment_column}", "id"'
        )
    return f"SELECT {cols} FROM {table} ORDER BY \"id\""


def row_to_record(spec: DbTableSpec, row: dict, source_system: str) -> SourceRecord:
    """行 → SourceRecord（occurred_at=增量列值 / 全量表纪元常量）。"""
    if spec.increment_column is not None:
        occurred_at = row.get(spec.increment_column) or FULL_PULL_OCCURRED_AT
        if occurred_at.tzinfo is None:  # naive 时间戳按 UTC 解释
            occurred_at = occurred_at.replace(tzinfo=UTC)
    else:
        occurred_at = FULL_PULL_OCCURRED_AT

    payload = {k: _json_safe(v) for k, v in row.items()}
    payload.setdefault("owner_domain", spec.owner_domain)
    return SourceRecord(
        source_system=source_system,
        object_type=spec.table.upper(),
        source_id=str(row["id"]),
        occurred_at=occurred_at,
        payload=payload,
    )


class DbPullAdapter(SourceAdapter):
    """配置驱动 DB 拉取适配器（name/dsn/table_specs 构造注入）。

    由 catalog systems 行（adapter_config）装配：name=系统名、dsn=
    adapter_config.dsn、table_specs=adapter_config.tables（DbTableSpec
    逐条构造，缺字段由调用方校验——见 adapters_admin.service）。
    """

    def __init__(
        self, name: str, dsn: str, table_specs: Sequence[DbTableSpec]
    ) -> None:
        self.name = name
        self._dsn = dsn
        self._specs = tuple(table_specs)

    def fetch_full(
        self, object_types: list[str], *, anchor: datetime | None = None
    ) -> list[SourceRecord]:
        return asyncio.run(self._fetch(object_types, incremental=False, since=None))

    def fetch_incremental(
        self, since: datetime, *, anchor: datetime | None = None
    ) -> list[SourceRecord]:
        return asyncio.run(self._fetch(object_types=[], incremental=True, since=since))

    def health_check(self) -> AdapterHealth:
        try:
            return asyncio.run(self._health())
        except Exception as exc:  # noqa: BLE001 — 探活失败即 DEGRADED
            return AdapterHealth(ok=False, detail=str(exc))

    def _specs_for(self, object_types: list[str]) -> list[DbTableSpec]:
        if not object_types:
            return list(self._specs)
        wanted = set(object_types)
        return [s for s in self._specs if s.table.upper() in wanted]

    async def _fetch(
        self,
        object_types: list[str],
        *,
        incremental: bool,
        since: datetime | None,
    ) -> list[SourceRecord]:
        import asyncpg

        records: list[SourceRecord] = []
        conn = await asyncpg.connect(self._dsn, timeout=5)
        try:
            for spec in self._specs_for(object_types):
                columns = [
                    row["column_name"]
                    for row in await conn.fetch(
                        """
                        SELECT column_name FROM information_schema.columns
                        WHERE table_schema = $1 AND table_name = $2
                        ORDER BY ordinal_position
                        """,
                        _SCHEMA,
                        spec.table,
                    )
                ]
                if not columns:
                    continue  # 表在对端不存在：跳过不报错
                sql = build_fetch_sql(
                    spec, build_select_columns(columns, spec.excluded_columns),
                    incremental=incremental,
                )
                if incremental and spec.increment_column:
                    params = (_naive_utc(since),)
                else:
                    params = ()
                rows = await conn.fetch(sql, *params)
                records.extend(
                    row_to_record(spec, dict(row), self.name) for row in rows
                )
        finally:
            await conn.close()
        return records

    async def _health(self) -> AdapterHealth:
        import asyncpg

        conn = await asyncpg.connect(self._dsn, timeout=5)
        try:
            await conn.fetchval("SELECT 1")
        finally:
            await conn.close()
        return AdapterHealth(ok=True, detail="db pull ready")
