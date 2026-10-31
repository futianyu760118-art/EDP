"""事件确定性 event_id（UUIDv5 幂等之适配器层，设计文档 7.1）——纯函数。

规范（全局冻结，客户端/服务端/对账任务必须一致）：
- tenant_ns = UUIDv5(NIL, str(tenant_id))（NIL = UUID(int=0)，Python 3.12 的
  uuid 模块尚无 NIL 常量）——命名空间含租户，event_id 天然租户隔离（跨租户
  同输入也不同 UUID）；
- name = f"{source_system}|{source_id}|{occurred_at_iso}|{event_type}"；
- occurred_at 归一化：naive 视为 UTC，aware 一律 astimezone(UTC)；序列化取
  isoformat() 语义——微秒最多 6 位（datetime 本身精度），非零才出现小数
  部分，偏移恒为 "+00:00"。
  例："2026-09-28T08:00:00+00:00" / "2026-09-28T08:00:00.123456+00:00"。
"""

from datetime import UTC, datetime
from uuid import UUID, uuid5

_NIL = UUID(int=0)


def tenant_namespace(tenant_id: UUID) -> UUID:
    """租户命名空间：UUIDv5(NIL, str(tenant_id))；确定性（同租户同 ns）。"""
    return uuid5(_NIL, str(tenant_id))


def normalize_occurred_at(value: datetime) -> datetime:
    """occurred_at 归一化到 UTC：naive 按 UTC 解释，aware 转 UTC。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def derive_event_id(
    tenant_id: UUID,
    source_system: str,
    source_id: str,
    occurred_at: datetime,
    event_type: str,
) -> UUID:
    """确定性 event_id = UUIDv5(tenant_ns, name)。

    同一 (tenant, source_system, source_id, occurred_at, event_type) 重放恒
    产生相同 UUID → 数据层 ON CONFLICT DO NOTHING 天然幂等（7.1 适配器层）。
    """
    normalized = normalize_occurred_at(occurred_at)
    name = f"{source_system}|{source_id}|{normalized.isoformat()}|{event_type}"
    return uuid5(tenant_namespace(tenant_id), name)
