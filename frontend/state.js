export const TOPICS = ["国外新闻", "AI", "大模型", "行业动态", "技术教程"];

export const state = {
  view: "dashboard",
  topics: ["AI"],
  briefs: [],
  bindings: {
    email: { sender: "", password: "", receivers: "" },
    feishu: { webhook: "" },
  },
  schedule: {
    time: "07:00",
    topics: ["AI"],
    enabled: true,
  },
};

export function setView(view) {
  state.view = view;
}

export function toggleTopic(topic) {
  if (state.topics.includes(topic)) {
    state.topics = state.topics.filter((item) => item !== topic);
  } else {
    state.topics = [...state.topics, topic];
  }
}
