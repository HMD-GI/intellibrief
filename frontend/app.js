import { api } from "./api.js";
import { renderBriefTable, renderTopics, showToast } from "./components.js";
import { state, TOPICS, setView, toggleTopic } from "./state.js";

const els = {};

function bindElements() {
  [
    "pageTitle",
    "pageSubtitle",
    "toast",
    "dashboardView",
    "briefsView",
    "bindingsView",
    "topicGroup",
    "generateTodayBtn",
    "saveScheduleBtn",
    "scheduleTime",
    "openBriefListBtn",
    "recentBriefs",
    "briefList",
    "searchBriefsBtn",
    "startDate",
    "endDate",
    "briefType",
    "emailSender",
    "emailPassword",
    "emailReceivers",
    "feishuWebhook",
    "saveBindingsBtn",
    "clearBindingsBtn",
    "briefModal",
    "briefFrame",
    "modalTitle",
    "closeModalBtn",
    "refreshBtn",
  ].forEach((id) => {
    els[id] = document.getElementById(id);
  });
}

function setActiveView(view) {
  setView(view);
  document.querySelectorAll(".view").forEach((node) => node.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach((node) => node.classList.remove("active"));
  document.querySelector(`[data-view="${view}"]`)?.classList.add("active");

  const titles = {
    dashboard: ["工作台", "选择主题，生成或安排今日简报。"],
    briefs: ["简报列表", "按时间范围和类型查询已生成简报。"],
    bindings: ["绑定设置", "绑定邮箱和飞书，用于简报推送。"],
  };
  els.pageTitle.textContent = titles[view][0];
  els.pageSubtitle.textContent = titles[view][1];
  document.getElementById(`${view}View`).classList.add("active");
}

function readBindingsFromForm() {
  return {
    email: {
      sender: els.emailSender.value.trim(),
      password: els.emailPassword.value.trim(),
      receivers: els.emailReceivers.value.trim(),
    },
    feishu: {
      webhook: els.feishuWebhook.value.trim(),
    },
  };
}

function fillBindingsForm(bindings) {
  els.emailSender.value = bindings?.email?.sender || "";
  els.emailPassword.value = bindings?.email?.password || "";
  els.emailReceivers.value = bindings?.email?.receivers || "";
  els.feishuWebhook.value = bindings?.feishu?.webhook || "";
}

async function loadBindings() {
  const data = await api.getSetting("bindings").catch(() => ({ value: {} }));
  state.bindings = data?.value || state.bindings;
  fillBindingsForm(state.bindings);
}

async function loadSchedule() {
  const data = await api.getSetting("schedule").catch(() => ({ value: {} }));
  state.schedule = { ...state.schedule, ...(data?.value || {}) };
  els.scheduleTime.value = state.schedule.time || "07:00";
}

async function loadBriefs() {
  try {
    const data = await api.queryBriefs({
      start_date: els.startDate?.value || "",
      end_date: els.endDate?.value || "",
      brief_type: els.briefType?.value || "all",
      limit: 50,
    });
    state.briefs = data.items || [];
    renderBriefTable(els.briefList, state.briefs, openBrief, deleteBrief);
    renderBriefTable(els.recentBriefs, state.briefs.slice(0, 5), openBrief, deleteBrief);
  } catch (error) {
    console.error(error);
    showToast(els.toast, `简报列表加载失败：${error.message}`);
  }
}

function openBrief(date) {
  els.modalTitle.textContent = `${date} 简报`;
  els.briefFrame.src = `/briefs/${date}`;
  els.briefModal.classList.remove("hidden");
}

async function deleteBrief(date) {
  if (!confirm(`确认删除 ${date} 的简报？`)) return;
  try {
    await api.deleteBrief(date);
    showToast(els.toast, "已删除");
    await loadBriefs();
  } catch (error) {
    console.error(error);
    showToast(els.toast, `删除失败：${error.message}`);
  }
}

async function saveBindings() {
  try {
    const value = readBindingsFromForm();
    await api.saveSetting("bindings", value);
    state.bindings = value;
    showToast(els.toast, "绑定已保存");
  } catch (error) {
    console.error(error);
    showToast(els.toast, `绑定保存失败：${error.message}`);
  }
}

async function saveSchedule() {
  try {
    const value = {
      time: els.scheduleTime.value,
      topics: state.topics,
      enabled: true,
    };
    await api.saveSchedule(value);
    state.schedule = value;
    showToast(els.toast, "定时配置已保存");
  } catch (error) {
    console.error(error);
    showToast(els.toast, `定时配置保存失败：${error.message}`);
  }
}

async function generateBrief() {
  try {
    await api.generateToday({
      topics: state.topics,
      send_email: !!els.emailSender.value.trim(),
      send_feishu: !!els.feishuWebhook.value.trim(),
    });
    showToast(els.toast, "已提交生成任务");
  } catch (error) {
    console.error(error);
    showToast(els.toast, `生成任务提交失败：${error.message}`);
  }
}

function wireEvents() {
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.addEventListener("click", () => setActiveView(button.dataset.view));
  });

  els.generateTodayBtn.addEventListener("click", generateBrief);
  els.saveScheduleBtn.addEventListener("click", saveSchedule);
  els.openBriefListBtn.addEventListener("click", () => setActiveView("briefs"));
  els.saveBindingsBtn.addEventListener("click", saveBindings);
  els.clearBindingsBtn.addEventListener("click", async () => {
    fillBindingsForm({});
    await saveBindings();
  });
  els.closeModalBtn.addEventListener("click", () => els.briefModal.classList.add("hidden"));
  els.briefModal.addEventListener("click", (event) => {
    if (event.target === els.briefModal) els.briefModal.classList.add("hidden");
  });
  els.searchBriefsBtn.addEventListener("click", loadBriefs);
  els.refreshBtn.addEventListener("click", loadBriefs);
  document.getElementById("briefType").addEventListener("change", loadBriefs);
}

function renderTopicControls() {
  renderTopics(els.topicGroup, TOPICS, state.topics, (topic) => {
    toggleTopic(topic);
    renderTopicControls();
  });
}

async function init() {
  bindElements();
  wireEvents();
  renderTopicControls();

  await loadBindings();
  await loadSchedule();
  await loadBriefs();
  setActiveView("dashboard");
}

init().catch((error) => {
  console.error(error);
  showToast(document.getElementById("toast"), `初始化失败：${error.message}`);
});
