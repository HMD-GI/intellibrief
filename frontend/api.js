const API_BASE = "";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }

  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    return await response.text();
  }

  const payload = await response.json();
  if (Object.prototype.hasOwnProperty.call(payload, "code")) {
    if (payload.code !== 0) throw new Error(payload.message || "请求失败");
    return payload.data;
  }
  return payload;
}

export const api = {
  queryBriefs(params = {}) {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") query.set(key, value);
    });
    return request(`/briefs/query?${query.toString()}`);
  },
  getBrief(date) {
    return request(`/briefs/${date}/content`);
  },
  deleteBrief(date) {
    return request(`/briefs/${date}`, { method: "DELETE" });
  },
  generateToday(options) {
    return request("/tasks/generate-brief", {
      method: "POST",
      body: JSON.stringify(options),
    });
  },
  saveSchedule(value) {
    return request("/tasks/schedule", {
      method: "POST",
      body: JSON.stringify(value),
    });
  },
  getSetting(key) {
    return request(`/settings/${key}`);
  },
  saveSetting(key, value) {
    return request(`/settings/${key}`, {
      method: "PUT",
      body: JSON.stringify({ key, value }),
    });
  },
  listSettings() {
    return request("/settings/");
  },
};
