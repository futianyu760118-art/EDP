"""EDP 上游适配器纯端口包：SourceAdapter 协议 + 注册表 + 确定性数据集。"""

from .base import AdapterHealth, SourceAdapter, SourceRecord
from .demo_erp import DemoErpAdapter
from .demo_plm import DemoPlmAdapter
from .erp_mock import ErpMockAdapter, all_records
from .mes_mock import DemoMesAdapter
from .registry import AdapterRegistry
from .stream import StreamParseError, StreamRoute, parse_debezium_event

__all__ = [
    "AdapterHealth",
    "AdapterRegistry",
    "DemoErpAdapter",
    "DemoMesAdapter",
    "DemoPlmAdapter",
    "ErpMockAdapter",
    "SourceAdapter",
    "SourceRecord",
    "StreamParseError",
    "StreamRoute",
    "all_records",
    "parse_debezium_event",
]
