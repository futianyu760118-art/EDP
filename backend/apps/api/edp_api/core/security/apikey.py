"""API Key 哈希：SHA-256 hex（库存只存 key_hash，明文仅生成时展示一次）。"""

import hashlib


def hash_key(key: str) -> str:
    """raw key → SHA-256 hexdigest（64 位十六进制）。"""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
