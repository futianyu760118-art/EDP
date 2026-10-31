"""演示数据集（EDP-016）：十场景故事线快照段，时间 = anchor + 固定偏移。

纯数据包（适配器归属约束：edp_adapters 不得依赖 edp_api；回流段常量在
edp_api.modules.demo.dataset）。确定性：无随机数、无 now()——同锚两次构建
完全一致，重放走 UUIDv5 幂等（duplicated）。

- SNAPSHOT_RECORDS 按依赖顺序排列（客户/物料/产品/供应商 → 订单/采购/BOM/
  交期/库存 → 项目+里程碑）：管道逐条投影时自然键先到先解析（ORDER 的
  customer_code、PO 的 supplier/material_code、BOM 的 product/material_code
  等）；DemoErpAdapter 取 source_system="erp"、DemoPlmAdapter 取 "plm"；
- occurred_at = anchor + timedelta(minutes=offset_minutes)：负值 = 过去，
  窗口约 14 天（对齐 MSW DEMO_NOW=2026-09-28T08:30:00Z 的相对偏移）；
- payload 含 owner_domain；键与 projections.service 投影读取键一致（单测
  逐键断言）；编码/金额/日期对齐 frontend MSW fixtures（objects.ts）与设计
  文档附录 B.8 工具响应示例（SO-2026-00123 / X-100 / S-021 / C-008 /
  PO-2026-00771 等）；
- 客户补齐：订单引用的 6 个 customer_code 全部建记录（投影 customer_id 解析
  所需，未命中会置 NULL 并 warning）——C-008/C-030/C-030-B 逐字对齐 MSW，
  其余为演示补齐；MSW 中 C-008 展示来源为 mdm，后端演示数据集仅 erp/plm
  两适配器，故归 erp；
- MATERIAL P-F：成品仓物料记录，使 INVENTORY "P-F:WH-01"（delivery.inventory
  .material_id NOT NULL）可解析——场景 5「产品 F 仅剩 38」；PRODUCT P-F 仍为
  独立产品对象（BOM/研发项目引用）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

# 演示时间锚兜底（租户未设置 attributes.demo_seed.anchor 时使用；MSW DEMO_NOW）
DEMO_ANCHOR = datetime(2026, 9, 28, 8, 30, 0, tzinfo=UTC)

_HOUR = 60
_DAY = 24 * _HOUR


@dataclass(frozen=True, slots=True)
class SnapshotSpec:
    """单条快照段源记录（经 erp-demo/plm-demo 适配器 → 管道）。"""

    source_system: str  # erp / plm
    object_type: str  # CUSTOMER/MATERIAL/.../PROJECT
    source_id: str  # 自然键（INVENTORY={material_code}:{warehouse} 等）
    offset_minutes: int  # anchor + offset（负值 = 过去）
    payload: dict  # 含 owner_domain；键与投影映射/工具响应对齐


SNAPSHOT_RECORDS: tuple[SnapshotSpec, ...] = (
    # ---- 客户（master；订单引用的 customer_code 全集，先于订单） ----
    SnapshotSpec(
        "erp",
        "CUSTOMER",
        "C-008",
        -14 * _DAY,
        {"name": "某客户", "level": "VIP", "owner_domain": "master"},
    ),
    SnapshotSpec(
        "erp",
        "CUSTOMER",
        "C-012",
        -14 * _DAY,
        {"name": "远航机械", "level": "普通", "owner_domain": "master"},
    ),
    SnapshotSpec(
        "erp",
        "CUSTOMER",
        "C-015",
        -14 * _DAY,
        {"name": "金桥电子", "level": "普通", "owner_domain": "master"},
    ),
    SnapshotSpec(
        "erp",
        "CUSTOMER",
        "C-021",
        -14 * _DAY,
        {"name": "华宇重工", "level": "普通", "owner_domain": "master"},
    ),
    SnapshotSpec(
        "erp",
        "CUSTOMER",
        "C-030",
        -14 * _DAY,
        {"name": "宏达精密", "level": "普通", "owner_domain": "master"},
    ),
    SnapshotSpec(
        "erp",
        "CUSTOMER",
        "C-030-B",
        -14 * _DAY,
        {
            "name": "宏达精密",
            "level": "普通",
            "note": "ERP 双记录（场景 8）",
            "owner_domain": "master",
        },
    ),
    SnapshotSpec(
        "erp",
        "CUSTOMER",
        "C-033",
        -14 * _DAY,
        {"name": "蓝天精密", "level": "普通", "owner_domain": "master"},
    ),
    # ---- 物料（master；X-100 关键料 / Y-200；P-F 成品仓物料） ----
    SnapshotSpec(
        "erp",
        "MATERIAL",
        "X-100",
        -14 * _DAY,
        {
            "name": "物料 X-100",
            "unit": "件",
            "total_available": 3200,
            "reserved": 800,
            "owner_domain": "master",
        },
    ),
    SnapshotSpec(
        "erp",
        "MATERIAL",
        "Y-200",
        -14 * _DAY,
        {
            "name": "物料 Y-200",
            "unit": "件",
            "total_available": 5400,
            "reserved": 400,
            "owner_domain": "master",
        },
    ),
    SnapshotSpec(
        "erp",
        "MATERIAL",
        "P-F",
        -14 * _DAY,
        {"name": "产品 F", "unit": "件", "owner_domain": "master"},
    ),
    # ---- 产品（plm；P-F 量产 / P-D 新品验证中——场景 4） ----
    SnapshotSpec(
        "plm",
        "PRODUCT",
        "P-F",
        -14 * _DAY,
        {"name": "产品 F", "category": "整机", "status": "ACTIVE", "owner_domain": "master"},
    ),
    SnapshotSpec(
        "plm",
        "PRODUCT",
        "P-D",
        -14 * _DAY,
        {
            "name": "产品 D（新品）",
            "category": "整机",
            "status": "验证中",
            "owner_domain": "master",
        },
    ),
    # ---- 供应商（procurement；S-118 延迟——场景 3 / S-030 停产——场景 9） ----
    SnapshotSpec(
        "erp",
        "SUPPLIER",
        "S-021",
        -14 * _DAY,
        {"name": "供应商 S-021", "lead_time_days": 10, "owner_domain": "procurement"},
    ),
    SnapshotSpec(
        "erp",
        "SUPPLIER",
        "S-118",
        -14 * _DAY,
        {
            "name": "供应商 S-118",
            "lead_time_days": 14,
            "note": "预计交期延迟 14 天",
            "owner_domain": "procurement",
        },
    ),
    SnapshotSpec(
        "erp",
        "SUPPLIER",
        "S-030",
        -14 * _DAY,
        {
            "name": "供应商 S-030",
            "status": "即将停产",
            "effective_date": "2026-11-01",
            "owner_domain": "procurement",
        },
    ),
    # ---- 订单（sales；10 条 = 场景 1~9 输入侧 + 2 条例行，金额/日期对齐 MSW） ----
    SnapshotSpec(
        "erp",
        "ORDER",
        "SO-2026-00122",
        -9 * _DAY,
        {
            "customer_code": "C-012",
            "amount": 86000,
            "currency": "CNY",
            "status": "已确认",
            "order_date": "2026-09-14",
            "delivery_date": "2026-10-15",
            "lines": [{"product_code": "P-D", "quantity": 20, "unit_price": 4300.0}],
            "owner_domain": "sales",
        },
    ),
    SnapshotSpec(
        "erp",
        "ORDER",
        "SO-2026-00123",
        -12240,  # -8.5d
        {
            "customer_code": "C-008",
            "amount": 120000,
            "currency": "CNY",
            "status": "已确认",
            "order_date": "2026-09-15",
            "delivery_date": "2026-10-15",
            "risk_note": "物料X缺口1000",
            "lines": [
                {"product_code": "P-F", "quantity": 500, "unit_price": 240.0},
                {"material_code": "X-100", "quantity": 1000, "unit_price": 12.5},
            ],
            "owner_domain": "sales",
        },
    ),
    SnapshotSpec(
        "erp",
        "ORDER",
        "SO-2026-00124",
        -8 * _DAY,
        {
            "customer_code": "C-015",
            "amount": 64000,
            "currency": "CNY",
            "status": "已确认",
            "order_date": "2026-09-16",
            "delivery_date": "2026-10-18",
            "lines": [{"material_code": "Y-200", "quantity": 320, "unit_price": 200.0}],
            "owner_domain": "sales",
        },
    ),
    SnapshotSpec(
        "erp",
        "ORDER",
        "SO-2026-00125",
        -10800,  # -7.5d
        {
            "customer_code": "C-021",
            "amount": 38000,
            "currency": "CNY",
            "status": "已确认",
            "order_date": "2026-09-17",
            "delivery_date": "2026-10-22",
            "lines": [{"product_code": "P-D", "quantity": 10, "unit_price": 3800.0}],
            "owner_domain": "sales",
        },
    ),
    SnapshotSpec(
        "erp",
        "ORDER",
        "SO-2026-00126",
        -7 * _DAY,
        {
            "customer_code": "C-012",
            "amount": 980000,
            "currency": "CNY",
            "status": "已确认",
            "order_date": "2026-09-18",
            "delivery_date": "2026-10-10",
            "product": "P-F",
            "lines": [{"product_code": "P-F", "quantity": 4000, "unit_price": 245.0}],
            "owner_domain": "sales",
        },
    ),
    SnapshotSpec(
        "erp",
        "ORDER",
        "SO-2026-00127",
        -9360,  # -6.5d
        {
            "customer_code": "C-033",
            "amount": 51000,
            "currency": "CNY",
            "status": "已确认",
            "order_date": "2026-09-19",
            "delivery_date": "2026-10-25",
            "lines": [{"material_code": "Y-200", "quantity": 255, "unit_price": 200.0}],
            "owner_domain": "sales",
        },
    ),
    SnapshotSpec(
        "erp",
        "ORDER",
        "SO-2026-00128",
        -6 * _DAY,
        {
            "customer_code": "C-008",
            "amount": 260000,
            "currency": "CNY",
            "status": "已确认",
            "order_date": "2026-09-20",
            "delivery_date": "2026-10-08",
            "condition": "交付窗口严格",
            "lines": [{"product_code": "P-F", "quantity": 1040, "unit_price": 250.0}],
            "owner_domain": "sales",
        },
    ),
    SnapshotSpec(
        "erp",
        "ORDER",
        "SO-2026-00129",
        -7920,  # -5.5d
        {
            "customer_code": "C-015",
            "amount": 450000,
            "currency": "CNY",
            "status": "已确认",
            "order_date": "2026-09-21",
            "delivery_date": "2026-10-12",
            "risk_note": "部分物料短缺+产能紧张",
            "lines": [{"product_code": "P-F", "quantity": 1875, "unit_price": 240.0}],
            "owner_domain": "sales",
        },
    ),
    SnapshotSpec(
        "erp",
        "ORDER",
        "SO-2026-00130",
        -5 * _DAY,
        {
            "customer_code": "C-030",
            "amount": 72000,
            "currency": "CNY",
            "status": "已确认",
            "order_date": "2026-09-22",
            "delivery_date": "2026-10-20",
            "lines": [{"material_code": "Y-200", "quantity": 360, "unit_price": 200.0}],
            "owner_domain": "sales",
        },
    ),
    SnapshotSpec(
        "erp",
        "ORDER",
        "SO-2026-00131",
        -6480,  # -4.5d
        {
            "customer_code": "C-021",
            "amount": 155000,
            "currency": "CNY",
            "status": "已确认",
            "order_date": "2026-09-23",
            "delivery_date": "2026-11-05",
            "suppliers": ["S-021", "S-030"],
            "lines": [{"product_code": "P-F", "quantity": 620, "unit_price": 250.0}],
            "owner_domain": "sales",
        },
    ),
    # ---- 采购单（procurement；00771 在途 X-100 / 00785 S-118 推迟 2 周——场景 3） ----
    SnapshotSpec(
        "erp",
        "PURCHASE_ORDER",
        "PO-2026-00771",
        -9000,  # -6.25d
        {
            "supplier_code": "S-021",
            "material_code": "X-100",
            "quantity": 2000,
            "expected_date": "2026-10-20",
            "status": "在途",
            "owner_domain": "procurement",
        },
    ),
    SnapshotSpec(
        "erp",
        "PURCHASE_ORDER",
        "PO-2026-00785",
        -8100,  # -5.625d
        {
            "supplier_code": "S-118",
            "material_code": "Y-200",
            "quantity": 1500,
            "expected_date": "2026-10-12",
            "status": "在途（推迟 2 周）",
            "owner_domain": "procurement",
        },
    ),
    # ---- BOM（plm；P-F V3，工具 /bom 响应示例） ----
    SnapshotSpec(
        "plm",
        "BOM",
        "BOM-P-F-V3",
        -10 * _DAY,
        {
            "product_code": "P-F",
            "bom_version": "V3",
            "status": "ACTIVE",
            "items": [
                {"material_code": "X-100", "quantity": 2.5},
                {"material_code": "Y-200", "quantity": 1.0},
            ],
            "owner_domain": "rd",
        },
    ),
    # ---- 库存（delivery；(物料, 仓库) 粒度；WH-01 缺口来源——场景 2，P-F 仅剩 38——场景 5） ----
    SnapshotSpec(
        "erp",
        "INVENTORY",
        "X-100:WH-01",
        -5 * _HOUR,
        {
            "material_code": "X-100",
            "warehouse": "WH-01",
            "available": 0,
            "reserved": 0,
            "owner_domain": "delivery",
        },
    ),
    SnapshotSpec(
        "erp",
        "INVENTORY",
        "X-100:WH-02",
        -5 * _HOUR,
        {
            "material_code": "X-100",
            "warehouse": "WH-02",
            "available": 3200,
            "reserved": 800,
            "owner_domain": "delivery",
        },
    ),
    SnapshotSpec(
        "erp",
        "INVENTORY",
        "Y-200:WH-01",
        -10 * _HOUR,
        {
            "material_code": "Y-200",
            "warehouse": "WH-01",
            "available": 5400,
            "reserved": 400,
            "owner_domain": "delivery",
        },
    ),
    SnapshotSpec(
        "erp",
        "INVENTORY",
        "Y-200:WH-02",
        -10 * _HOUR,
        {
            "material_code": "Y-200",
            "warehouse": "WH-02",
            "available": 1200,
            "reserved": 200,
            "owner_domain": "delivery",
        },
    ),
    SnapshotSpec(
        "erp",
        "INVENTORY",
        "P-F:WH-01",
        -8 * _HOUR,
        {
            "material_code": "P-F",
            "warehouse": "WH-01",
            "available": 38,
            "reserved": 0,
            "owner_domain": "delivery",
        },
    ),
    # ---- 供应商交期（procurement；S-021→X-100=10 天——场景 2 关键输入） ----
    SnapshotSpec(
        "erp",
        "SUPPLIER_LEAD_TIME",
        "S-021:X-100",
        -5 * _HOUR,
        {
            "supplier_code": "S-021",
            "material_code": "X-100",
            "lead_time_days": 10,
            "owner_domain": "procurement",
        },
    ),
    SnapshotSpec(
        "erp",
        "SUPPLIER_LEAD_TIME",
        "S-118:X-100",
        -20 * _HOUR,
        {
            "supplier_code": "S-118",
            "material_code": "X-100",
            "lead_time_days": 14,
            "owner_domain": "procurement",
        },
    ),
    SnapshotSpec(
        "erp",
        "SUPPLIER_LEAD_TIME",
        "S-030:X-100",
        -12 * _HOUR,
        {
            "supplier_code": "S-030",
            "material_code": "X-100",
            "lead_time_days": 21,
            "owner_domain": "procurement",
        },
    ),
    SnapshotSpec(
        "erp",
        "SUPPLIER_LEAD_TIME",
        "S-021:Y-200",
        -25 * _HOUR,
        {
            "supplier_code": "S-021",
            "material_code": "Y-200",
            "lead_time_days": 7,
            "owner_domain": "procurement",
        },
    ),
    SnapshotSpec(
        "erp",
        "SUPPLIER_LEAD_TIME",
        "S-118:Y-200",
        -22 * _HOUR,
        {
            "supplier_code": "S-118",
            "material_code": "Y-200",
            "lead_time_days": 14,
            "owner_domain": "procurement",
        },
    ),
    SnapshotSpec(
        "erp",
        "SUPPLIER_LEAD_TIME",
        "S-030:Y-200",
        -18 * _HOUR,
        {
            "supplier_code": "S-030",
            "material_code": "Y-200",
            "lead_time_days": 21,
            "owner_domain": "procurement",
        },
    ),
    # ---- 研发项目 + 里程碑（plm；PRJ-D 验证中/未达产——场景 4） ----
    SnapshotSpec(
        "plm",
        "PROJECT",
        "PRJ-D",
        -32 * _HOUR,
        {
            "product_code": "P-D",
            "status": "验证中",
            "stage": "验证中",
            "readiness_level": "未达产",
            "milestones": [
                {
                    "name": "完成验证与测试",
                    "status": "IN_PROGRESS",
                    "due_date": "2026-10-05",
                }
            ],
            "owner_domain": "rd",
        },
    ),
    # ---- 产能快照（mes；场景 7 组合风险：L1 产能紧张） ----
    SnapshotSpec(
        "mes",
        "CAPACITY",
        "L1:2026-W40",
        -8 * _DAY,
        {
            "product_line": "L1",
            "period": "2026-W40",
            "capacity_qty": 1200,
            "owner_domain": "delivery",
        },
    ),
    SnapshotSpec(
        "mes",
        "CAPACITY",
        "L2:2026-W40",
        -6 * _DAY,
        {
            "product_line": "L2",
            "period": "2026-W40",
            "capacity_qty": 3600,
            "owner_domain": "delivery",
        },
    ),
    SnapshotSpec(
        "mes",
        "CAPACITY",
        "L1:2026-W41",
        -4 * _DAY,
        {
            "product_line": "L1",
            "period": "2026-W41",
            "capacity_qty": 2400,
            "owner_domain": "delivery",
        },
    ),
)
