import axios from "axios";  // 导入 HTTP 客户端

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000",  // 独立前端通过环境变量指定后端地址
  timeout: 30000,
  headers: {
    "Content-Type": "application/json",
  },
});

apiClient.interceptors.response.use(
  (response) => {
    const payload = response.data;
    if (payload && Object.prototype.hasOwnProperty.call(payload, "code")) {
      if (payload.code !== 0) {
        return Promise.reject(new Error(payload.message || "请求失败"));  // 统一处理后端业务错误
      }
      return payload.data;
    }
    return payload;
  },
  (error) => {
    const message = error.response?.data?.detail || error.response?.data?.message || error.message || "网络请求失败";
    return Promise.reject(new Error(message));  // 统一处理网络和 HTTP 错误
  },
);

export default apiClient;
