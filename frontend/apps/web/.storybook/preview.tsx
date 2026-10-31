/* eslint-disable react-refresh/only-export-components -- storybook 全局配置文件，非 HMR 模块 */
import type { Decorator, Preview } from "@storybook/react";
import { useEffect } from "react";
import "../src/styles/tokens.css";
import "../src/styles/app.css";
import { ThemeProvider } from "../src/app/providers/ThemeProvider";
import { useThemeStore, type ThemeMode } from "../src/app/providers/theme-store";

const LIGHT_BG = "#f7f8fc"; // --edp-background
const DARK_BG = "#0b0c14"; // --edp-background (.dark)

declare module "@storybook/react" {
  interface Parameters {
    /** story 主题（默认亮色）；由 ThemeWrapper decorator 消费 */
    theme?: ThemeMode;
  }
}

/**
 * ThemeWrapper：按 story 参数 theme（默认 light）渲染 ThemeProvider。
 * Backgrounds 工具栏切到暗色时联动 documentElement 加 dark class；
 * 工具栏显式选择优先于 story 参数。
 */
const WithEdpTheme: Decorator = (Story, context) => {
  const storyTheme: ThemeMode = context.parameters.theme ?? "light";
  const toolbarValue = (context.globals as { backgrounds?: { value?: string } })
    ?.backgrounds?.value;
  const mode: ThemeMode =
    toolbarValue === DARK_BG ? "dark" : toolbarValue === LIGHT_BG ? "light" : storyTheme;
  const setTheme = useThemeStore((s) => s.setTheme);
  useEffect(() => {
    setTheme(mode);
  }, [mode, setTheme]);
  return (
    <ThemeProvider>
      <div className="edp-font-sans" style={{ minHeight: "100vh" }}>
        <Story />
      </div>
    </ThemeProvider>
  );
};

const preview: Preview = {
  decorators: [WithEdpTheme],
  parameters: {
    backgrounds: {
      default: "light",
      values: [
        { name: "light", value: LIGHT_BG },
        { name: "dark", value: DARK_BG },
      ],
    },
    controls: {
      matchers: {
        color: /(background|color)$/i,
        date: /Date$/i,
      },
    },
  },
};

export default preview;
