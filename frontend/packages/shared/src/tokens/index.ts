/**
 * EDP 设计令牌 → Antd 5 theme.token 映射（设计文档 13.4.1）。
 *
 * 单一事实来源是 `apps/web/src/styles/tokens.css` 的 `--edp-*` 变量（亮/暗两套）；
 * 本模块是其 TypeScript 镜像，供 antd ConfigProvider 消费。
 * 一致性由 `tokens.test.ts` 锁定：改 CSS 或改此处不同步会红。
 */

/** 字体栈与 tokens.css `.edp-font-sans` 逐字一致 */
export const fontFamilySans =
  'Inter, "Noto Sans SC", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif';

/** 字体栈与 tokens.css `.edp-font-mono` 逐字一致（ID/哈希/日志用） */
export const fontFamilyMono =
  'ui-monospace, SFMono-Regular, Consolas, "Noto Sans SC Mono", monospace';

export const lightTokens = {
  colorPrimary: "#5b5ce2", // --edp-primary
  colorBgLayout: "#f7f8fc", // --edp-background
  colorBgContainer: "#ffffff", // --edp-card
  colorBgElevated: "#ffffff", // --edp-popover
  colorText: "#172033", // --edp-foreground
  colorTextSecondary: "#788298", // --edp-muted-foreground
  colorBorder: "#e8ebf2", // --edp-border
  colorBorderSecondary: "#f3f4f7", // --edp-muted
  borderRadiusSM: 4, // --edp-radius-small
  borderRadius: 8, // --edp-radius-medium
  borderRadiusLG: 12, // --edp-radius-large
  fontFamily: fontFamilySans,
  fontSize: 12, // 列表主文本 12px（13.4.1 字号阶）
  fontSizeSM: 12,
  fontSizeLG: 14,
  colorSuccess: "#12a47d", // --edp-state-success
  colorWarning: "#d97706", // --edp-state-warning
  colorError: "#df4f5f", // --edp-state-error
  colorInfo: "#3b82f6", // --edp-state-info
  /** 链接色 = 主色：antd 由 colorInfo 派生 colorLink，会把全局 <a> reset
   *  成 info 蓝 #3b82f6（侧边栏菜单链接被涂蓝的根因）；原型链接即 text-primary。 */
  colorLink: "#5b5ce2", // --edp-primary
} as const;

export const darkTokens = {
  colorPrimary: "#7b7cf0", // --edp-primary (.dark)
  colorBgLayout: "#0b0c14", // --edp-background (.dark)
  colorBgContainer: "#131520", // --edp-card (.dark)
  colorBgElevated: "#131520", // --edp-popover (.dark)
  colorText: "#e8ebf2", // --edp-foreground (.dark)
  colorTextSecondary: "#9aa1af", // --edp-muted-foreground (.dark)
  colorBorder: "#2a2d3d", // --edp-border (.dark)
  colorBorderSecondary: "#1c1e2c", // --edp-muted (.dark)
  borderRadiusSM: 4,
  borderRadius: 8,
  borderRadiusLG: 12,
  fontFamily: fontFamilySans,
  fontSize: 12,
  fontSizeSM: 12,
  fontSizeLG: 14,
  colorSuccess: "#12a47d",
  colorWarning: "#d97706",
  colorError: "#df4f5f",
  colorInfo: "#3b82f6",
  colorLink: "#7b7cf0", // --edp-primary (.dark)；同 lightTokens 注释：防 <a> reset 成 info 蓝
  /**
   * —— 派生 token 覆写（原型来源）——
   * 决策（T17 Concern #1 / T18 实跑对比落地）：ThemeProvider 不传 algorithm。
   * antd darkAlgorithm 会改写显式 colorPrimary（#7b7cf0 → #6c6ccf）；去掉
   * algorithm 后黑底系派生灰（rgba(0,0,0,x)）与亮色主色底（#f0f3ff）不可用，
   * 故由下列 tokens.css 原型变量原值接管（tokens.test.ts 锁定一致性）。
   */
  colorTextTertiary: "#6b7280", // --edp-ink-3 (.dark)；占位符/禁用等三级文本
  colorTextQuaternary: "#6b7280", // --edp-ink-3 (.dark)；原型无第四档弱化灰，与三级同值
  colorPrimaryBg: "#1e1f3a", // --edp-primary-50 (.dark)；选中底/主色淡背景
  colorPrimaryBgHover: "#2a2b4d", // --edp-primary-100 (.dark)
  controlItemBgHover: "#1c1e2c", // --edp-muted (.dark)；列表行/菜单 hover
  controlItemBgActive: "#2a2d3d", // --edp-border (.dark)（与 --edp-input 同值）
} as const;

export type ThemeTokens = typeof lightTokens;

/** 语义状态色对（前景/背景）——独立于主色，全局语义令牌（13.4.1） */
export interface SemanticStatePair {
  fg: string;
  bg: string;
}

export interface SemanticStateSet {
  success: SemanticStatePair;
  warning: SemanticStatePair;
  error: SemanticStatePair;
  info: SemanticStatePair;
}

/** 亮色状态色：与 tokens.css :root --edp-state-* / -bg 逐字一致 */
export const semanticState: SemanticStateSet = {
  success: { fg: "#12a47d", bg: "#e9fbf4" },
  warning: { fg: "#d97706", bg: "#fff7e8" },
  error: { fg: "#df4f5f", bg: "#fff0f2" },
  info: { fg: "#3b82f6", bg: "#edf5ff" },
};

/** 暗色状态色：fg 不变，bg = fg 色 + "26"（15% alpha）透明度变体 */
export const darkSemanticState: SemanticStateSet = {
  success: { fg: "#12a47d", bg: "#12a47d26" },
  warning: { fg: "#d97706", bg: "#d9770626" },
  error: { fg: "#df4f5f", bg: "#df4f5f26" },
  info: { fg: "#3b82f6", bg: "#3b82f626" },
};

/**
 * antd token → CSS 变量引用映射说明（供样式层/组件层对齐两套体系）。
 * 样式中应优先使用右列 CSS 变量；antd 组件由 ThemeProvider 注入左列 token。
 */
export const edpCssVars = {
  colorPrimary: "var(--edp-primary)",
  colorBgLayout: "var(--edp-background)",
  colorBgContainer: "var(--edp-card)",
  colorBgElevated: "var(--edp-popover)",
  colorText: "var(--edp-foreground)",
  colorTextSecondary: "var(--edp-muted-foreground)",
  colorBorder: "var(--edp-border)",
  colorBorderSecondary: "var(--edp-muted)",
  borderRadiusSM: "var(--edp-radius-small)",
  borderRadius: "var(--edp-radius-medium)",
  borderRadiusLG: "var(--edp-radius-large)",
  colorSuccess: "var(--edp-state-success)",
  colorWarning: "var(--edp-state-warning)",
  colorError: "var(--edp-state-error)",
  colorInfo: "var(--edp-state-info)",
  stateSuccessBg: "var(--edp-state-success-bg)",
  stateWarningBg: "var(--edp-state-warning-bg)",
  stateErrorBg: "var(--edp-state-error-bg)",
  stateInfoBg: "var(--edp-state-info-bg)",
  fontFamilySansClass: "edp-font-sans",
  fontFamilyMonoClass: "edp-font-mono",
} as const;

export type EdpCssVars = typeof edpCssVars;
