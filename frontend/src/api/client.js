import axios from "axios";

const USER_KEY_STORAGE = "intellibrief_user_key";

function createRandomUserKey() {
  // 每台设备首次进入页面时生成随机用户标识，用于没有登录系统时的数据隔离。
  if (window.crypto?.randomUUID) {
    return `user_${window.crypto.randomUUID()}`;
  }
  return `user_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 12)}`;
}

export function getCurrentUserKey() {
  // 从浏览器本地存储读取用户标识；不存在时创建并保存，保证同一设备后续访问保持一致。
  let userKey = (window.localStorage.getItem(USER_KEY_STORAGE) || "").trim();
  if (!userKey) {
    userKey = createRandomUserKey();
    window.localStorage.setItem(USER_KEY_STORAGE, userKey);
  }
  return userKey;
}

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000",
  timeout: 30000,
  headers: {
    "Content-Type": "application/json",
  },
});

apiClient.interceptors.request.use((config) => {
  // 每次请求统一附加当前用户标识，后端用它隔离发送设置、天气偏好等个人数据。
  config.headers["X-User-Key"] = getCurrentUserKey();
  return config;
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
