import { reactive } from "vue";  // 导入 Vue 响应式能力

export const TOPICS = ["国外新闻", "AI", "大模型", "行业动态", "技术教程"];  // 默认主题列表

export const state = reactive({
  view: "dashboard",
  topics: ["AI"],
  briefs: [],
  bindings: {
    email: {
      sender: "",
      password: "",
      receivers: "",
    },
    feishu: {
      webhook: "",
    },
  },
  schedule: {
    time: "07:00",
    enabled: true,
    topics: ["AI"],
  },
});

export function setView(view) {
  state.view = view;  // 切换页面视图
}

export function toggleTopic(topic) {
  const index = state.topics.indexOf(topic);
  if (index >= 0) {
    state.topics.splice(index, 1);  // 取消选择主题
  } else {
    state.topics.push(topic);  // 选择主题
  }
}
