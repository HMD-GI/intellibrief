import apiClient from "./client";  // 导入统一请求实例

export function generateTodayBrief(payload) {
  return apiClient.post("/tasks/generate-brief", payload);  // 一键生成当日简报
}

export function saveSchedule(payload) {
  return apiClient.post("/tasks/schedule", payload);  // 保存定时生成配置
}
