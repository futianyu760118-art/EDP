"""契约包 JSON Schema 校验（V1.2 T07）。

遍历 contracts/ 下全部 *.schema.json，逐文件：
1. JSON 可解析；
2. Draft 2020-12 meta-schema 结构校验（check_schema）；
3. 基本自洽性检查（$schema / $id / title 存在，$id 与仓库相对路径一致）。

运行：uv run --with jsonschema python scripts/validate_contract_schemas.py
（jsonschema 不进入后端运行时依赖；CI 经 --with 注入。）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts"


def main() -> int:
    if not CONTRACTS_DIR.is_dir():
        print(f"contracts/ 目录不存在：{CONTRACTS_DIR}", file=sys.stderr)
        return 1

    try:
        from jsonschema import Draft202012Validator
    except ImportError:  # pragma: no cover
        print("缺少 jsonschema：请以 `uv run --with jsonschema` 运行（CI 已注入）", file=sys.stderr)
        return 1

    files = sorted(p for p in CONTRACTS_DIR.rglob("*.schema.json") if p.is_file())
    if not files:
        print("contracts/ 下无 *.schema.json 文件", file=sys.stderr)
        return 1

    failures: list[str] = []
    for path in files:
        rel = path.relative_to(Path(__file__).resolve().parents[2]).as_posix()
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            failures.append(f"{rel}: JSON 解析失败 {exc}")
            continue

        for field in ("$schema", "$id", "title"):
            if field not in schema:
                failures.append(f"{rel}: 缺少 {field}")

        expected_id = path.relative_to(CONTRACTS_DIR).as_posix()
        if schema.get("$id") not in (expected_id, f"contracts/{expected_id}"):
            failures.append(f"{rel}: $id={schema.get('$id')!r} 与路径不一致（应为 {expected_id}）")

        try:
            Draft202012Validator.check_schema(schema)
        except Exception as exc:  # SchemaError / ValidationError 均为 ValueError 子类
            failures.append(f"{rel}: meta-schema 校验失败 {exc}")

    for msg in failures:
        print(msg, file=sys.stderr)

    print(f"schema-gate: {len(files) - len(failures)}/{len(files)} 通过")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
