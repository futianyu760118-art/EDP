"""演示数据集（EDP-016）：十场景故事线回流段（能力结果 + 场景 2 决策案例）。

归属：回流段常量放 modules/demo（快照段常量在 edp_adapters.demo_dataset，
适配器不得依赖 edp_api）。seed 服务（service.py）消费本模块：

- RESULT_EVENTS → events/batch 服务调用（object_ref 自然键 seed 时解析
  object_id；occurred_at = anchor + offset_minutes）；risk_level 非空的事件
  由服务端自动落结果证据（T9）；
- DEMO_CASE → decisions 服务创建（OPEN；source_event_ref 指向场景 2 结果
  事件的对象自然键，evidence_source_refs 自然键 seed 时解析为源快照证据
  id）；
- MGMT_OBJECTIVES / MGMT_KPI_DEFINITIONS / MGMT_KPI_VALUES → management 段
  （W4，EDP-012 残余）：objectives period = 锚当月（YYYY-MM）、kpi_values
  period = 锚 ISO 周（YYYY-Www）± 偏移；
- 放大段常量与纯函数（W6 T5）：SCALE_* / scale_suffix /
  scaled_activity_event_type / scaled_risk_level——seed --scale N 的确定性
  扩展口径（见文件尾段约定）。

确定性：无随机数、无 now()；值对齐 frontend MSW data/events.ts 逐字段与
data/ebms.ts 的 summary/order_no 文案逐字；重放幂等键 seed-demo:results:v1；
management 行 id = uuid5(NIL, "seed-mgmt:...")（重跑 0 新增）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResultEventSpec:
    """单条能力结果回流事件（events/batch 输入）。"""

    event_type: str  # capability.result.* / adapter.sync.failed
    result_type: str  # ORDER_RISK/ORDER_QUALITY/PRODUCT_READINESS/DATA_QUALITY/ADAPTER
    risk_level: str | None  # P0~P3；场景 10 的 adapter.sync.failed 为 P2
    score: float | None
    object_ref: tuple[str, str]  # (object_type, source_id)，seed 时解析 object_id
    offset_minutes: int  # anchor + offset（负值 = 过去）
    data: dict  # reason/recommendation/summary/order_no（EBMS 读取）
    source_system: str = "agent-hub"
    actor_type: str = "AI"
    actor_id: str | None = None


@dataclass(frozen=True, slots=True)
class CaseOptionSpec:
    """决策案例选项（B.5 options[{key,label}]）。"""

    key: str
    label: str


@dataclass(frozen=True, slots=True)
class DemoCaseSpec:
    """场景 2 决策案例（M4 主线：关键料缺失）。"""

    question: str
    context: dict
    options: tuple[CaseOptionSpec, ...]
    risk_level: str
    source_event_ref: tuple[str, str]  # 源结果事件的对象自然键
    evidence_source_refs: tuple[tuple[str, str], ...]  # 证据来源对象自然键


@dataclass(frozen=True, slots=True)
class ObjectiveSpec:
    """经营目标（A.8 management.objectives；period 由 seed 锚派生当月）。"""

    title: str
    metric_type: str
    target_value: float
    current_value: float
    status: str = "ACTIVE"


@dataclass(frozen=True, slots=True)
class KpiDefinitionSpec:
    """KPI 定义（A.8 management.kpi_definitions）。"""

    code: str
    name: str
    unit: str


@dataclass(frozen=True, slots=True)
class KpiValueSpec:
    """KPI 数值（A.8 management.kpi_values；period = seed 锚 ISO 周 + 偏移）。"""

    code: str
    week_offset: int  # 0 = 锚当周、-1 = 前一周
    value: float


RESULT_EVENTS: tuple[ResultEventSpec, ...] = (
    # 场景 1：正常订单 A（P3，无风险；对齐 events.ts 26h 前）
    ResultEventSpec(
        "capability.result.order_risk",
        "ORDER_RISK",
        "P3",
        0.08,
        ("ORDER", "SO-2026-00122"),
        -26 * 60,
        {
            "reason": "物料充足",
            "recommendation": "无（正常）",
            "summary": "物料充足，无交付风险",
            "order_no": "SO-2026-00122",
        },
        actor_id="agent:delivery-order-risk",
    ),
    # 场景 2：关键料缺失 B（P1，M4 主线；缺口 1000、交期 10 天、预计延误 5 天）
    ResultEventSpec(
        "capability.result.order_risk",
        "ORDER_RISK",
        "P1",
        0.86,
        ("ORDER", "SO-2026-00123"),
        -5 * 60,
        {
            "reason": "物料X缺口1000",
            "recommendation": "加急采购/替代料",
            "expected_delay_days": 5,
            "summary": "物料X缺口1000，预计延误5天",
            "order_no": "SO-2026-00123",
        },
        actor_id="agent:delivery-order-risk",
    ),
    # 场景 3：供应商延迟 C（P2，PO-2026-00785 推迟 2 周）
    ResultEventSpec(
        "capability.result.order_risk",
        "ORDER_RISK",
        "P2",
        0.64,
        ("ORDER", "SO-2026-00124"),
        -20 * 60,
        {
            "reason": "PO 预计到货推迟 2 周",
            "recommendation": "确认交期，调整生产计划",
            "summary": "PO-2026-00785 预计到货推迟 2 周",
            "order_no": "SO-2026-00124",
        },
        actor_id="agent:delivery-order-risk",
    ),
    # 场景 4：新品未验证 D（P2，PRJ-D 验证中/未达产）
    ResultEventSpec(
        "capability.result.product_readiness",
        "PRODUCT_READINESS",
        "P2",
        0.55,
        ("PROJECT", "PRJ-D"),
        -32 * 60,
        {
            "readiness": "未达产",
            "blocking": "完成验证与测试",
            "reason": "新品D项目验证中",
            "recommendation": "推进验证与测试，确认量产就绪",
            "summary": "新品D项目验证中，未达量产就绪",
            "order_no": "PRJ-D",
        },
        actor_id="agent:rd-product-readiness",
    ),
    # 场景 5：高值低库存 E（P1，产品 F 仅剩 38）
    ResultEventSpec(
        "capability.result.order_quality",
        "ORDER_QUALITY",
        "P1",
        0.81,
        ("ORDER", "SO-2026-00126"),
        -8 * 60,
        {
            "reason": "产品F库存不足（仅剩 38）",
            "recommendation": "补料/通知客户",
            "summary": "产品F库存不足（仅剩38），大额订单交付风险",
            "order_no": "SO-2026-00126",
        },
        actor_id="agent:sales-order-quality",
    ),
    # 场景 6：VIP 客户 G（P3，策略加权后无风险）
    ResultEventSpec(
        "capability.result.order_quality",
        "ORDER_QUALITY",
        "P3",
        0.12,
        ("ORDER", "SO-2026-00128"),
        -28 * 60,
        {
            "reason": "重要客户，策略加权后无风险",
            "recommendation": "正常交付",
            "summary": "VIP 客户订单，策略加权后无风险",
            "order_no": "SO-2026-00128",
        },
        actor_id="agent:sales-order-quality",
    ),
    # 场景 7：组合风险 H（P0，部分缺料+产能紧张）
    ResultEventSpec(
        "capability.result.order_risk",
        "ORDER_RISK",
        "P0",
        0.93,
        ("ORDER", "SO-2026-00129"),
        -3 * 60,
        {
            "reason": "部分物料短缺+产能紧张",
            "recommendation": "组合方案：分批交付+产能协调+替代料",
            "summary": "部分物料短缺+产能紧张，综合高风险",
            "order_no": "SO-2026-00129",
        },
        actor_id="agent:delivery-order-risk",
    ),
    # 场景 8：数据不一致 I（P2，客户 ID ERP 双记录）
    ResultEventSpec(
        "capability.result.dq_check",
        "DATA_QUALITY",
        "P2",
        0.58,
        ("ORDER", "SO-2026-00130"),
        -44 * 60,
        {
            "reason": "客户ID在ERP中有两处不同记录",
            "recommendation": "人工确认主记录",
            "summary": "客户ID在ERP存在双记录，需人工确认",
            "order_no": "SO-2026-00130",
        },
        actor_id="agent:dq-checker",
    ),
    # 场景 9：供应商交叉 J（P1，S-030 即将停产）
    ResultEventSpec(
        "capability.result.order_risk",
        "ORDER_RISK",
        "P1",
        0.88,
        ("ORDER", "SO-2026-00131"),
        -12 * 60,
        {
            "reason": "供应商 S-030 即将停产，多源依赖",
            "recommendation": "寻找替代供应商或修改BOM",
            "summary": "供应商S-030即将停产，多源依赖需替代方案",
            "order_no": "SO-2026-00131",
        },
        actor_id="agent:delivery-order-risk",
    ),
    # 场景 10：工具调用失败（P2，PLM 同步失败；来源 edp-adapter / SERVICE）
    ResultEventSpec(
        "adapter.sync.failed",
        "ADAPTER",
        "P2",
        0.5,
        ("PROJECT", "PRJ-D"),
        -18,
        {
            "adapter": "plm",
            "reason": "UPSTREAM_UNAVAILABLE",
            "note": "场景 10：工具调用失败，已转人工跟进",
            "summary": "PLM 同步失败（工具调用故障），里程碑数据待更新",
            "order_no": "PLM",
        },
        source_system="edp-adapter",
        actor_type="SERVICE",
        actor_id="adapter:plm",
    ),
)


DEMO_CASE = DemoCaseSpec(
    question="订单 SO-2026-00123 存在缺料风险，是否加急采购物料X？",
    context={"order_amount": 120000, "material_gap": 1000},
    options=(
        CaseOptionSpec(key="EXPEDITE", label="加急采购"),
        CaseOptionSpec(key="SUBSTITUTE", label="启用替代料"),
        CaseOptionSpec(key="REJECT", label="拒绝建议"),
    ),
    risk_level="P1",
    source_event_ref=("ORDER", "SO-2026-00123"),
    evidence_source_refs=(
        ("ORDER", "SO-2026-00123"),
        ("MATERIAL", "X-100"),
        ("PURCHASE_ORDER", "PO-2026-00771"),
    ),
)


# W4 management 段（EDP-012 残余）：objectives/kpi_definitions/kpi_values 值
# 对齐 B.9 示例（on_time_delivery 91.2% / 2026-W36 风格）；period 由 seed 锚
# 派生（objectives = 锚当月 YYYY-MM、kpi_values = 锚 ISO 周 ± 偏移）。
MGMT_OBJECTIVES: tuple[ObjectiveSpec, ...] = (
    ObjectiveSpec("Q4 准时交付率", "on_time_delivery", 95.0, 91.2),
    ObjectiveSpec("库存周转率", "inventory_turnover", 8.0, 7.2),
    ObjectiveSpec("新品按时量产率", "product_readiness", 90.0, 86.5),
)

MGMT_KPI_DEFINITIONS: tuple[KpiDefinitionSpec, ...] = (
    KpiDefinitionSpec("on_time_delivery", "准时交付率", "%"),
    KpiDefinitionSpec("inventory_turnover", "库存周转率", "次/月"),
    KpiDefinitionSpec("risk_closure_rate", "风险闭环率", "%"),
)

MGMT_KPI_VALUES: tuple[KpiValueSpec, ...] = (
    KpiValueSpec("on_time_delivery", 0, 91.2),
    KpiValueSpec("on_time_delivery", -1, 90.8),
    KpiValueSpec("inventory_turnover", 0, 7.2),
    KpiValueSpec("inventory_turnover", -1, 7.0),
    KpiValueSpec("risk_closure_rate", 0, 85.0),
    KpiValueSpec("risk_closure_rate", -1, 82.5),
)


# ---- seed 放大段（W6 T5，EDP-033 压测前置）：--scale N 确定性扩展 ----
#
# scale>1 时在十类场景基线外**追加**确定性放大实体（对象/事件/证据）；
# 十类场景本体（RESULT_EVENTS/DEMO_CASE/management 段）不参与放大——
# 评估与召回统计（T12）基于基线场景。放大实体正常落库（真实数据形状），
# coverage/orphan/对账统计自然包含；T12 运营报告如需剔除，SQL 侧按
# source_id 后缀模式 ``source_id ~ '-[0-9]{6}$'`` 排除（事件/证据经
# object_id join master.business_objects 后同式过滤）——本约定以
# 6 位数字后缀为界：基线 ORDER/PO 自然键尾段已是 5 位数字
# （SO-2026-00122 / PO-2026-00771），5 位后缀会让排除模式误伤基线对象。

# 放大单元后缀零填充位数（scale_suffix）
SCALE_SUFFIX_DIGITS = 6

# 每个放大对象在快照事件外追加的活动事件数（W6 压测量级换算系数）
SCALE_ACTIVITY_PER_OBJECT = 9

# 活动事件 risk_level 稀疏分布（压测过滤场景需要少量 P0/P1，其余为空）：
# 全局序号 seq % 1000 == 0 → P0、== 500 → P1
SCALE_RISK_PERIOD = 1000
SCALE_P1_OFFSET = 500


def scale_suffix(unit: int) -> str:
    """放大单元后缀（unit ≥ 1）：``-{unit:06d}``（确定性；位数见上约定）。"""
    return f"-{unit:0{SCALE_SUFFIX_DIGITS}d}"


def scaled_activity_event_type(object_type: str) -> str:
    """放大活动事件类型：``{object_type 小写}.activity``——与十类场景的
    capability.result.* / adapter.sync.failed 本体完全区隔。"""
    return f"{object_type.lower()}.activity"


def scaled_risk_level(seq: int) -> str | None:
    """活动事件全局序号 → risk_level（确定性稀疏分布，无随机数；多数为空）。"""
    if seq % SCALE_RISK_PERIOD == 0:
        return "P0"
    if seq % SCALE_RISK_PERIOD == SCALE_P1_OFFSET:
        return "P1"
    return None
