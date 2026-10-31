import { App as AntdApp, ConfigProvider } from "antd";
import type { ReactNode } from "react";
import { useThemeStore } from "./theme-store";
import { themeConfigFor } from "./theme-config";

/** 双套令牌切换（antd 5 组件经 ConfigProvider 消费 --edp-* 镜像原值） */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const theme = useThemeStore((s) => s.theme);
  return (
    <ConfigProvider theme={themeConfigFor(theme)}>
      <AntdApp>{children}</AntdApp>
    </ConfigProvider>
  );
}
