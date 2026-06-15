import apiClient from "./client";  // 导入统一请求实例

export function listSettings() {
  return apiClient.get("/settings/");  // 获取全部设置
}

export function getSetting(key) {
  return apiClient.get(`/settings/${key}`);  // 获取单个设置
}

export function saveSetting(key, value) {
  return apiClient.put(`/settings/${key}`, { key, value });  // 保存单个设置
}
