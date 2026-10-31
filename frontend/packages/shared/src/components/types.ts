/**
 * 语义色调（设计文档 13.4.3 语义色字典 + 主色）。
 * - primary：品牌主色（时间线常规事件、KPI 图标默认）
 * - success / warning / error / info：状态语义色（--edp-state-*）
 * - muted：中性弱化（占位、无状态）
 */
export type SemanticTone = "primary" | "success" | "warning" | "error" | "info" | "muted";
