"""OpenAPI 契约快照导出/校验（EDP-007）。

用法（在 backend/ 下）：
    uv run python scripts/export_openapi.py          # 生成 contracts/openapi.json + openapi.sha256
    uv run python scripts/export_openapi.py --check  # 校验快照与当前 app 定义一致，不一致 exit 1

指纹格式：openapi.sha256 = 对 openapi.json 文件字节的 SHA-256 hex（纯 hex 一行）。
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parent.parent
CONTRACTS_DIR = BACKEND_ROOT.parent / "contracts"
OPENAPI_PATH = CONTRACTS_DIR / "openapi.json"
FINGERPRINT_PATH = CONTRACTS_DIR / "openapi.sha256"


def render_openapi() -> str:
    from edp_api.main import app

    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def digest_of(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def write_snapshot(content: str) -> None:
    CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
    OPENAPI_PATH.write_text(content, encoding="utf-8", newline="\n")
    FINGERPRINT_PATH.write_text(digest_of(content) + "\n", encoding="utf-8", newline="\n")


def first_diff_path(expected: Any, actual: Any, path: str = "$") -> str | None:
    """深度优先定位 expected/actual 首个差异的 JSON 路径；一致返回 None。"""
    if type(expected) is not type(actual):
        return path
    if isinstance(expected, dict):
        for key in sorted(set(expected) | set(actual)):
            if key not in expected or key not in actual:
                return f"{path}.{key}"
            sub = first_diff_path(expected[key], actual[key], f"{path}.{key}")
            if sub is not None:
                return sub
        return None
    if isinstance(expected, list):
        for idx in range(min(len(expected), len(actual))):
            sub = first_diff_path(expected[idx], actual[idx], f"{path}[{idx}]")
            if sub is not None:
                return sub
        if len(expected) != len(actual):
            return f"{path}[{min(len(expected), len(actual))}]"
        return None
    if expected != actual:
        return path
    return None


def check_snapshot(content: str) -> tuple[bool, str]:
    """返回 (是否一致, 失败原因)；校验文件存在性、json diff 与 sha 指纹。"""
    if not OPENAPI_PATH.exists():
        return False, f"快照缺失：{OPENAPI_PATH}"
    if not FINGERPRINT_PATH.exists():
        return False, f"指纹缺失：{FINGERPRINT_PATH}"

    on_disk = OPENAPI_PATH.read_text(encoding="utf-8")
    if on_disk != content:
        detail = "内容不可解析为 JSON，无法定位差异路径"
        try:
            diff = first_diff_path(
                json.loads(on_disk), json.loads(content)
            )
        except json.JSONDecodeError as exc:
            diff = None
            detail = f"JSON 解析失败：{exc}"
        if diff is not None:
            detail = f"首个差异路径 {diff}（磁盘快照 vs 当前 OpenAPI 定义）"
        return False, f"contracts/openapi.json 与当前 OpenAPI 定义不一致：{detail}"

    recorded = FINGERPRINT_PATH.read_text(encoding="utf-8").strip()
    if recorded != digest_of(content):
        return False, "contracts/openapi.sha256 指纹与 openapi.json 字节不匹配"
    return True, ""


def main() -> int:
    parser = argparse.ArgumentParser(description="导出/校验 OpenAPI 契约快照")
    parser.add_argument("--check", action="store_true", help="校验快照一致，不符 exit 1")
    args = parser.parse_args()

    content = render_openapi()
    if args.check:
        ok, reason = check_snapshot(content)
        if ok:
            print("contract snapshot OK")
            return 0
        print(f"contract snapshot DRIFT: {reason}", file=sys.stderr)
        print(
            "请运行 `uv run python scripts/export_openapi.py` 重新导出并提交"
            "（契约变更需走 [contract] 流程）",
            file=sys.stderr,
        )
        return 1

    write_snapshot(content)
    print(f"wrote {OPENAPI_PATH}")
    print(f"wrote {FINGERPRINT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
