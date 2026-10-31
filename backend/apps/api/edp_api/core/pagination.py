"""游标分页：opaque cursor = 紧凑 JSON 的 base64url（无填充）。"""

import base64
import json

from pydantic import BaseModel


def encode_cursor(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_cursor(cursor: str | None) -> dict | None:
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None
    total: int | None = None
