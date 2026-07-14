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
        <div class="topbar-actions">
          <label class="user-key-field">
            <span>用户标识</span>
            <input
              v-model="currentUserKey"
              type="text"
              placeholder="请输入当前登录用户标识"
              @keyup.enter="handleApplyUserKey"
            >
          </label>
          <button type="button" class="secondary-btn" @click="handleApplyUserKey">切换用户</button>
          <button type="button" class="icon-btn" title="刷新" @click="reloadAll">刷新</button>
        </div>
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
            <div class="keyword-field">
              <div class="delivery-title">主题关键词</div>
              <div v-if="!state.topics.length" class="schedule-topic">
                <div>请先选择主题，再填写对应关键词。</div>
              </div>
              <div v-else class="grid">
                <label v-for="topic in state.topics" :key="topic">
                  {{ topic }}
                  <input
                    v-model="topicKeywordInputs[topic]"
                    type="text"
                    placeholder="可选，如“美国、欧洲”等"
                  >
                </label>
              </div>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head">
              <h2>生成</h2>
              <span>生成当日简报，天气模块独立显示</span>
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
              <button type="button" class="secondary-btn" @click="handleAddScheduleItem">
                添加当前选择为定时项
              </button>
              <button type="button" class="secondary-btn" @click="handleSaveSchedule(true)">
                {{ scheduleForm.enabled ? "保存定时生成配置" : "保存并开启定时生成简报" }}
              </button>
              <button
                v-if="scheduleForm.enabled"
                type="button"
                class="secondary-btn"
                @click="handleSaveSchedule(false)"
              >
                停止定时生成简报
              </button>
            </div>
            <div class="schedule-topic">
              <div v-if="!scheduleForm.items.length">暂无定时生成项，请先选择主题后添加。</div>
              <div v-else class="schedule-item-list">
                <div
                  v-for="item in scheduleForm.items"
                  :key="item.id"
                  class="schedule-item"
                >
                  <div class="schedule-row">
                    <input v-model="item.time" type="time">
                    <label class="check-row">
                      <input v-model="item.enabled" type="checkbox">
                      启用该时间段
                    </label>
                    <button type="button" class="secondary-btn" @click="handleReplaceScheduleItem(item)">
                      用当前选择覆盖
                    </button>
                    <button type="button" class="link-btn" @click="handleRemoveScheduleItem(item.id)">
                      删除
                    </button>
                  </div>
                  <div>主题：{{ item.topics.join("、") || "-" }}</div>
                  <div>关键词：{{ formatScheduleItemKeywords(item) }}</div>
                </div>
              </div>
              <div v-if="scheduleForm.enabled">当前状态：已开启多时间段定时生成</div>
              <div v-else>当前状态：未开启定时生成</div>
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
              <span>同一封邮件中拆分为简报和天气两个区块</span>
            </div>
            <label>
              发件邮箱
              <input v-model="bindingForm.email.sender" placeholder="name@example.com">
            </label>
            <label>
              授权码
              <input v-model="bindingForm.email.password" type="password" placeholder="SMTP 授权码">
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
            <div class="actions-panel binding-actions-left">
              <button
                type="button"
                class="secondary-btn"
                :disabled="sendNowLoading.email"
                @click="handleSendNow('email')"
              >
                {{ sendNowLoading.email ? "发送中" : "一键发送邮箱" }}
              </button>
              <input v-model="sendScheduleForm.email.time" type="time">
              <div class="scope-options">
                <label
                  v-for="scope in BRIEF_DATE_SCOPE_OPTIONS"
                  :key="`email-${scope.value}`"
                  class="check-row"
                >
                  <input
                    :checked="sendScheduleForm.email.brief_date_scopes.includes(scope.value)"
                    type="checkbox"
                    @change="toggleBriefDateScope('email', scope.value)"
                  >
                  {{ scope.label }}
                </label>
              </div>
              <button type="button" class="secondary-btn" @click="handleSaveSendSchedule('email', true)">
                {{ sendScheduleForm.email.enabled ? "保存定时发送邮箱" : "开启定时发送邮箱" }}
              </button>
              <button
                v-if="sendScheduleForm.email.enabled"
                type="button"
                class="secondary-btn"
                @click="handleSaveSendSchedule('email', false)"
              >
                停止定时发送邮箱
              </button>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head">
              <h2>飞书机器人</h2>
              <span>通过 Webhook 发送消息卡片，简报、天气、台风分区展示</span>
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
            <div class="actions-panel binding-actions-left">
              <button
                type="button"
                class="secondary-btn"
                :disabled="sendNowLoading.feishu"
                @click="handleSendNow('feishu')"
              >
                {{ sendNowLoading.feishu ? "发送中" : "一键发送飞书" }}
              </button>
              <input v-model="sendScheduleForm.feishu.time" type="time">
              <div class="scope-options">
                <label
                  v-for="scope in BRIEF_DATE_SCOPE_OPTIONS"
                  :key="`feishu-${scope.value}`"
                  class="check-row"
                >
                  <input
                    :checked="sendScheduleForm.feishu.brief_date_scopes.includes(scope.value)"
                    type="checkbox"
                    @change="toggleBriefDateScope('feishu', scope.value)"
                  >
                  {{ scope.label }}
                </label>
              </div>
              <button type="button" class="secondary-btn" @click="handleSaveSendSchedule('feishu', true)">
                {{ sendScheduleForm.feishu.enabled ? "保存定时发送飞书" : "开启定时发送飞书" }}
              </button>
              <button
                v-if="sendScheduleForm.feishu.enabled"
                type="button"
                class="secondary-btn"
                @click="handleSaveSendSchedule('feishu', false)"
              >
                停止定时发送飞书
              </button>
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

import { getCurrentUserKey } from "./api/client";
import { deleteBrief, getBriefHtmlUrl, queryBriefs } from "./api/briefs";
import { getSetting, saveSetting } from "./api/settings";
import { generateTodayBrief, saveSchedule, saveSendSchedule, sendNow } from "./api/tasks";
import BriefTable from "./modules/brief/components/BriefTable.vue";
import ToastBar from "./modules/common/components/ToastBar.vue";
import TopicChips from "./modules/common/components/TopicChips.vue";
import WeatherPanel from "./modules/weather/components/WeatherPanel.vue";
import { setView, state, toggleTopic, TOPICS } from "./state";

const USER_KEY_STORAGE = "intellibrief_user_key";
const BRIEF_DATE_SCOPE_OPTIONS = [
  { label: "今天", value: "today" },
  { label: "昨天", value: "yesterday" },
];

const toastMessage = ref("");
const isGenerating = ref(false);
const briefModalVisible = ref(false);
const modalTitle = ref("简报详情");
const briefFrameUrl = ref("");
const weatherReloadKey = ref(0);
const currentUserKey = ref(state.userKey || "default");
const topicKeywordInputs = reactive({});
const sendNowLoading = reactive({
  email: false,
  feishu: false,
});

const filters = reactive({
  start_date: "",
  end_date: "",
  brief_type: "all",
  topic: "all",
});

const scheduleForm = reactive({
  enabled: false,
  items: [],
});

const sendScheduleForm = reactive({
  email: {
    time: "07:30",
    enabled: false,
    brief_date_scopes: ["today"],
  },
  feishu: {
    time: "07:30",
    enabled: false,
    brief_date_scopes: ["today"],
  },
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
    return "发送设置按当前用户隔离保存；切换用户后会显示该用户自己的邮箱和飞书配置。";
  }
  return "选择主题及对应关键词，生成或定时生成当日简报。";
});

const recentBriefs = computed(() => state.briefs.slice(0, 5));

function parseKeywords(inputText) {
  // 将输入框中的关键词按中文顿号拆分成数组，并去掉空值。
  return (inputText || "")
    .split("、")
    .map((item) => item.trim())
    .filter(Boolean);
}

function buildTopicKeywordMap(topics) {
  // 将当前已选主题映射到各自的关键词数组，用于后端按主题独立处理。
  const result = {};
  (topics || []).forEach((topic) => {
    const keywords = parseKeywords(topicKeywordInputs[topic]);
    if (keywords.length) {
      result[topic] = keywords;
    }
  });
  return result;
}

function createScheduleItemFromCurrentSelection() {
  // 以“当前工作台勾选的主题和关键词”生成一条新的定时生成项。
  const now = Date.now().toString(36);
  const lastItem = scheduleForm.items[scheduleForm.items.length - 1];
  return {
    id: `schedule_${now}_${Math.random().toString(36).slice(2, 8)}`,
    time: lastItem?.time || "07:00",
    topics: [...state.topics],
    keywords: [],
    topic_keywords: buildTopicKeywordMap(state.topics),
    enabled: true,
  };
}

function normalizeScheduleItems(items) {
  // 统一规整后端返回的定时项结构，兼容旧版单 time 配置和新版 items 数组配置。
  if (Array.isArray(items) && items.length) {
    return items.map((item, index) => ({
      id: item.id || `schedule_${index + 1}`,
      time: item.time || "07:00",
      topics: item.topics || [],
      keywords: item.keywords || [],
      topic_keywords: item.topic_keywords || {},
      enabled: item.enabled !== false,
    }));
  }
  return [];
}

function assignScheduleValue(value) {
  // 将后端的定时生成配置完整回填到前端状态。
  const items = normalizeScheduleItems(value?.items);
  scheduleForm.enabled = !!value?.enabled;
  scheduleForm.items.splice(0, scheduleForm.items.length, ...items);
  state.schedule = {
    enabled: scheduleForm.enabled,
    items: items.map((item) => ({
      id: item.id,
      time: item.time,
      topics: [...item.topics],
      keywords: [...(item.keywords || [])],
      topic_keywords: { ...(item.topic_keywords || {}) },
      enabled: item.enabled !== false,
    })),
  };
}

function formatScheduleItemKeywords(item) {
  // 将定时项中的主题关键词转成便于展示的文本。
  const entries = Object.entries(item?.topic_keywords || {});
  if (!entries.length) {
    return "未设置";
  }
  return entries
    .map(([topic, keywords]) => `${topic}：${(keywords || []).join("、") || "未设置"}`)
    .join("；");
}

function toggleBriefDateScope(channel, scope) {
  // 控制定时发送中的 today / yesterday 多选。
  const values = sendScheduleForm[channel].brief_date_scopes;
  const index = values.indexOf(scope);
  if (index >= 0) {
    values.splice(index, 1);
  } else {
    values.push(scope);
  }
  if (!values.length) {
    values.push("today");
  }
}

function applyTopicKeywordsToInputs(topicKeywords) {
  // 将后端返回的关键词设置回填到每个主题对应的输入框中。
  TOPICS.forEach((topic) => {
    topicKeywordInputs[topic] = (topicKeywords?.[topic] || []).join("、");
  });
}

function syncUserKeyState(userKey) {
  // 当前项目没有真实登录系统，因此用浏览器本地保存的用户标识来模拟登录态隔离。
  state.userKey = userKey;
  currentUserKey.value = userKey;
  window.localStorage.setItem(USER_KEY_STORAGE, userKey);
}

function showToast(message) {
  toastMessage.value = message;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    toastMessage.value = "";
  }, 2500);
}

async function handleApplyUserKey() {
  const nextUserKey = (currentUserKey.value || "").trim();
  if (!nextUserKey) {
    showToast("请输入有效的用户标识");
    return;
  }
  syncUserKeyState(nextUserKey);
  await reloadAll(false);
  showToast(`已切换到用户：${nextUserKey}`);
}

function handleToggleTopic(topic) {
  toggleTopic(topic);
  if (!Object.prototype.hasOwnProperty.call(topicKeywordInputs, topic)) {
    topicKeywordInputs[topic] = "";
  }
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
    copyBindingsToForm({});
    showToast(`加载发送设置失败：${error.message}`);
  }
}

async function loadSchedule() {
  try {
    const data = await getSetting("schedule");
    const value = data?.value || {};
    // 兼容旧版单时间配置，自动转成新版多时间段结构。
    if (!value.items && value.time) {
      value.items = [
        {
          id: "legacy_schedule",
          time: value.time,
          topics: value.topics || [],
          keywords: value.keywords || [],
          topic_keywords: value.topic_keywords || {},
          enabled: value.enabled !== false,
        },
      ];
    }
    assignScheduleValue(value);
    const firstItem = scheduleForm.items[0];
    if (firstItem) {
      applyTopicKeywordsToInputs(firstItem.topic_keywords);
    }
  } catch (error) {
    showToast(`加载定时设置失败：${error.message}`);
  }
}

async function loadSendSchedules() {
  try {
    const [emailData, feishuData] = await Promise.all([
      getSetting("send_schedule_email"),
      getSetting("send_schedule_feishu"),
    ]);
    const emailValue = emailData?.value || {};
    const feishuValue = feishuData?.value || {};
    sendScheduleForm.email.time = emailValue.time || "07:30";
    sendScheduleForm.email.enabled = !!emailValue.enabled;
    sendScheduleForm.email.brief_date_scopes = emailValue.brief_date_scopes || ["today"];
    sendScheduleForm.feishu.time = feishuValue.time || "07:30";
    sendScheduleForm.feishu.enabled = !!feishuValue.enabled;
    sendScheduleForm.feishu.brief_date_scopes = feishuValue.brief_date_scopes || ["today"];
  } catch (error) {
    showToast(`加载定时发送设置失败：${error.message}`);
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
    showToast("请至少选择一个主题");
    return;
  }
  if (isGenerating.value) {
    return;
  }

  const payload = {
    topics: [...state.topics],
    send_email: Boolean(bindingForm.email.sender.trim()),
    send_feishu: Boolean(bindingForm.feishu.webhook_url.trim()),
    topic_keywords: buildTopicKeywordMap(state.topics),
  };

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

function handleAddScheduleItem() {
  // 将当前工作台选择的主题和关键词快照加入定时列表，供 APScheduler 后续恢复和触发。
  if (!state.topics.length) {
    showToast("请先选择至少一个主题，再添加定时项");
    return;
  }
  scheduleForm.items.push(createScheduleItemFromCurrentSelection());
  showToast("已添加一条定时生成项");
}

function handleReplaceScheduleItem(item) {
  // 用当前工作台选择覆盖某一条定时项，避免在列表里重复填写主题和关键词。
  if (!state.topics.length) {
    showToast("请先选择至少一个主题，再覆盖定时项");
    return;
  }
  item.topics = [...state.topics];
  item.keywords = [];
  item.topic_keywords = buildTopicKeywordMap(state.topics);
  showToast("定时项已更新为当前主题配置");
}

function handleRemoveScheduleItem(scheduleId) {
  // 删除指定定时生成项。
  const index = scheduleForm.items.findIndex((item) => item.id === scheduleId);
  if (index >= 0) {
    scheduleForm.items.splice(index, 1);
    showToast("已删除定时生成项");
  }
}

async function handleSaveSchedule(enabled) {
  // 保存多时间段定时生成配置，并同步开启或关闭 APScheduler 任务。
  if (enabled && !scheduleForm.items.length) {
    if (!state.topics.length) {
      showToast("请至少选择一个主题并添加一条定时项");
      return;
    }
    scheduleForm.items.push(createScheduleItemFromCurrentSelection());
  }

  const payload = {
    enabled,
    items: scheduleForm.items.map((item) => ({
      id: item.id,
      time: item.time,
      topics: item.topics || [],
      keywords: item.keywords || [],
      topic_keywords: item.topic_keywords || {},
      enabled: item.enabled !== false,
    })),
  };

  try {
    const value = await saveSchedule(payload);
    assignScheduleValue(value);
    showToast(enabled ? "已保存并开启定时生成简报" : "已关闭定时生成简报");
  } catch (error) {
    showToast(`保存定时设置失败：${error.message}`);
  }
}

async function handleSendNow(channel) {
  sendNowLoading[channel] = true;
  try {
    const result = await sendNow({
      channel,
      brief_date_scopes: [...sendScheduleForm[channel].brief_date_scopes],
    });
    showToast(result?.message || "发送完成");
  } catch (error) {
    showToast(`发送失败：${error.message}`);
  } finally {
    sendNowLoading[channel] = false;
  }
}

async function handleSaveSendSchedule(channel, enabled) {
  // 保存单个渠道的定时发送配置，并把“今天/昨天”多选一起提交给后端。
  try {
    const value = await saveSendSchedule({
      channel,
      time: sendScheduleForm[channel].time,
      enabled,
      brief_date_scopes: [...sendScheduleForm[channel].brief_date_scopes],
    });
    sendScheduleForm[channel].time = value.time || sendScheduleForm[channel].time;
    sendScheduleForm[channel].enabled = !!value.enabled;
    sendScheduleForm[channel].brief_date_scopes = value.brief_date_scopes || ["today"];
    showToast(
      enabled
        ? `已开启定时发送${channel === "email" ? "邮箱" : "飞书"}`
        : `已取消定时发送${channel === "email" ? "邮箱" : "飞书"}`,
    );
  } catch (error) {
    showToast(`保存定时发送设置失败：${error.message}`);
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

async function reloadAll(showMessage = true) {
  await Promise.all([loadBindings(), loadSchedule(), loadSendSchedules(), loadBriefs()]);
  weatherReloadKey.value += 1;
  if (showMessage) {
    showToast("数据已刷新");
  }
}

onMounted(async () => {
  TOPICS.forEach((topic) => {
    topicKeywordInputs[topic] = "";
  });
  const storedUserKey = getCurrentUserKey();
  syncUserKeyState(storedUserKey);
  await reloadAll(false);
});
</script>


