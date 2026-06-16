import { defineConfig } from "vite";  // 导入 Vite 配置工具
import vue from "@vitejs/plugin-vue";  // 导入 Vue 插件
import { fileURLToPath, URL } from "node:url";  // 导入 URL 工具，用于稳定解析前端工程根目录

const projectRoot = fileURLToPath(new URL(".", import.meta.url));  // 固定 Vite 根目录，避免 Windows 沙箱路径解析异常

export default defineConfig({
  root: projectRoot,  // 明确指定前端工程根目录
  plugins: [vue()],  // 启用 Vue 单文件组件支持
  server: {
    host: "127.0.0.1",  // 绑定本机地址，便于本地开发
    port: 5173,  // 默认前端端口
  },
});
