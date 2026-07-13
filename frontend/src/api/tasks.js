import apiClient from "./client";

export function generateTodayBrief(payload) {
  return apiClient.post("/tasks/generate-brief", payload, { timeout: 0 });
}

export function saveSchedule(payload) {
  return apiClient.post("/tasks/schedule", payload);
}

export function saveSendSchedule(payload) {
  return apiClient.post("/tasks/send-schedule", payload);
}

export function sendNow(payload) {
  return apiClient.post("/tasks/send-now", payload);
}
