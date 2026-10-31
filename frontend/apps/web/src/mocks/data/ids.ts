/** 固定 UUID 表（spec §4）：跨文件共享，保证跨页引用一致。 */
export const TENANT_ID = "00000000-0000-4000-8000-000000000001";

export function mockUuid(n: number): string {
  return `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
}

// ---- 订单（SO-2026-00122~00131；AEOS §10 场景输入侧） ----
export const OBJ_ORDER_A = mockUuid(101); // 场景1 正常订单
export const OBJ_ORDER_B = mockUuid(102); // 场景2 关键料缺失（M4 主线）
export const OBJ_ORDER_C = mockUuid(103); // 场景3 供应商延迟通知
export const OBJ_ORDER_R1 = mockUuid(104); // 常规填充订单
export const OBJ_ORDER_E = mockUuid(105); // 场景5 高值低库存
export const OBJ_ORDER_R2 = mockUuid(106); // 常规填充订单
export const OBJ_ORDER_G = mockUuid(107); // 场景6 VIP 客户订单
export const OBJ_ORDER_H = mockUuid(108); // 场景7 多条件组合风险
export const OBJ_ORDER_I = mockUuid(109); // 场景8 数据不一致
export const OBJ_ORDER_J = mockUuid(110); // 场景9 供应商交叉风险

// ---- 客户 / 物料 / 产品（master） ----
export const OBJ_CUSTOMER_C008 = mockUuid(201); // VIP
export const OBJ_CUSTOMER_C030A = mockUuid(202); // 场景8 ERP 双记录 A
export const OBJ_CUSTOMER_C030B = mockUuid(203); // 场景8 ERP 双记录 B
export const OBJ_MATERIAL_X100 = mockUuid(301);
export const OBJ_MATERIAL_Y200 = mockUuid(302);
export const OBJ_PRODUCT_PF = mockUuid(311);
export const OBJ_PRODUCT_PD = mockUuid(312); // 新品（场景4）

// ---- 供应商 / 采购 / 研发 ----
export const OBJ_SUPPLIER_S021 = mockUuid(321); // 交期 10 天
export const OBJ_SUPPLIER_S118 = mockUuid(322); // 延迟 14 天（场景3）
export const OBJ_SUPPLIER_S030 = mockUuid(323); // 即将停产（场景9）
export const OBJ_PO_00771 = mockUuid(331); // X-100 在途 2000 件
export const OBJ_PO_00785 = mockUuid(332); // Y-200 推迟 2 周
export const OBJ_PROJECT_PRJD = mockUuid(341); // 产品 D 研发项目（场景4）

// ---- 关键事件（4xx 具名） ----
export const EVT_ORDER_A_RISK = mockUuid(401);
export const EVT_ORDER_B_RISK = mockUuid(402);
export const EVT_ORDER_C_RISK = mockUuid(403);
export const EVT_PRJD_READINESS = mockUuid(404);
export const EVT_ORDER_E_RISK = mockUuid(405);
export const EVT_ORDER_G_RISK = mockUuid(406);
export const EVT_ORDER_H_RISK = mockUuid(407);
export const EVT_ORDER_I_DQ = mockUuid(408);
export const EVT_ORDER_J_RISK = mockUuid(409);
export const EVT_ADAPTER_PLM_FAILED = mockUuid(410);
export const EVT_CASE_B_CREATED = mockUuid(411);

// ---- 质量事件（42x；quality.* 写通道——Bell 消息中心 fixtures） ----
export const EVT_QUALITY_REINDEX_OK = mockUuid(421);
export const EVT_QUALITY_REINDEX_MISMATCH = mockUuid(422);
export const EVT_QUALITY_RECHECK_OK = mockUuid(423);
export const EVT_QUALITY_CHECKSUM_FAIL = mockUuid(424);

// ---- 证据（6xx 具名；611+ 为常规快照生成段） ----
export const EVID_ORDER_B_SNAPSHOT = mockUuid(601);
export const EVID_ORDER_B_INVENTORY = mockUuid(602);
export const EVID_ORDER_B_PO = mockUuid(603);
export const EVID_ORDER_B_LEADTIME = mockUuid(604);
export const EVID_ORDER_C_PO_DELAY = mockUuid(605);
export const EVID_PRJD_READINESS = mockUuid(606);
export const EVID_ORDER_E_INVENTORY = mockUuid(607);
export const EVID_ORDER_I_DUAL = mockUuid(608);
export const EVID_S030_DISCONTINUE = mockUuid(609);
export const EVID_ORDER_A_SNAPSHOT = mockUuid(610);

// ---- 案例前向引用（W4 页面数据不在本 spec 范围，仅作 ref 存在，B.5 示例编号） ----
export const CASE_ORDER_B = mockUuid(901);
export const SYNC_ID = mockUuid(910);
