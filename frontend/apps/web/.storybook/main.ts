import tailwindcss from "@tailwindcss/vite";
import type { StorybookConfig } from "@storybook/react-vite";

const config: StorybookConfig = {
  stories: [
    "../src/stories/**/*.stories.tsx",
    // shared 组件故事（T20 起放 packages/shared/src/components）
    "../../../packages/shared/src/**/*.stories.tsx",
  ],
  addons: ["@storybook/addon-essentials", "@storybook/addon-a11y"],
  framework: {
    name: "@storybook/react-vite",
    options: {},
  },
  async viteFinal(config) {
    // app.css 的 @import "tailwindcss" 需要.tailwindcss/vite 参与编译
    config.plugins = [...(config.plugins ?? []), tailwindcss()];
    return config;
  },
};

export default config;
