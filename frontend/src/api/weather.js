import apiClient from "./client";

// 查询指定地区的天气、预警和台风信息。
export async function getWeatherReport(region) {
  const data = await apiClient.get("/weather/report", {
    params: { region },
  });
  return data?.report || null;
}

// 获取地区联想候选项。
export async function getWeatherSuggestions(keyword) {
  const data = await apiClient.get("/weather/suggest", {
    params: { keyword },
  });
  return Array.isArray(data?.items) ? data.items : [];
}

// 获取最近查询地区。
export async function getRecentWeatherQueries() {
  const data = await apiClient.get("/weather/recent");
  return Array.isArray(data?.items) ? data.items : [];
}
