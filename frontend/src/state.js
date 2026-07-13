import { reactive } from "vue";

// 主题列表与后端默认主题保持一致，避免前后端枚举不一致。
export const TOPICS = ["国外新闻", "AI资讯"];

export const state = reactive({
  view: "dashboard",
  userKey: "default",
  topics: [],
  briefs: [],
  bindings: {
    email: {
      sender: "",
      password: "",
      receivers: "",
      smtp_host: "",
      smtp_port: "465",
      smtp_use_ssl: true,
      include_brief: true,
      include_weather: false,
      include_typhoon: false,
    },
    feishu: {
      webhook_url: "",
      include_brief: true,
      include_weather: false,
      include_typhoon: false,
    },
  },
  schedule: {
    time: "07:00",
    enabled: false,
    topics: [],
    topic_keywords: {},
  },
  weather: {
    region: "北京",
    report: null,
    recentQueries: [],
  },
});

export function setView(view) {
  state.view = view;
}

export function toggleTopic(topic) {
  const index = state.topics.indexOf(topic);
  if (index >= 0) {
    state.topics.splice(index, 1);
  } else {
    state.topics.push(topic);
  }
}
