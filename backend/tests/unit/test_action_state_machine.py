"""T2 Action 状态机单测（EDP-020，设计 7.5）：TRANSITIONS 全组合。

期望不从 TRANSITIONS 复读，而由设计 7.5 状态机图的独立表述推导：
- 主链 PROPOSED→ASSIGNED→ACCEPTED→APPROVED→EXECUTING→COMPLETED→VERIFIED；
- PROPOSED 另有拒绝边 → REJECTED；
- 任意非终态 → CANCELLED（取消边）；
- 终态 VERIFIED/CANCELLED/REJECTED 无出边；
- 恰两条 Human-Only 边：APPROVED→EXECUTING、COMPLETED→VERIFIED。

覆盖：
1. 9 态 × 9 目标全组合：允许/禁止与期望逐格一致；
2. 允许边的 human_only 标记逐格一致（恰两条 True）；
3. 终态无出边：TRANSITIONS 空表 + allowed_to() == []；
4. allowed_to 输出形状 [{to_status, human_only}] 且 to_status 字典序稳定；
5. TRANSITIONS 键集 = 9 态（无未知状态）。
"""

import pytest
from edp_api.modules.actions.service import TRANSITIONS, allowed_to

ALL_STATES = [
    "PROPOSED",
    "ASSIGNED",
    "ACCEPTED",
    "APPROVED",
    "EXECUTING",
    "COMPLETED",
    "VERIFIED",
    "CANCELLED",
    "REJECTED",
]
TERMINAL = {"VERIFIED", "CANCELLED", "REJECTED"}

# 设计 7.5 主链边 + PROPOSED 拒绝边
MAIN_LINE = {
    "PROPOSED": "ASSIGNED",
    "ASSIGNED": "ACCEPTED",
    "ACCEPTED": "APPROVED",
    "APPROVED": "EXECUTING",
    "EXECUTING": "COMPLETED",
    "COMPLETED": "VERIFIED",
}
HUMAN_ONLY_EDGES = {("APPROVED", "EXECUTING"), ("COMPLETED", "VERIFIED")}


def expected_allowed(from_status: str, to_status: str) -> bool:
    """设计 7.5 图导出：主链下一态、拒绝边（仅 PROPOSED）、取消边（非终态）。"""
    if from_status in TERMINAL:
        return False
    if to_status == "CANCELLED":
        return True
    if from_status == "PROPOSED" and to_status == "REJECTED":
        return True
    return MAIN_LINE.get(from_status) == to_status


# ---- 1+2. 9 态 × 9 目标全组合：允许性与 human_only 逐格断言 ----


@pytest.mark.parametrize("from_status", ALL_STATES)
@pytest.mark.parametrize("to_status", ALL_STATES)
def test_transition_matrix_full_grid(from_status: str, to_status: str) -> None:
    targets = TRANSITIONS[from_status]
    if expected_allowed(from_status, to_status):
        assert to_status in targets, f"应允许 {from_status}→{to_status}"
        assert targets[to_status] is (
            (from_status, to_status) in HUMAN_ONLY_EDGES
        ), f"human_only 标记不符：{from_status}→{to_status}"
    else:
        assert to_status not in targets, f"应禁止 {from_status}→{to_status}"


def test_exactly_two_human_only_edges() -> None:
    """全表恰两条 human_only=True：APPROVED→EXECUTING、COMPLETED→VERIFIED。"""
    edges = {
        (from_status, to_status)
        for from_status, targets in TRANSITIONS.items()
        for to_status, human_only in targets.items()
        if human_only is True
    }
    assert edges == HUMAN_ONLY_EDGES


def test_transitions_covers_exactly_nine_states() -> None:
    """键集 = 9 态，无未知状态。"""
    assert set(TRANSITIONS) == set(ALL_STATES)


# ---- 3. 终态无出边 ----


@pytest.mark.parametrize("status", sorted(TERMINAL))
def test_terminal_states_have_no_out_edges(status: str) -> None:
    assert TRANSITIONS[status] == {}
    assert allowed_to(status) == []


# ---- 4. allowed_to 形状与字典序稳定 ----


@pytest.mark.parametrize("status", ALL_STATES)
def test_allowed_to_shape_and_stable_order(status: str) -> None:
    items = allowed_to(status)
    assert all(set(item) == {"to_status", "human_only"} for item in items)
    assert [item["to_status"] for item in items] == sorted(
        item["to_status"] for item in items
    )
    assert items == allowed_to(status)  # 重复调用稳定
    assert [item["to_status"] for item in items] == sorted(
        TRANSITIONS[status]
    ), "allowed_to 应覆盖 TRANSITIONS 全部目标且按 to_status 字典序"


def test_allowed_to_proposed_example() -> None:
    """B.5 典型：PROPOSED → [ASSIGNED, CANCELLED, REJECTED]（字典序，全非
    Human-Only）。"""
    assert allowed_to("PROPOSED") == [
        {"to_status": "ASSIGNED", "human_only": False},
        {"to_status": "CANCELLED", "human_only": False},
        {"to_status": "REJECTED", "human_only": False},
    ]


def test_allowed_to_approved_marks_human_only() -> None:
    assert allowed_to("APPROVED") == [
        {"to_status": "CANCELLED", "human_only": False},
        {"to_status": "EXECUTING", "human_only": True},
    ]
