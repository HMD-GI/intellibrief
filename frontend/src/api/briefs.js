import apiClient from "./client";  // 导入统一请求实例

export function queryBriefs(params = {}) {
  return apiClient.get("/briefs/query", { params });  // 查询简报列表
}

export function getBriefContent(date) {
  return apiClient.get(`/briefs/${date}/content`);  // 获取简报详情 JSON
}

export function getBriefHtmlUrl(date) {
  const baseUrl = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
  return `${baseUrl}/briefs/${date}`;  // 返回 HTML 预览地址，供 iframe 使用
}

export function deleteBrief(date) {
  return apiClient.delete(`/briefs/${date}`);  // 删除指定日期简报
}
