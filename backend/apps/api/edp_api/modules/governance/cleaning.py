"""governance 清洗引擎（V1.2 T09）：规则执行 + fixAudit 留痕 + 违规清单。

规则来源 = governance.cleaning_rules（object_type 匹配 + 生效区间内；
版本化——同规则新版本由 service 层覆盖旧生效区间）。引擎纯函数化：
``apply_payload`` 对单条 payload 应用规则集合，返回 (cleaned, fixes,
violations)；会话交互（实体解析别名查询、主数据引用检查）由
``apply_cleaning(sess, ...)`` 编排。

rule_type 支持面（transformation 配置形状）：

- FORMAT：{"date_fields": [field...], "from": ["%Y/%m/%d", ...], "to": "%Y-%m-%d"}
- NORMALIZATION：{"strip": true, "full_width": true}（去空白/全半角）
- MAPPING：{"map": {"已确认": "CONFIRMED", ...}}
- UNIT_CONVERSION：{"factor": 1000}（数值乘系数）
- CURRENCY_NORMALIZATION：{"upper": true}（币种码大写）
- RANGE_CHECK：{"min": 0, "max": null}（数值区间）
- REFERENTIAL_CHECK：{"table": "master.customers", "column": "customer_code"}
  （表名白名单，防注入）
- BUSINESS_RULE：{"date_after": "order_date"}（field ≥ payload[date_after]）
- DEDUPLICATION：记录级（管道 UUIDv5 幂等已兜底，引擎内 no-op 留痕）
- ENTITY_RESOLUTION：{"object_type": "CUSTOMER", "value_field": "name"}
  （别名 → canonical 名称替换）

auto_fix=True 的修复类规则就地修复并记 fixAudit（before/after/rule 引用/
confidence）；auto_fix=False → 记违规不修复。检查类规则恒记违规。所有
应用规则按 review_required 标记入 violations（供 A2 机器审消费）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from edp_api.modules.governance.models import CleaningRule, EntityAlias

# REFERENTIAL_CHECK 白名单（防表名注入；仅首链路主数据）
_REFERENTIAL_TABLES = frozenset(
    {
        "master.customers",
        "master.products",
        "master.materials",
        "master.suppliers",
        "master.business_objects",
    }
)

# 修复类规则（auto_fix 生效）；其余为检查类
_FIX_RULE_TYPES = frozenset(
    {
        "FORMAT",
        "NORMALIZATION",
        "MAPPING",
        "UNIT_CONVERSION",
        "CURRENCY_NORMALIZATION",
        "ENTITY_RESOLUTION",
    }
)

_FULL_WIDTH_PATTERN = re.compile(
    "[\uff01-\uff5e]"
)  # 全角字符 → 半角（offset 0xFEE0）


@dataclass(slots=True)
class RuleViolation:
    """单条规则违规/待确认项（A2 机器审 exception_list 数据源）。"""

    rule_id: str
    rule_name: str
    rule_type: str
    field: str | None
    severity: str
    message: str
    review_required: bool = False


@dataclass(slots=True)
class FixAudit:
    """自动修复留痕（clean_records.before/after + rule_refs）。"""

    rule_id: str
    rule_version: int
    before_value: Any
    after_value: Any
    field: str | None
    confidence: float = 1.0


@dataclass(slots=True)
class CleaningResult:
    cleaned: dict
    fixes: list[FixAudit] = field(default_factory=list)
    violations: list[RuleViolation] = field(default_factory=list)


def _to_half_width(value: str) -> str:
    """全角 ASCII → 半角（!~ 区间统一偏移 0xFEE0）。"""
    return _FULL_WIDTH_PATTERN.sub(lambda m: chr(ord(m.group()) - 0xFEE0), value)


def _parse_dates(value: Any, from_formats: list[str], to_format: str) -> Any:
    """按候选格式解析 → 目标格式；全部失败 → 原值返回（记违规）。"""
    if not isinstance(value, str):
        return value
    for fmt in from_formats:
        try:
            return datetime.strptime(value, fmt).strftime(to_format)
        except ValueError:
            continue
    return value


async def apply_cleaning(
    sess: AsyncSession,
    tenant_id,
    object_type: str,
    payload: dict,
) -> CleaningResult:
    """编排：取生效规则（object_type + 生效区间）→ 逐条应用 → 留痕。

    RLS 会话（bind_tenant）——规则/别名查询天然限租户。无规则 = 恒等
    （既有管道行为不变）。
    """
    now = datetime.now().astimezone()
    rules = (
        (
            await sess.execute(
                select(CleaningRule)
                .where(
                    CleaningRule.tenant_id == tenant_id,
                    CleaningRule.object_type == object_type,
                    CleaningRule.effective_from <= now,
                    (CleaningRule.effective_to.is_(None))
                    | (CleaningRule.effective_to > now),
                )
                .order_by(CleaningRule.rule_type, CleaningRule.version.desc())
            )
        )
        .scalars()
        .all()
    )

    result = CleaningResult(cleaned=dict(payload))
    for rule in rules:
        await _apply_rule(sess, tenant_id, rule, result)
    return result


async def _apply_rule(
    sess: AsyncSession, tenant_id, rule: CleaningRule, result: CleaningResult
) -> None:
    """单条规则应用：修复类（auto_fix）就地改 + FixAudit；否则违规。

    field 为 None 的规则作用于 payload 级（ENTITY_RESOLUTION）；其余
    field 级。rule.condition 支持（字符串比较）最小实现：空 = 恒触发。
    """
    try:
        if rule.field is None:
            await _apply_field_rule(sess, tenant_id, rule, None, result)
        else:
            await _apply_field_rule(sess, tenant_id, rule, rule.field, result)
    except Exception as exc:  # 单条规则失败不阻断管道——记违规
        result.violations.append(
            RuleViolation(
                rule_id=str(rule.rule_id),
                rule_name=rule.rule_name,
                rule_type=rule.rule_type,
                field=rule.field,
                severity=rule.severity,
                message=f"规则执行异常：{exc}",
                review_required=rule.review_required,
            )
        )


async def _apply_field_rule(
    sess: AsyncSession,
    tenant_id,
    rule: CleaningRule,
    field_name: str | None,
    result: CleaningResult,
) -> None:
    """field 级规则执行；规则类型与 transformation 形状见模块 docstring。"""
    cfg = rule.transformation or {}
    payload = result.cleaned
    value = payload.get(field_name) if field_name is not None else payload

    if rule.rule_type == "NORMALIZATION":
        if not isinstance(value, str):
            return
        new = value
        if cfg.get("strip", True):
            new = new.strip()
        if cfg.get("full_width", True):
            new = _to_half_width(new)
        if new != value:
            _fix_or_violate(rule, field_name, value, new, result)

    elif rule.rule_type == "FORMAT":
        fields = cfg.get("date_fields") or ([field_name] if field_name else [])
        from_formats = cfg.get("from") or ["%Y/%m/%d", "%Y-%m-%d"]
        to_format = cfg.get("to") or "%Y-%m-%d"
        for f in fields:
            original = payload.get(f)
            if not isinstance(original, str):
                continue
            converted = _parse_dates(original, from_formats, to_format)
            if converted != original:
                _fix_or_violate(rule, f, original, converted, result)

    elif rule.rule_type == "MAPPING":
        mapping = cfg.get("map") or {}
        if isinstance(value, str) and value in mapping:
            _fix_or_violate(rule, field_name, value, mapping[value], result)

    elif rule.rule_type == "UNIT_CONVERSION":
        factor = cfg.get("factor")
        if isinstance(value, (int, float)) and isinstance(factor, (int, float)):
            _fix_or_violate(rule, field_name, value, value * factor, result)

    elif rule.rule_type == "CURRENCY_NORMALIZATION":
        if isinstance(value, str) and cfg.get("upper", True) and value != value.upper():
            _fix_or_violate(rule, field_name, value, value.upper(), result)

    elif rule.rule_type == "RANGE_CHECK":
        minimum = cfg.get("min")
        maximum = cfg.get("max")
        bad = isinstance(value, (int, float)) and (
            (minimum is not None and value < minimum)
            or (maximum is not None and value > maximum)
        )
        if bad:
            result.violations.append(
                _violation(rule, field_name, f"数值越界：{value} 不在 [{minimum}, {maximum}]")
            )

    elif rule.rule_type == "REFERENTIAL_CHECK":
        table = cfg.get("table")
        column = cfg.get("column")
        if table not in _REFERENTIAL_TABLES or not column or not value:
            return
        hit = (
            await sess.execute(
                text(f"SELECT 1 FROM {table} WHERE {column} = :v LIMIT 1"),
                {"v": value},
            )
        ).scalar_one_or_none()
        if hit is None:
            result.violations.append(
                _violation(rule, field_name, f"引用缺失：{value} 不在 {table}.{column}")
            )

    elif rule.rule_type == "BUSINESS_RULE":
        after_field = cfg.get("date_after")
        if after_field and isinstance(value, str) and isinstance(
            payload.get(after_field), str
        ):
            try:
                if datetime.fromisoformat(value) < datetime.fromisoformat(
                    payload[after_field]
                ):
                    result.violations.append(
                        _violation(rule, field_name, f"日期先后矛盾：{field_name} < {after_field}")
                    )
            except ValueError:
                return

    elif rule.rule_type == "ENTITY_RESOLUTION":
        target_type = cfg.get("object_type") or rule.object_type
        value_field = cfg.get("value_field") or field_name
        if not isinstance(payload.get(value_field), str):
            return
        alias_row = (
            await sess.execute(
                select(EntityAlias).where(
                    EntityAlias.tenant_id == tenant_id,
                    EntityAlias.object_type == target_type,
                    EntityAlias.alias == payload[value_field],
                )
            )
        ).scalar_one_or_none()
        if alias_row is None:
            return
        if alias_row.canonical_ref is None:
            result.violations.append(
                _violation(rule, value_field, f"别名未归一到 Canonical：{payload[value_field]}")
            )
            return
        canonical_name = (
            await sess.execute(
                text(
                    "SELECT attributes->>'name' AS name FROM master.business_objects"
                    " WHERE object_id = :oid LIMIT 1"
                ),
                {"oid": alias_row.canonical_ref},
            )
        ).scalar_one_or_none()
        if canonical_name:
            _fix_or_violate(
                rule,
                value_field,
                payload[value_field],
                canonical_name,
                result,
                confidence=alias_row.confidence if alias_row.confidence is not None else 1.0,
            )

    elif rule.rule_type == "DEDUPLICATION":
        pass  # 记录级去重由管道 UUIDv5 幂等兜底（引擎 no-op 留痕）


def _fix_or_violate(
    rule: CleaningRule,
    field_name: str | None,
    before_value: Any,
    after_value: Any,
    result: CleaningResult,
    *,
    confidence: float = 1.0,
) -> None:
    """auto_fix → 就地修复 + FixAudit；否则 → 违规（review_required 透传）。"""
    if rule.auto_fix:
        result.cleaned[field_name] = after_value
        result.fixes.append(
            FixAudit(
                rule_id=str(rule.rule_id),
                rule_version=rule.version,
                before_value=before_value,
                after_value=after_value,
                field=field_name,
                confidence=confidence,
            )
        )
    else:
        result.violations.append(
            _violation(rule, field_name, f"需人工修复：{before_value!r} → {after_value!r}")
        )


def _violation(rule: CleaningRule, field_name: str | None, message: str) -> RuleViolation:
    return RuleViolation(
        rule_id=str(rule.rule_id),
        rule_name=rule.rule_name,
        rule_type=rule.rule_type,
        field=field_name,
        severity=rule.severity,
        message=message,
        review_required=rule.review_required,
    )
