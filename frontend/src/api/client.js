import axios from "axios";

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000",
  timeout: 30000,
  headers: {
    "Content-Type": "application/json",
  },
});

apiClient.interceptors.response.use(
  (response) => {
    const payload = response.data;
    // 统一解析后端返回的 success/code/message/data 结构。
    if (payload && Object.prototype.hasOwnProperty.call(payload, "code")) {
      const isSuccess = payload.success !== false && payload.code === 0;
      if (!isSuccess) {
        return Promise.reject(new Error(payload.message || "请求失败"));
      }
      return payload.data;
    }
    return payload;
  },
  (error) => {
    const payload = error.response?.data;
    const message =
      payload?.message ||
      payload?.detail ||
      error.message ||
      "网络请求失败";
    return Promise.reject(new Error(message));
  },
);

export default apiClient;
