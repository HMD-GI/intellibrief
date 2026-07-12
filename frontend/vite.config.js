import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// 使用最小 Vite 配置，避免额外路径拼装带来的 Windows 兼容问题。
export default defineConfig({
  plugins: [vue()],
  build: {
    // 显式指定相对入口，避免 Windows 环境下 Vite/ Rollup 将 index.html 误解析为绝对输出文件名。
    rollupOptions: {
      input: "index.html",
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
  },
});
