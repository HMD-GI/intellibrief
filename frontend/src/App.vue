<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">IB</div>
        <div>
          <div class="brand-title">IntelliBrief</div>
          <div class="brand-subtitle">每日情报工作台</div>
        </div>
      </div>
      <nav class="nav">
        <button class="nav-item" :class="{ active: state.view === 'dashboard' }" @click="setView('dashboard')">工作台</button>
        <button class="nav-item" :class="{ active: state.view === 'briefs' }" @click="setView('briefs')">简报列表</button>
        <button class="nav-item" :class="{ active: state.view === 'bindings' }" @click="setView('bindings')">绑定设置</button>
      </nav>
    </aside>

    <main class="main">
      <header class="topbar">
        <div>
          <h1>{{ pageTitle }}</h1>
          <p>{{ pageSubtitle }}</p>
        </div>
        <button type="button" class="icon-btn" title="刷新" @click="reloadAll">↻</button>
      </header>

      <ToastBar :message="toastMessage" />

      <section v-if="state.view === 'dashboard'">
        <div class="grid two">
          <section class="panel">
            <div class="panel-head">
              <h2>主题</h2>
              <span>可多选</span>
            </div>
            <TopicChips :topics="TOPICS" :modelValue="state.topics" @toggle="handleToggleTopic" />
            <label class="keyword-field">
              关键词
              <input
                v-model="keywordInput"
                type="text"
                placeholder='可选，如“美国、欧洲”等'
              >
            </label>
          </section>

          <section class="panel">
            <div class="panel-head">
              <h2>生成</h2>
              <span>今日简报</span>
            </div>
            <button type="button" class="primary-btn" :disabled="isGenerating" @click="handleGenerate">
              {{ isGenerating ? "正在生成中" : "一键生成当日简报" }}
            </button>
            <div class="schedule-row">
              <input v-model="scheduleForm.time" type="time">
              <button type="button" class="secondary-btn" @click="handleToggleSchedule">
                {{ scheduleForm.enabled ? "已开始定时生成简报" : "开始定时生成简报" }}
              </button>
              <span v-if="scheduleForm.enabled" class="schedule-topic">主题：{{ scheduleForm.topics.join("、") }}</span>
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

      <section v-else-if="state.view === 'briefs'">
        <section class="panel">
          <div class="filter-bar">
            <label>开始时间<input v-model="filters.start_date" type="date"></label>
            <label>结束时间<input v-model="filters.end_date" type="date"></label>
            <label>类型
              <select v-model="filters.brief_type">
                <option value="all">全部</option>
                <option value="daily">每日简报</option>
              </select>
            </label>
            <label>主题
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
              <span>选填</span>
            </div>
            <label>发件邮箱<input v-model="bindingForm.email.sender" placeholder="name@example.com"></label>
            <label>授权码<input v-model="bindingForm.email.password" type="password" placeholder="SMTP 授权码"></label>
            <label>收件人<input v-model="bindingForm.email.receivers" placeholder="多个邮箱用逗号分隔"></label>
            <label>SMTP 服务器<input v-model="bindingForm.email.smtp_host" placeholder="smtp.163.com"></label>
            <label>SMTP 端口<input v-model="bindingForm.email.smtp_port" type="number" placeholder="465"></label>
            <label class="check-row">
              <input v-model="bindingForm.email.smtp_use_ssl" type="checkbox">
              使用 SSL
            </label>
          </section>
          <section class="panel">
            <div class="panel-head">
              <h2>飞书</h2>
              <span>选填</span>
            </div>
            <label>Webhook<input v-model="bindingForm.feishu.webhook" placeholder="https://open.feishu.cn/..."></label>
          </section>
        </div>
        <section class="panel actions-panel">
          <button type="button" class="primary-btn" @click="handleSaveBindings">保存绑定</button>
          <button type="button" class="secondary-btn" @click="handleClearBindings">清空绑定</button>
        </section>
      </section>
    </main>
  </div>

  <div v-if="briefModalVisible" class="modal" @click.self="closeModal">
    <div class="modal-card">
      <header>
        <h2>{{ modalTitle }}</h2>
        <button type="button" class="icon-btn" title="关闭" @click="closeModal">×</button>
      </header>
      <iframe :src="briefFrameUrl" title="简报内容"></iframe>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref, onMounted } from "vue";  // 导入 Vue 响应式工具
import TopicChips from "./components/TopicChips.vue";  // 导入主题按钮组组件
import BriefTable from "./components/BriefTable.vue";  // 导入简报表格组件
import ToastBar from "./components/ToastBar.vue";  // 导入提示组件
import { state, TOPICS, setView, toggleTopic } from "./state";  // 导入共享状态
import { queryBriefs, deleteBrief, getBriefHtmlUrl } from "./api/briefs";  // 导入简报接口
import { generateTodayBrief, saveSchedule } from "./api/tasks";  // 导入任务接口
import { getSetting, saveSetting } from "./api/settings";  // 导入设置接口

const toastMessage = ref("");  // 顶部提示消息
const isGenerating = ref(false);  // 控制一键生成按钮状态
const briefModalVisible = ref(false);  // 简报弹窗显示状态
const modalTitle = ref("简报详情");  // 弹窗标题
const briefFrameUrl = ref("");  // iframe 预览地址
const keywordInput = ref("");  // 当前页面的关键词输入框文本

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
  keywords: [],  // 保存定时任务使用的关键词数组
});

const bindingForm = reactive({
  email: {
    sender: "",
    password: "",
    receivers: "",
    smtp_host: "",
    smtp_port: "465",
    smtp_use_ssl: true,
  },
  feishu: {
    webhook: "",
  },
});

const pageTitle = computed(() => {
  if (state.view === "briefs") return "简报列表";
  if (state.view === "bindings") return "绑定设置";
  return "工作台";
});

const pageSubtitle = computed(() => {
  if (state.view === "briefs") return "按时间范围和类型查询已生成简报。";
  if (state.view === "bindings") return "绑定邮箱和飞书，用于简报推送。";
  return "选择主题，可选输入关键词，生成或安排今日简报。";
});

const recentBriefs = computed(() => state.briefs.slice(0, 5));  // 最近 5 条简报

function parseKeywords(inputText) {
  return (inputText || "")
    .split("、")
    .map((item) => item.trim())  // 按顿号分隔并去掉首尾空白
    .filter(Boolean);  // 去掉空字符串
}

function showToast(message) {
  toastMessage.value = message;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    toastMessage.value = "";
  }, 2500);
}

function copyBindingsToForm(data) {
  bindingForm.email.sender = data?.email?.sender || "";
  bindingForm.email.password = data?.email?.password || "";
  bindingForm.email.receivers = data?.email?.receivers || "";
  bindingForm.email.smtp_host = data?.email?.smtp_host || "";
  bindingForm.email.smtp_port = data?.email?.smtp_port || "465";
  bindingForm.email.smtp_use_ssl = data?.email?.smtp_use_ssl ?? true;
  bindingForm.feishu.webhook = data?.feishu?.webhook || "";
}

async function loadBindings() {
  try {
    const data = await getSetting("bindings");
    copyBindingsToForm(data?.value || {});
  } catch (error) {
    showToast(`加载绑定失败：${error.message}`);
  }
}

async function loadSchedule() {
  try {
    const data = await getSetting("schedule");
    scheduleForm.time = data?.value?.time || "07:00";
    scheduleForm.enabled = !!data?.value?.enabled;
    scheduleForm.topics = data?.value?.topics || [];
    scheduleForm.keywords = data?.value?.keywords || [];
    keywordInput.value = (data?.value?.keywords || []).join("、");  // 恢复最近一次保存的关键词显示
  } catch (error) {
    showToast(`加载定时失败：${error.message}`);
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
    showToast(`简报列表加载失败：${error.message}`);
  }
}

function handleToggleTopic(topic) {
  toggleTopic(topic);  // 切换主题选择
}

async function handleGenerate() {
  if (!state.topics.length) {
    showToast("一定要选择一个主题");
    return;
  }
  if (isGenerating.value) return;
  const keywords = parseKeywords(keywordInput.value);  // 提交前将顿号分隔字符串转为数组
  isGenerating.value = true;
  showToast("正在生成中，请等待后端全流程结束");
  try {
    const payload = {
      topics: state.topics,
      send_email: !!bindingForm.email.sender.trim(),
      send_feishu: !!bindingForm.feishu.webhook.trim(),
    };
    if (keywords.length) {
      payload.keywords = keywords;  // 只有关键词数组非空时才传给后端
    }
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
  try {
    const nextEnabled = !scheduleForm.enabled;
    const topics = nextEnabled ? [...state.topics] : scheduleForm.topics;
    const keywords = parseKeywords(keywordInput.value);  // 定时生成也复用同一关键词输入框
    const payload = {
      time: scheduleForm.time,
      topics,
      enabled: nextEnabled,
    };
    if (keywords.length) {
      payload.keywords = keywords;  // 仅当关键词非空时才传给后端
    }
    const value = await saveSchedule(payload);
    scheduleForm.enabled = !!value?.enabled;
    scheduleForm.topics = value?.topics || [];
    scheduleForm.keywords = value?.keywords || [];
    showToast(scheduleForm.enabled ? "已开始定时生成简报" : "已取消定时生成简报");
  } catch (error) {
    showToast(`保存定时失败：${error.message}`);
  }
}

async function handleSaveBindings() {
  try {
    await saveSetting("bindings", {
      email: { ...bindingForm.email },
      feishu: { ...bindingForm.feishu },
    });
    showToast("绑定已保存");
  } catch (error) {
    showToast(`保存绑定失败：${error.message}`);
  }
}

async function handleClearBindings() {
  bindingForm.email.sender = "";
  bindingForm.email.password = "";
  bindingForm.email.receivers = "";
  bindingForm.email.smtp_host = "";
  bindingForm.email.smtp_port = "465";
  bindingForm.email.smtp_use_ssl = true;
  bindingForm.feishu.webhook = "";
  await handleSaveBindings();
}

async function handleDeleteBrief(item) {
  if (!window.confirm(`确认删除 ${item.date} ${item.topic || "综合"} 的简报？`)) return;
  try {
    await deleteBrief(item.id);
    showToast("已删除");
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
  showToast("已刷新");
}

onMounted(async () => {
  await reloadAll();
});
</script>
