<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">IB</div>
        <div>
          <div class="brand-title">IntelliBrief</div>
          <div class="brand-subtitle">简报与天气分离工作台</div>
        </div>
      </div>
      <nav class="nav">
        <button
          type="button"
          class="nav-item"
          :class="{ active: state.view === 'dashboard' }"
          @click="setView('dashboard')"
        >
          工作台
        </button>
        <button
          type="button"
          class="nav-item"
          :class="{ active: state.view === 'weather' }"
          @click="setView('weather')"
        >
          天气情况
        </button>
        <button
          type="button"
          class="nav-item"
          :class="{ active: state.view === 'briefs' }"
          @click="setView('briefs')"
        >
          简报列表
        </button>
        <button
          type="button"
          class="nav-item"
          :class="{ active: state.view === 'bindings' }"
          @click="setView('bindings')"
        >
          发送设置
        </button>
      </nav>
    </aside>

    <main class="main">
      <header class="topbar">
        <div>
          <h1>{{ pageTitle }}</h1>
          <p>{{ pageSubtitle }}</p>
        </div>
        <button type="button" class="icon-btn" title="刷新" @click="reloadAll">刷新</button>
      </header>

      <ToastBar :message="toastMessage" />

      <section v-if="state.view === 'dashboard'">
        <div class="grid two">
          <section class="panel">
            <div class="panel-head">
              <h2>主题</h2>
              <span>必须选择，支持多选</span>
            </div>
            <TopicChips :topics="TOPICS" :model-value="state.topics" @toggle="handleToggleTopic" />
            <label class="keyword-field">
              关键词
              <input
                v-model="keywordInput"
                type="text"
                placeholder="可选，如“美国、欧洲”等"
              >
            </label>
          </section>

          <section class="panel">
            <div class="panel-head">
              <h2>生成</h2>
              <span>生成当日简报，不包含天气正文</span>
            </div>
            <button
              type="button"
              class="primary-btn"
              :disabled="isGenerating"
              @click="handleGenerate"
            >
              {{ isGenerating ? "正在生成中" : "一键生成当日简报" }}
            </button>
            <div class="schedule-row">
              <input v-model="scheduleForm.time" type="time">
              <button type="button" class="secondary-btn" @click="handleToggleSchedule">
                {{ scheduleForm.enabled ? "已开始定时生成简报" : "开始定时生成简报" }}
              </button>
            </div>
            <div v-if="scheduleForm.enabled" class="schedule-topic">
              <div>定时主题：{{ scheduleForm.topics.join("、") || "-" }}</div>
              <div>定时关键词：{{ scheduleForm.keywords.join("、") || "未设置" }}</div>
            </div>
          </section>
        </div>

        <section class="panel">
          <div class="panel-head">
            <h2>最近简报</h2>
            <button type="button" class="link-btn" @click="setView('briefs')">查看全部</button>
          </div>
          <BriefTable :items="recentBriefs" @view="openBrief" @remove="handleDeleteBrief" />
        </section>
      </section>

      <WeatherPanel
        v-else-if="state.view === 'weather'"
        :reload-key="weatherReloadKey"
        @toast="showToast"
      />

      <section v-else-if="state.view === 'briefs'">
        <section class="panel">
          <div class="filter-bar">
            <label>
              开始时间
              <input v-model="filters.start_date" type="date">
            </label>
            <label>
              结束时间
              <input v-model="filters.end_date" type="date">
            </label>
            <label>
              类型
              <select v-model="filters.brief_type">
                <option value="all">全部</option>
                <option value="daily">每日简报</option>
              </select>
            </label>
            <label>
              主题
              <select v-model="filters.topic">
                <option value="all">全部</option>
                <option v-for="topic in TOPICS" :key="topic" :value="topic">{{ topic }}</option>
              </select>
            </label>
            <button type="button" class="secondary-btn" @click="loadBriefs">查询</button>
          </div>
          <BriefTable :items="state.briefs" @view="openBrief" @remove="handleDeleteBrief" />
        </section>
      </section>

      <section v-else>
        <div class="grid two">
          <section class="panel">
            <div class="panel-head">
              <h2>邮箱</h2>
              <span>同一封邮件中分为“简报”和“天气”两个部分</span>
            </div>
            <label>
              发件邮箱
              <input v-model="bindingForm.email.sender" placeholder="name@example.com">
            </label>
            <label>
              授权码
              <input
                v-model="bindingForm.email.password"
                type="password"
                placeholder="SMTP 授权码"
              >
            </label>
            <label>
              收件人
              <input v-model="bindingForm.email.receivers" placeholder="多个邮箱用逗号分隔">
            </label>
            <label>
              SMTP 服务器
              <input v-model="bindingForm.email.smtp_host" placeholder="smtp.163.com">
            </label>
            <label>
              SMTP 端口
              <input v-model="bindingForm.email.smtp_port" type="number" placeholder="465">
            </label>
            <label class="check-row">
              <input v-model="bindingForm.email.smtp_use_ssl" type="checkbox">
              使用 SSL
            </label>
            <div class="delivery-options">
              <div class="delivery-title">邮箱发送内容</div>
              <label class="check-row">
                <input v-model="bindingForm.email.include_brief" type="checkbox">
                简报内容
              </label>
              <label class="check-row">
                <input v-model="bindingForm.email.include_weather" type="checkbox">
                天气情况
              </label>
              <label class="check-row">
                <input v-model="bindingForm.email.include_typhoon" type="checkbox">
                台风情况
              </label>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head">
              <h2>飞书机器人</h2>
              <span>通过 Webhook 发送消息卡片，天气、台风、简报分区展示</span>
            </div>
            <label>
              Webhook 地址
              <input
                v-model="bindingForm.feishu.webhook_url"
                placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..."
              >
            </label>
            <div class="delivery-options">
              <div class="delivery-title">飞书发送内容</div>
              <label class="check-row">
                <input v-model="bindingForm.feishu.include_brief" type="checkbox">
                简报区块
              </label>
              <label class="check-row">
                <input v-model="bindingForm.feishu.include_weather" type="checkbox">
                天气区块
              </label>
              <label class="check-row">
                <input v-model="bindingForm.feishu.include_typhoon" type="checkbox">
                台风区块
              </label>
            </div>
          </section>
        </div>

        <section class="panel actions-panel">
          <button type="button" class="primary-btn" @click="handleSaveBindings">保存发送设置</button>
          <button type="button" class="secondary-btn" @click="handleClearBindings">清空发送设置</button>
        </section>
      </section>
    </main>
  </div>

  <div v-if="briefModalVisible" class="modal" @click.self="closeModal">
    <div class="modal-card">
      <header>
        <h2>{{ modalTitle }}</h2>
        <button type="button" class="icon-btn" title="关闭" @click="closeModal">关闭</button>
      </header>
      <iframe :src="briefFrameUrl" title="简报内容"></iframe>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";

import BriefTable from "./modules/brief/components/BriefTable.vue";
import ToastBar from "./modules/common/components/ToastBar.vue";
import TopicChips from "./modules/common/components/TopicChips.vue";
import WeatherPanel from "./modules/weather/components/WeatherPanel.vue";
import { deleteBrief, getBriefHtmlUrl, queryBriefs } from "./api/briefs";
import { getSetting, saveSetting } from "./api/settings";
import { generateTodayBrief, saveSchedule } from "./api/tasks";
import { setView, state, toggleTopic, TOPICS } from "./state";

const toastMessage = ref("");
const isGenerating = ref(false);
const briefModalVisible = ref(false);
const modalTitle = ref("简报详情");
const briefFrameUrl = ref("");
const keywordInput = ref("");
const weatherReloadKey = ref(0);

const filters = reactive({
  start_date: "",
  end_date: "",
  brief_type: "all",
  topic: "all",
});

const scheduleForm = reactive({
  time: "07:00",
  enabled: false,
  topics: [],
  keywords: [],
});

const bindingForm = reactive({
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
});

const pageTitle = computed(() => {
  if (state.view === "weather") return "天气情况";
  if (state.view === "briefs") return "简报列表";
  if (state.view === "bindings") return "发送设置";
  return "工作台";
});

const pageSubtitle = computed(() => {
  if (state.view === "weather") {
    return "天气模块独立展示地区天气、预警和台风情况，并支持最近查询缓存和地区联想。";
  }
  if (state.view === "briefs") {
    return "按日期范围和主题查询已生成简报。";
  }
  if (state.view === "bindings") {
    return "天气、台风与简报独立发送：飞书通过机器人卡片发送，邮箱按两个区块发送。";
  }
  return "选择主题和关键词，生成或定时生成当日简报。";
});

const recentBriefs = computed(() => state.briefs.slice(0, 5));

// 将前端输入框中的关键词按“、”切分为数组，并在提交前去掉空值。
function parseKeywords(inputText) {
  return (inputText || "")
    .split("、")
    .map((item) => item.trim())
    .filter(Boolean);
}

function showToast(message) {
  toastMessage.value = message;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    toastMessage.value = "";
  }, 2500);
}

function handleToggleTopic(topic) {
  toggleTopic(topic);
}

function copyBindingsToForm(data) {
  const email = data?.email || {};
  const feishu = data?.feishu || {};

  Object.assign(bindingForm.email, {
    sender: email.sender || "",
    password: email.password || "",
    receivers: email.receivers || "",
    smtp_host: email.smtp_host || "",
    smtp_port: email.smtp_port || "465",
    smtp_use_ssl: email.smtp_use_ssl ?? true,
    include_brief: email.include_brief ?? true,
    include_weather: email.include_weather ?? false,
    include_typhoon: email.include_typhoon ?? false,
  });

  Object.assign(bindingForm.feishu, {
    webhook_url: feishu.webhook_url || "",
    include_brief: feishu.include_brief ?? true,
    include_weather: feishu.include_weather ?? false,
    include_typhoon: feishu.include_typhoon ?? false,
  });
}

async function loadBindings() {
  try {
    const data = await getSetting("bindings");
    const value = data?.value || {};
    state.bindings = value;
    copyBindingsToForm(value);
  } catch (error) {
    showToast(`加载发送设置失败：${error.message}`);
  }
}

async function loadSchedule() {
  try {
    const data = await getSetting("schedule");
    const value = data?.value || {};
    scheduleForm.time = value.time || "07:00";
    scheduleForm.enabled = !!value.enabled;
    scheduleForm.topics = value.topics || [];
    scheduleForm.keywords = value.keywords || [];
    state.schedule = {
      time: scheduleForm.time,
      enabled: scheduleForm.enabled,
      topics: [...scheduleForm.topics],
      keywords: [...scheduleForm.keywords],
    };
    if (!keywordInput.value && scheduleForm.keywords.length) {
      keywordInput.value = scheduleForm.keywords.join("、");
    }
  } catch (error) {
    showToast(`加载定时设置失败：${error.message}`);
  }
}

async function loadBriefs() {
  try {
    const data = await queryBriefs({
      start_date: filters.start_date || undefined,
      end_date: filters.end_date || undefined,
      brief_type: filters.brief_type,
      topic: filters.topic,
      limit: 50,
    });
    state.briefs = data?.items || [];
  } catch (error) {
    showToast(`加载简报列表失败：${error.message}`);
  }
}

async function handleGenerate() {
  if (!state.topics.length) {
    showToast("一定要选择一个主题");
    return;
  }
  if (isGenerating.value) {
    return;
  }

  const keywords = parseKeywords(keywordInput.value);
  const payload = {
    topics: [...state.topics],
    send_email: Boolean(bindingForm.email.sender.trim()),
    send_feishu: Boolean(bindingForm.feishu.webhook_url.trim()),
  };
  if (keywords.length) {
    payload.keywords = keywords;
  }

  isGenerating.value = true;
  showToast("正在生成中，请等待后端完整流水线结束");
  try {
    await generateTodayBrief(payload);
    await loadBriefs();
    showToast("当日简报生成完成");
  } catch (error) {
    showToast(`生成失败：${error.message}`);
  } finally {
    isGenerating.value = false;
  }
}

async function handleToggleSchedule() {
  if (!scheduleForm.enabled && !state.topics.length) {
    showToast("一定要选择一个主题");
    return;
  }

  const nextEnabled = !scheduleForm.enabled;
  const topics = nextEnabled ? [...state.topics] : scheduleForm.topics;
  const keywords = parseKeywords(keywordInput.value);
  const payload = {
    time: scheduleForm.time,
    topics,
    enabled: nextEnabled,
  };
  if (keywords.length) {
    payload.keywords = keywords;
  }

  try {
    const value = await saveSchedule(payload);
    scheduleForm.enabled = !!value.enabled;
    scheduleForm.topics = value.topics || [];
    scheduleForm.keywords = value.keywords || [];
    state.schedule = {
      time: value.time || scheduleForm.time,
      enabled: scheduleForm.enabled,
      topics: [...scheduleForm.topics],
      keywords: [...scheduleForm.keywords],
    };
    showToast(scheduleForm.enabled ? "已开始定时生成简报" : "已取消定时生成简报");
  } catch (error) {
    showToast(`保存定时设置失败：${error.message}`);
  }
}

async function handleSaveBindings() {
  const value = {
    email: { ...bindingForm.email },
    feishu: { ...bindingForm.feishu },
  };

  try {
    await saveSetting("bindings", value);
    state.bindings = value;
    showToast("发送设置已保存");
  } catch (error) {
    showToast(`保存发送设置失败：${error.message}`);
  }
}

async function handleClearBindings() {
  Object.assign(bindingForm.email, {
    sender: "",
    password: "",
    receivers: "",
    smtp_host: "",
    smtp_port: "465",
    smtp_use_ssl: true,
    include_brief: true,
    include_weather: false,
    include_typhoon: false,
  });

  Object.assign(bindingForm.feishu, {
    webhook_url: "",
    include_brief: true,
    include_weather: false,
    include_typhoon: false,
  });

  await handleSaveBindings();
}

async function handleDeleteBrief(item) {
  if (!window.confirm(`确认删除 ${item.date} ${item.topic || "综合"} 的简报？`)) {
    return;
  }
  try {
    await deleteBrief(item.id);
    showToast("简报已删除");
    await loadBriefs();
  } catch (error) {
    showToast(`删除失败：${error.message}`);
  }
}

function openBrief(item) {
  modalTitle.value = `${item.date} ${item.topic || "综合"} 简报`;
  briefFrameUrl.value = getBriefHtmlUrl(item.id);
  briefModalVisible.value = true;
}

function closeModal() {
  briefModalVisible.value = false;
}

async function reloadAll() {
  await Promise.all([loadBindings(), loadSchedule(), loadBriefs()]);
  weatherReloadKey.value += 1;
  showToast("数据已刷新");
}

onMounted(async () => {
  await reloadAll();
});
</script>
