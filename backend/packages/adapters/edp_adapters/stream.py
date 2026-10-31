"""实时流端口（V1.3 T44）：Debezium 信封 → SourceRecord 纯转换。

纯端口包（同 base.py 约定）：无 IO 副作用、不依赖 edp_api。时间语义
冻结（方案 V1.3 §2.2）：occurred_at 一律取 payload.ts_ms（源库事务提交
时刻，毫秒纪元 UTC），禁止消费侧 now()——与拉取适配器"源系统冻结时间
窗"同一约定，保证确定性重放。

契约：contracts/realtime/debezium-event.schema.json（schema-gate 冻结）。
映射语义：
- payload.after → SourceRecord.payload（缺失 owner_domain 时按路由缺省注入
  ——process_record 管道必需字段）；
- payload.source.table → object_type（大写化，须匹配 OBJECT_TYPE_PATTERN），
  路由 object_type 可覆写（如 orders → ORDER）；
- pk_columns 值（str 化）以 "-" 拼接 → source_id（须匹配
  SOURCE_ID_PATTERN；两 pattern 与 registry.schemas 冻结值保持一致）；
- op=c/r/u 为可处理快照语义；op=d 与 tombstone（after=null）→ None
  （对象层 upsert-only，删除语义后续阶段另行裁决）；
- 解析失败抛 StreamParseError（消费侧进 DLQ，不阻断分区消费）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from edp_adapters.base import SourceRecord

# 与 edp_api.modules.registry.schemas 冻结值一致（adapters 包不得 import
# edp_api——此处按契约复制并在测试中锁定语义）
OBJECT_TYPE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
SOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@#/-]{0,127}$")

_DELETE_OPS = frozenset({"d"})


class StreamParseError(ValueError):
    """信封解析失败（消费侧进 DLQ，不阻断分区消费）。"""


@dataclass(slots=True, frozen=True)
class StreamRoute:
    """topic → 转换参数的路由（消费侧配置装配，纯数据）。

    - topic：Kafka topic 精确匹配（命名规范 edp.{tenant}.{system}.{table}，
      方案 V1.3 §2.1）；
    - source_system：落 SourceRecord.source_system（与拉取轨同名即双轨
      同源——对账按此归并）；
    - pk_columns：源表主键列（复合主键按序拼接）；
    - owner_domain：payload 缺失时的缺省域（管道必需字段）；
    - object_type：缺省从 source.table 大写派生；显式覆写（orders → ORDER）。
    """

    topic: str
    source_system: str
    pk_columns: tuple[str, ...] = ("id",)
    owner_domain: str = "master"
    object_type: str | None = None


def parse_debezium_event(event: dict, route: StreamRoute) -> SourceRecord | None:
    """Debezium 信封（dict）→ SourceRecord；op=d / tombstone → None。

    任何结构缺字段 / 派生值越 pattern → StreamParseError（含原因）。
    """
    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise StreamParseError("信封缺少 payload 对象")

    op = payload.get("op")
    if not isinstance(op, str) or not op:
        raise StreamParseError("payload.op 缺失或非字符串")

    after = payload.get("after")
    if op in _DELETE_OPS or after is None:
        return None

    ts_ms = payload.get("ts_ms")
    if not isinstance(ts_ms, int) or isinstance(ts_ms, bool) or ts_ms < 0:
        raise StreamParseError("payload.ts_ms 缺失或非法（须为非负整数毫秒纪元）")

    source = payload.get("source")
    if not isinstance(source, dict):
        raise StreamParseError("payload.source 缺失")

    if route.object_type is not None:
        object_type = route.object_type
    else:
        table = source.get("table")
        if not isinstance(table, str) or not table:
            raise StreamParseError("payload.source.table 缺失")
        object_type = table.upper()
    if not OBJECT_TYPE_PATTERN.fullmatch(object_type):
        raise StreamParseError(f"object_type 越界：{object_type!r}")

    pk_values: list[str] = []
    for column in route.pk_columns:
        value = after.get(column)
        if value is None:
            raise StreamParseError(f"after 缺少主键列：{column}")
        pk_values.append(str(value))
    source_id = "-".join(pk_values)
    if not SOURCE_ID_PATTERN.fullmatch(source_id):
        raise StreamParseError(f"source_id 越界：{source_id!r}")

    normalized_payload = dict(after)
    normalized_payload.setdefault("owner_domain", route.owner_domain)

    return SourceRecord(
        source_system=route.source_system,
        object_type=object_type,
        source_id=source_id,
        occurred_at=datetime.fromtimestamp(ts_ms / 1000, tz=UTC),
        payload=normalized_payload,
    )
