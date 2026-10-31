import base64
import json

import pytest
from edp_api.core.pagination import Page, decode_cursor, encode_cursor


def _b64(raw: str) -> str:
    return base64.urlsafe_b64encode(raw.encode()).rstrip(b"=").decode()


def test_roundtrip() -> None:
    payload = {
        "sort_key": "2026-09-14T00:00:00+00:00",
        "tiebreak_id": "0d9c4b1e-8f2a-4c1d-9e77-3a2b1c0d9e11",
    }
    cursor = encode_cursor(payload)
    assert isinstance(cursor, str)
    assert decode_cursor(cursor) == payload


def test_cursor_is_compact_base64url_without_padding() -> None:
    cursor = encode_cursor({"a": 1, "b": [1, 2]})
    assert "=" not in cursor
    assert "+" not in cursor
    assert "/" not in cursor
    assert " " not in cursor


def test_decode_none() -> None:
    assert decode_cursor(None) is None


def test_decode_empty_string() -> None:
    assert decode_cursor("") is None


@pytest.mark.parametrize("bad", ["!!!not-base64!!!", "abcde", "a*b*c", "\x00\x01"])
def test_decode_invalid_base64_returns_none(bad: str) -> None:
    assert decode_cursor(bad) is None


def test_decode_non_json_returns_none() -> None:
    assert decode_cursor(_b64("not-json")) is None


def test_decode_non_dict_json_returns_none() -> None:
    assert decode_cursor(_b64(json.dumps([1, 2, 3]))) is None
    assert decode_cursor(_b64(json.dumps("x"))) is None
    assert decode_cursor(_b64("42")) is None


def test_unicode_roundtrip() -> None:
    payload = {"姓名": "张三", "query": "检索>词&?=", "emoji": "✅"}
    assert decode_cursor(encode_cursor(payload)) == payload


def test_page_generic_model_roundtrip() -> None:
    page = Page[str](items=["a", "b"], next_cursor=encode_cursor({"k": 1}))
    assert page.items == ["a", "b"]
    assert decode_cursor(page.next_cursor) == {"k": 1}

    empty = Page[str](items=[])
    assert empty.next_cursor is None
    assert empty.total is None
    assert empty.model_dump() == {"items": [], "next_cursor": None, "total": None}

    counted = Page[str](items=["a"], total=7)
    assert counted.total == 7


def test_page_model_validate_nested() -> None:
    from pydantic import BaseModel

    class Sku(BaseModel):
        id: str

    page = Page[Sku].model_validate({"items": [{"id": "sku-1"}], "next_cursor": "cur"})
    assert page.items[0].id == "sku-1"
    assert page.next_cursor == "cur"
