import { defineConfig } from "vite";  // 导入 Vite 配置工具
import vue from "@vitejs/plugin-vue";  // 导入 Vue 插件

export default defineConfig({
  plugins: [vue()],  // 启用 Vue 单文件组件支持
  server: {
    host: "127.0.0.1",  // 绑定本机地址，便于本地开发
    port: 5173,  // 默认前端端口
  },
});
