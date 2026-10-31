/**
 * T17 Concern #1 决策的运行时锁定：ThemeProvider 不传 algorithm。
 *
 * 若有人重新引入 darkAlgorithm，第一条断言即红（antd 会把 #7b7cf0 改写为
 * #6c6ccf）；派生覆写（原型原值接管）与 html.dark 切换一并锁定。
 */
import { theme as antdTheme } from "antd";
import { act, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ThemeProvider } from "./ThemeProvider";
import { themeConfigFor } from "./theme-config";
import { useThemeStore } from "./theme-store";

describe("themeConfigFor：antd 生效 token 原值直出（无 algorithm 改写）", () => {
  it("暗色：Primary 恰为原型 #7b7cf0，派生覆写为原型变量原值", () => {
    const merged = antdTheme.getDesignToken({ ...themeConfigFor("dark") });
    expect(merged.colorPrimary).toBe("#7b7cf0"); // darkAlgorithm 下会变 #6c6ccf
    expect(merged.colorBgContainer).toBe("#131520");
    expect(merged.colorPrimaryBg).toBe("#1e1f3a"); // --edp-primary-50
    expect(merged.colorPrimaryBgHover).toBe("#2a2b4d"); // --edp-primary-100
    expect(merged.colorTextTertiary).toBe("#6b7280"); // --edp-ink-3
    expect(merged.colorTextQuaternary).toBe("#6b7280");
    expect(merged.controlItemBgHover).toBe("#1c1e2c"); // --edp-muted
  });

  it("亮色：Primary 恰为原型 #5b5ce2", () => {
    const merged = antdTheme.getDesignToken({ ...themeConfigFor("light") });
    expect(merged.colorPrimary).toBe("#5b5ce2");
    expect(merged.colorBgContainer).toBe("#ffffff");
  });
});

describe("ThemeProvider / theme-store：html.dark 切换", () => {
  it("setTheme('dark') 后 documentElement 带 dark class", () => {
    render(
      <ThemeProvider>
        <div>content</div>
      </ThemeProvider>,
    );
    act(() => useThemeStore.getState().setTheme("dark"));
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(document.documentElement.classList.contains("light")).toBe(false);
    act(() => useThemeStore.getState().setTheme("light"));
    expect(document.documentElement.classList.contains("light")).toBe(true);
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });
});
