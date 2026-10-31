import { darkTokens, lightTokens } from "@edp/shared";
import type { ThemeMode } from "./theme-store";

/**
 * 主题配置工厂（单一事实来源，ThemeProvider.test.tsx 锁定）。
 *
 * 决策（T17 Concern #1，T18 实跑对比后落地）：不传 algorithm，仅 token 双套切换。
 * - antd darkAlgorithm 会改写显式 colorPrimary：#7b7cf0 → #6c6ccf，违背
 *   “token 原值即原型基线”（原型 .dark --edp-primary = #7b7cf0）；
 * - 去掉 algorithm 后的派生灰阶/主色底由 darkTokens 追加的原型来源覆写接管
 *   （ink-3 / primary-50 / primary-100 / muted / border，见 @edp/shared tokens）。
 */
export function themeConfigFor(mode: ThemeMode) {
  return {
    token: { ...(mode === "dark" ? darkTokens : lightTokens) },
  };
}
