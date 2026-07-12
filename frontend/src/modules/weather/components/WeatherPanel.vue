<template>
  <section>
    <section class="panel">
      <div class="weather-toolbar">
        <div class="weather-search-block">
          <label class="weather-region">
            地区
            <input
              v-model="weatherForm.region"
              type="text"
              placeholder="请输入中文地区，例如北京、温州、福州"
              @focus="handleFocus"
              @blur="handleBlur"
              @input="handleRegionInput"
            >
          </label>
          <div v-if="showSuggestionDropdown" class="weather-suggestion-dropdown">
            <button
              v-for="item in suggestionRows"
              :key="`${item.region}-${item.display_name}`"
              type="button"
              class="weather-suggestion-item"
              @mousedown.prevent="handleSelectSuggestion(item)"
            >
              <span>{{ item.display_name }}</span>
              <small>{{ item.source === "recent" ? "最近查询" : "联想候选" }}</small>
            </button>
          </div>
        </div>
        <div class="weather-actions">
          <button type="button" class="secondary-btn" :disabled="weatherLoading" @click="loadWeather(false)">
            {{ weatherLoading ? "查询中" : "仅查询" }}
          </button>
          <button type="button" class="primary-btn" :disabled="weatherLoading" @click="loadWeather(true)">
            {{ weatherLoading ? "保存中" : "保存地区并查询" }}
          </button>
        </div>
      </div>

      <div v-if="recentQueryRows.length" class="weather-recent-block">
        <div class="weather-recent-title">最近查询</div>
        <div class="weather-recent-list">
          <button
            v-for="item in recentQueryRows"
            :key="`${item.region}-${item.queried_at || item.display_name}`"
            type="button"
            class="chip"
            @click="handleSelectRecent(item)"
          >
            {{ item.display_name || item.region }}
          </button>
        </div>
      </div>

      <div class="weather-meta">
        <span>当前地区：{{ state.weather.region || "未设置" }}</span>
        <span>当天日期：{{ weatherDateLabel }}</span>
        <span>天气源：{{ weatherProviderLabel }}</span>
      </div>
      <div v-if="weatherNotices.length" class="weather-notices">
        <div v-for="notice in weatherNotices" :key="notice" class="weather-notice">{{ notice }}</div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <h2>地区天气</h2>
        <span>展示当天各时段天气、温度、湿度、风力和降雨概率</span>
      </div>
      <div class="weather-summary-grid" v-if="state.weather.report">
        <div class="weather-card">
          <div class="weather-card-label">最低气温</div>
          <div class="weather-card-value">{{ state.weather.report.weather_summary?.temp_min ?? "-" }}°C</div>
        </div>
        <div class="weather-card">
          <div class="weather-card-label">最高气温</div>
          <div class="weather-card-value">{{ state.weather.report.weather_summary?.temp_max ?? "-" }}°C</div>
        </div>
        <div class="weather-card">
          <div class="weather-card-label">时段数</div>
          <div class="weather-card-value">{{ state.weather.report.weather_summary?.hourly_count ?? 0 }}</div>
        </div>
      </div>
      <div v-if="!hourlyRows.length" class="empty">暂无天气数据</div>
      <div v-else class="brief-table">
        <div class="table-row table-head weather-row">
          <div>时间</div>
          <div>天气</div>
          <div>温度</div>
          <div>湿度</div>
          <div>风向/风力</div>
          <div>降雨概率</div>
        </div>
        <div v-for="row in hourlyRows" :key="row.fxTime" class="table-row weather-row">
          <div>{{ formatHour(row.fxTime) }}</div>
          <div>{{ row.text || "-" }}</div>
          <div>{{ row.temp ?? "-" }}°C</div>
          <div>{{ row.humidity ?? "-" }}%</div>
          <div>{{ row.windDir || "-" }} / {{ row.windScale || "-" }}</div>
          <div>{{ row.pop ?? row.precip ?? "-" }}{{ row.pop != null ? "%" : "" }}</div>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <h2>台风情况</h2>
        <span>仅展示当前日期前后一周内的台风，支持按台风名称切换查看路径和预报</span>
      </div>
      <div v-if="!state.weather.report" class="empty">请先查询天气数据</div>
      <div v-else class="typhoon-panel">
        <div class="typhoon-summary">{{ state.weather.report.typhoon?.summary || "最近一周内没有台风" }}</div>

        <div v-if="warningRows.length" class="warning-list">
          <div v-for="warning in warningRows" :key="warning.id || warning.title" class="warning-item">
            <div class="warning-title">{{ warning.title || "天气预警" }}</div>
            <div class="warning-text">{{ warning.text || "-" }}</div>
          </div>
        </div>

        <div v-if="typhoonRows.length">
          <TyphoonMap :storms="typhoonRows" />
        </div>
        <div v-else class="empty">当前日期前后一周内没有台风</div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <h2>原始返回数据</h2>
        <span>直接查看后端返回的天气、预警和台风结构</span>
      </div>
      <div v-if="!state.weather.report" class="empty">暂无返回数据</div>
      <pre v-else class="weather-json-viewer">{{ formattedWeatherJson }}</pre>
    </section>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";

import { getSetting, saveSetting } from "../../../api/settings";
import { getRecentWeatherQueries, getWeatherReport, getWeatherSuggestions } from "../../../api/weather";
import { state } from "../../../state";
import TyphoonMap from "./TyphoonMap.vue";

const props = defineProps({
  reloadKey: {
    type: Number,
    default: 0,
  },
});

const emit = defineEmits(["toast"]);

const weatherLoading = ref(false);
const suggesting = ref(false);
const suggestionVisible = ref(false);
const suggestions = ref([]);
const weatherForm = reactive({
  region: "北京",
});

// 使用中文地区校验规则，避免把英文、问号或纯符号发给后端和第三方天气接口。
const CHINESE_REGION_PATTERN = /^[\u4e00-\u9fff\u3400-\u4dbf·（）()\s]{1,40}$/;

let suggestionTimer = null;

const weatherDateLabel = computed(() => state.weather.report?.date || new Date().toISOString().slice(0, 10));
const hourlyRows = computed(() => state.weather.report?.hourly || []);
const warningRows = computed(() => state.weather.report?.warnings || []);
const typhoonRows = computed(() => state.weather.report?.typhoon?.active || []);
const weatherProviderLabel = computed(() => state.weather.report?.provider?.label || "-");
const weatherNotices = computed(() => state.weather.report?.notices || []);
const recentQueryRows = computed(() => state.weather.recentQueries || []);
const formattedWeatherJson = computed(() => JSON.stringify(state.weather.report, null, 2));

// 合并最近查询和联想结果，减少重复候选项。
const suggestionRows = computed(() => {
  const merged = [];
  const seen = new Set();
  [...suggestions.value, ...recentQueryRows.value].forEach((item) => {
    const key = `${(item.region || "").toLowerCase()}|${item.display_name || ""}`;
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    merged.push(item);
  });
  return merged.slice(0, 8);
});

const showSuggestionDropdown = computed(() => {
  return suggestionVisible.value && (suggestionRows.value.length > 0 || suggesting.value);
});

function showToast(message) {
  emit("toast", message);
}

function formatHour(value) {
  if (!value) {
    return "-";
  }
  return value.slice(11, 16);
}

function isValidChineseRegion(region) {
  const value = (region || "").trim();
  return Boolean(value) && CHINESE_REGION_PATTERN.test(value);
}

async function loadWeatherPreferences() {
  try {
    const data = await getSetting("weather_preferences");
    const value = data?.value || {};
    const region = value.region || state.weather.region || "北京";
    weatherForm.region = region;
    state.weather.region = region;
  } catch (error) {
    showToast(`加载天气设置失败：${error.message}`);
  }
}

async function loadRecentQueries() {
  try {
    const data = await getRecentWeatherQueries();
    state.weather.recentQueries = Array.isArray(data) ? data : [];
  } catch (error) {
    showToast(`加载最近查询失败：${error.message}`);
  }
}

async function loadWeather(persist = false) {
  const region = (weatherForm.region || "").trim();
  if (!region) {
    showToast("请输入天气查询地区。");
    return;
  }
  if (!isValidChineseRegion(region)) {
    showToast("请输入有效的中文地区名称，请重新输入。");
    return;
  }

  weatherLoading.value = true;
  try {
    if (persist) {
      await saveSetting("weather_preferences", { region });
    }
    const report = await getWeatherReport(region);
    if (!report || typeof report !== "object") {
      throw new Error("后端未返回有效天气数据。");
    }
    state.weather.report = report;
    state.weather.region = region;
    await loadRecentQueries();
    showToast("天气数据已更新。");
  } catch (error) {
    state.weather.report = null;
    showToast(`天气查询失败：${error.message}`);
  } finally {
    weatherLoading.value = false;
  }
}

async function searchSuggestions(keyword) {
  const targetKeyword = (keyword || "").trim();
  if (!targetKeyword) {
    suggestions.value = [];
    return;
  }
  if (!isValidChineseRegion(targetKeyword)) {
    suggestions.value = [];
    return;
  }

  suggesting.value = true;
  try {
    const data = await getWeatherSuggestions(targetKeyword);
    suggestions.value = Array.isArray(data) ? data : [];
  } catch (error) {
    suggestions.value = [];
    showToast(`地区联想失败：${error.message}`);
  } finally {
    suggesting.value = false;
  }
}

function handleRegionInput() {
  suggestionVisible.value = true;
  window.clearTimeout(suggestionTimer);
  suggestionTimer = window.setTimeout(() => {
    void searchSuggestions(weatherForm.region);
  }, 250);
}

// 点击候选后自动查询，减少一次额外确认操作。
function handleSelectSuggestion(item) {
  const region = item.region || item.name || "";
  weatherForm.region = region;
  suggestionVisible.value = false;
  suggestions.value = [];
  void loadWeather(false);
}

function handleSelectRecent(item) {
  weatherForm.region = item.region || item.display_name || "";
  void loadWeather(false);
}

function handleFocus() {
  suggestionVisible.value = true;
  if (!weatherForm.region.trim()) {
    suggestions.value = [];
    return;
  }
  handleRegionInput();
}

function handleBlur() {
  // 给候选点击保留极短缓冲，避免 blur 过早关闭下拉。
  window.setTimeout(() => {
    suggestionVisible.value = false;
  }, 120);
}

async function initializeWeatherPanel() {
  await Promise.all([loadWeatherPreferences(), loadRecentQueries()]);
  if (!state.weather.report && weatherForm.region) {
    await loadWeather(false);
  }
}

watch(
  () => props.reloadKey,
  async () => {
    await initializeWeatherPanel();
  },
);

onMounted(async () => {
  await initializeWeatherPanel();
});

onBeforeUnmount(() => {
  window.clearTimeout(suggestionTimer);
});
</script>
