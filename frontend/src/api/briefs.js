import apiClient from "./client";  // 导入统一请求实例

export function queryBriefs(params = {}) {
  return apiClient.get("/briefs/query", { params });  // 查询简报列表
}

export function getBriefContent(id) {
  return apiClient.get(`/briefs/item/${id}/content`);  // 获取简报详情 JSON
}

export function getBriefHtmlUrl(id) {
  const baseUrl = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
  return `${baseUrl}/briefs/item/${id}/html`;  // 返回 HTML 预览地址，供 iframe 使用
}

export function deleteBrief(id) {
  return apiClient.delete(`/briefs/item/${id}`);  // 删除指定 ID 简报
}
