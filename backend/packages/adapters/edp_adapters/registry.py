"""适配器注册表：进程内名称 → 适配器实例映射（T16 sync API 装配用）。"""

from __future__ import annotations

from .base import SourceAdapter


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, SourceAdapter] = {}

    def register(self, adapter: SourceAdapter) -> None:
        self._adapters[adapter.name] = adapter

    def get(self, name: str) -> SourceAdapter:
        try:
            return self._adapters[name]
        except KeyError:
            raise LookupError(
                f"adapter not registered: {name}"
                f" (available: {', '.join(self.list()) or 'none'})"
            ) from None

    def list(self) -> list[str]:
        return sorted(self._adapters)
