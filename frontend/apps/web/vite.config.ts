import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// preview 反代（W6 T10 E2E 基座）：真栈 E2E 以 VITE_API_BASE=""（同源相对
// 路径）构建 + vite preview 承载，/api 经本代理转发到真栈 api（后端无 CORS
// 中间件——web 容器形态同理由 nginx /api 反代，此处对齐）。目标沿 E2E_API_BASE
// （本地 dev compose override = 18000；CI = 8000），仅 preview 生效不影响 dev/build。
const previewApiTarget = process.env.E2E_API_BASE ?? "http://localhost:18000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  preview: {
    // linux 视觉基线生成（Playwright 官方镜像容器内浏览器经 host.docker.internal
    // 访问宿主 preview）需放行该 Host 头；CI/本地 localhost 访问不受影响。
    allowedHosts: ["host.docker.internal"],
    proxy: {
      "/api": {
        target: previewApiTarget,
        changeOrigin: true,
      },
    },
  },
});
