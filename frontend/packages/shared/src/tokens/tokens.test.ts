/**
 * 一致性锁定测试（刻意硬编码期望值）。
 *
 * 本文件从两处锁定 `packages/shared/src/tokens/index.ts`：
 * 1. 与 `apps/web/src/styles/tokens.css` 的 --edp-* 变量逐字一致
 *    （跨包读 CSS 源文件——未来改 CSS 而不同步此模块会红，提醒同步）；
 * 2. 与设计文档 13.4.1 映射表硬编码值一致（双保险，防止 CSS 与 TS 一起漂移）。
 * 这是刻意的：改任何一侧都必须显式过一遍此测试。
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  darkSemanticState,
  darkTokens,
  fontFamilyMono,
  fontFamilySans,
  lightTokens,
  semanticState,
} from "./index";

// vitest run 的 cwd = 本包目录（packages/shared）
const TOKENS_CSS_PATH = resolve(process.cwd(), "../../apps/web/src/styles/tokens.css");
const css = readFileSync(TOKENS_CSS_PATH, "utf8");

function extractBlock(selector: string): string {
  const escaped = selector.replace(".", "\\.");
  const m = css.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`));
  if (!m) throw new Error(`tokens.css: selector ${selector} not found`);
  return m[1];
}

function parseVars(block: string): Record<string, string> {
  const vars: Record<string, string> = {};
  for (const m of block.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    vars[m[1]] = m[2].trim();
  }
  return vars;
}

const rootVars = parseVars(extractBlock(":root"));
const darkVars = parseVars(extractBlock(".dark"));

// tokens.css 的 .dark 块刻意不重定义状态色与圆角（13.4.1：亮暗相同，继承 :root）
const lightOnlyMap: Record<string, string> = {
  colorSuccess: "--edp-state-success",
  colorWarning: "--edp-state-warning",
  colorError: "--edp-state-error",
  colorInfo: "--edp-state-info",
};
const radiusMap: Record<string, string> = {
  borderRadiusSM: "--edp-radius-small",
  borderRadius: "--edp-radius-medium",
  borderRadiusLG: "--edp-radius-large",
};

const lightMap: Record<string, string> = {
  colorPrimary: "--edp-primary",
  colorBgLayout: "--edp-background",
  colorBgContainer: "--edp-card",
  colorBgElevated: "--edp-popover",
  colorText: "--edp-foreground",
  colorTextSecondary: "--edp-muted-foreground",
  colorBorder: "--edp-border",
  colorBorderSecondary: "--edp-muted",
  // 链接色 = 主色（防 antd 由 colorInfo 派生 colorLink 把 <a> reset 成 info 蓝）
  colorLink: "--edp-primary",
};

describe("lightTokens ↔ tokens.css :root（改 CSS 必须同步此模块）", () => {
  for (const [token, cssVar] of Object.entries({ ...lightMap, ...lightOnlyMap })) {
    it(`${token} === :root ${cssVar}`, () => {
      expect(lightTokens[token as keyof typeof lightTokens]).toBe(rootVars[cssVar]);
    });
  }
  for (const [token, cssVar] of Object.entries(radiusMap)) {
    it(`${token} === :root ${cssVar} 数值`, () => {
      expect(String(lightTokens[token as keyof typeof lightTokens])).toBe(
        parseInt(rootVars[cssVar], 10).toString(),
      );
    });
  }
});

describe("darkTokens ↔ tokens.css .dark（改 CSS 必须同步此模块）", () => {
  for (const [token, cssVar] of Object.entries(lightMap)) {
    it(`${token} === .dark ${cssVar}`, () => {
      expect(darkTokens[token as keyof typeof darkTokens]).toBe(darkVars[cssVar]);
    });
  }
  for (const [token, cssVar] of Object.entries(lightOnlyMap)) {
    it(`${token} 亮暗相同：.dark 未重定义 ${cssVar} 且值继承 :root`, () => {
      expect(darkVars[cssVar]).toBeUndefined();
      expect(darkTokens[token as keyof typeof darkTokens]).toBe(rootVars[cssVar]);
    });
  }
  for (const [token, cssVar] of Object.entries(radiusMap)) {
    it(`${token} 亮暗相同：.dark 未重定义 ${cssVar} 数值`, () => {
      expect(darkVars[cssVar]).toBeUndefined();
      expect(String(darkTokens[token as keyof typeof darkTokens])).toBe(
        parseInt(rootVars[cssVar], 10).toString(),
      );
    });
  }
});

describe("dark 派生覆写 ↔ tokens.css .dark 原型变量（T17 Concern #1 决策落地）", () => {
  // ThemeProvider 不传 algorithm 后，antd 派生灰阶/主色底由这些原型原值接管
  const darkAliasMap: Record<string, string> = {
    colorTextTertiary: "--edp-ink-3",
    colorTextQuaternary: "--edp-ink-3",
    colorPrimaryBg: "--edp-primary-50",
    colorPrimaryBgHover: "--edp-primary-100",
    controlItemBgHover: "--edp-muted",
    controlItemBgActive: "--edp-border",
  };

  for (const [token, cssVar] of Object.entries(darkAliasMap)) {
    it(`${token} === .dark ${cssVar}`, () => {
      expect(darkTokens[token as keyof typeof darkTokens]).toBe(darkVars[cssVar]);
    });
  }

  it("决策前提锁定：暗色 Primary 恰为原型原值 #7b7cf0（darkAlgorithm 会改写为 #6c6ccf）", () => {
    expect(darkTokens.colorPrimary).toBe(darkVars["--edp-primary"]);
    expect(darkTokens.colorPrimary).toBe("#7b7cf0");
  });
});

describe("13.4.1 映射表硬编码值（双保险）", () => {
  it("亮色核心色板", () => {
    expect(lightTokens.colorPrimary).toBe("#5b5ce2");
    expect(lightTokens.colorBgLayout).toBe("#f7f8fc");
    expect(lightTokens.colorBgContainer).toBe("#ffffff");
    expect(lightTokens.colorBgElevated).toBe("#ffffff");
    expect(lightTokens.colorText).toBe("#172033");
    expect(lightTokens.colorTextSecondary).toBe("#788298");
    expect(lightTokens.colorBorder).toBe("#e8ebf2");
  });

  it("暗色核心色板", () => {
    expect(darkTokens.colorPrimary).toBe("#7b7cf0");
    expect(darkTokens.colorBgLayout).toBe("#0b0c14");
    expect(darkTokens.colorBgContainer).toBe("#131520");
    expect(darkTokens.colorBgElevated).toBe("#131520");
    expect(darkTokens.colorText).toBe("#e8ebf2");
    expect(darkTokens.colorTextSecondary).toBe("#9aa1af");
    expect(darkTokens.colorBorder).toBe("#2a2d3d");
  });

  it("圆角阶 4/8/12 亮暗一致", () => {
    expect(lightTokens.borderRadiusSM).toBe(4);
    expect(lightTokens.borderRadius).toBe(8);
    expect(lightTokens.borderRadiusLG).toBe(12);
    expect(darkTokens.borderRadiusSM).toBe(4);
    expect(darkTokens.borderRadius).toBe(8);
    expect(darkTokens.borderRadiusLG).toBe(12);
  });

  it("字号阶：正文 12 / SM 12 / LG 14", () => {
    expect(lightTokens.fontSize).toBe(12);
    expect(lightTokens.fontSizeSM).toBe(12);
    expect(lightTokens.fontSizeLG).toBe(14);
    expect(darkTokens.fontSize).toBe(12);
    expect(darkTokens.fontSizeSM).toBe(12);
    expect(darkTokens.fontSizeLG).toBe(14);
  });
});

describe("字体栈 ↔ tokens.css 基础类", () => {
  it("fontFamilySans === .edp-font-sans font-family", () => {
    const m = css.match(/\.edp-font-sans\s*\{[^}]*font-family:\s*([^;]+);/);
    expect(m).not.toBeNull();
    expect(fontFamilySans).toBe(m![1].trim());
    expect(lightTokens.fontFamily).toBe(fontFamilySans);
    expect(darkTokens.fontFamily).toBe(fontFamilySans);
  });

  it("fontFamilyMono === .edp-font-mono font-family", () => {
    const m = css.match(/\.edp-font-mono\s*\{[^}]*font-family:\s*([^;]+);/);
    expect(m).not.toBeNull();
    expect(fontFamilyMono).toBe(m![1].trim());
  });
});

describe("语义状态色 ↔ tokens.css --edp-state-*", () => {
  const stateMap = {
    success: "--edp-state-success",
    warning: "--edp-state-warning",
    error: "--edp-state-error",
    info: "--edp-state-info",
  } as const;

  it("亮色 fg/bg 与 :root 逐字一致", () => {
    for (const [key, cssVar] of Object.entries(stateMap)) {
      expect(semanticState[key as keyof typeof semanticState].fg).toBe(rootVars[cssVar]);
      expect(semanticState[key as keyof typeof semanticState].bg).toBe(
        rootVars[`${cssVar}-bg`],
      );
    }
  });

  it("暗色规则：fg 不变，bg = fg + '26' alpha", () => {
    for (const [key] of Object.entries(stateMap)) {
      const k = key as keyof typeof darkSemanticState;
      expect(darkSemanticState[k].fg).toBe(semanticState[k].fg);
      expect(darkSemanticState[k].bg).toBe(`${semanticState[k].fg}26`);
    }
  });

  it("状态色与 antd token 状态色同源", () => {
    expect(lightTokens.colorSuccess).toBe(semanticState.success.fg);
    expect(lightTokens.colorWarning).toBe(semanticState.warning.fg);
    expect(lightTokens.colorError).toBe(semanticState.error.fg);
    expect(lightTokens.colorInfo).toBe(semanticState.info.fg);
  });
});
