<template>
  <div class="typhoon-map-shell">
    <div v-if="stormButtons.length > 1" class="typhoon-switcher">
      <button
        v-for="item in stormButtons"
        :key="item.id"
        type="button"
        class="chip"
        :class="{ active: item.id === selectedStormId }"
        @click="selectStorm(item.id)"
      >
        {{ item.name }}
      </button>
    </div>

    <div v-if="!selectedStorm" class="empty">当前日期前后一周内没有可展示的台风路径数据</div>

    <div v-else class="typhoon-map-layout">
      <div class="typhoon-map-card">
        <div class="typhoon-map-toolbar">
          <span class="typhoon-map-source">底图：OpenStreetMap</span>
          <div class="typhoon-map-zoom">
            <button type="button" class="secondary-btn" @click="zoomOut">-</button>
            <span>级别 {{ zoom }}</span>
            <button type="button" class="secondary-btn" @click="zoomIn">+</button>
          </div>
        </div>

        <div
          ref="mapRef"
          class="typhoon-map-viewport"
          @pointerdown="handlePointerDown"
          @wheel.prevent="handleWheel"
        >
          <div class="typhoon-tile-layer">
            <img
              v-for="tile in tiles"
              :key="tile.key"
              :src="tile.url"
              :style="tile.style"
              class="typhoon-tile"
              alt=""
              draggable="false"
            >
          </div>

          <svg class="typhoon-overlay" :viewBox="`0 0 ${viewport.width} ${viewport.height}`">
            <polyline
              v-if="pathCoordinates.length > 1"
              class="typhoon-path-line"
              :points="pathCoordinates"
            />

            <g v-for="point in renderedPoints" :key="point.key">
              <circle
                :cx="point.x"
                :cy="point.y"
                :r="point.isCurrent ? 8 : 5"
                :class="point.isCurrent ? 'typhoon-point-current' : point.kind === 'forecast' ? 'typhoon-point-forecast' : 'typhoon-point-track'"
                @click="selectPoint(point)"
              />
              <text
                v-if="point.isCurrent"
                :x="point.x"
                :y="point.y - 12"
                class="typhoon-current-label"
              >
                🌀
              </text>
            </g>
          </svg>
        </div>
      </div>

      <div class="typhoon-map-side">
        <div class="typhoon-side-card">
          <h3>{{ selectedStorm.name }}</h3>
          <div class="forecast-title">点位详情</div>
          <p>时间：{{ selectedPoint?.fxTime || "-" }}</p>
          <p>类型：{{ selectedPointLabel }}</p>
          <p>描述：{{ selectedPoint?.text || "-" }}</p>
          <p>经纬度：{{ selectedPoint?.lat || "-" }}, {{ selectedPoint?.lon || "-" }}</p>
          <p>风速：{{ selectedPoint?.windSpeed || "-" }}</p>
          <p>气压：{{ selectedPoint?.pressure || "-" }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";

const props = defineProps({
  storms: {
    type: Array,
    default: () => [],
  },
});

// 使用 Web Mercator 投影把经纬度转换到真实瓦片底图上。
// 这样可以在不引入重量级地图 SDK 的前提下，叠加台风路径和点位信息。
const TILE_SIZE = 256;
const MIN_ZOOM = 4;
const MAX_ZOOM = 7;
const DEFAULT_CENTER = { lon: 118, lat: 28 };

const mapRef = ref(null);
const zoom = ref(5);
const center = reactive({ ...DEFAULT_CENTER });
const viewport = reactive({ width: 960, height: 620 });
const selectedStormId = ref("");
const selectedPointKey = ref("");
const dragging = reactive({
  active: false,
  startX: 0,
  startY: 0,
  startCenterWorldX: 0,
  startCenterWorldY: 0,
});

const stormButtons = computed(() => props.storms || []);

const selectedStorm = computed(() => {
  if (!stormButtons.value.length) {
    return null;
  }
  return stormButtons.value.find((item) => item.id === selectedStormId.value) || stormButtons.value[0];
});

const worldSize = computed(() => TILE_SIZE * 2 ** zoom.value);
const centerWorld = computed(() => lonLatToWorld(center.lon, center.lat, zoom.value));
const topLeftWorld = computed(() => ({
  x: centerWorld.value.x - viewport.width / 2,
  y: centerWorld.value.y - viewport.height / 2,
}));

const tiles = computed(() => {
  const tilesPerAxis = 2 ** zoom.value;
  const startX = Math.floor(topLeftWorld.value.x / TILE_SIZE) - 1;
  const endX = Math.floor((topLeftWorld.value.x + viewport.width) / TILE_SIZE) + 1;
  const startY = Math.floor(topLeftWorld.value.y / TILE_SIZE) - 1;
  const endY = Math.floor((topLeftWorld.value.y + viewport.height) / TILE_SIZE) + 1;
  const rows = [];

  for (let tileX = startX; tileX <= endX; tileX += 1) {
    for (let tileY = startY; tileY <= endY; tileY += 1) {
      if (tileY < 0 || tileY >= tilesPerAxis) {
        continue;
      }
      const wrappedX = mod(tileX, tilesPerAxis);
      rows.push({
        key: `${zoom.value}-${wrappedX}-${tileY}`,
        url: `https://tile.openstreetmap.org/${zoom.value}/${wrappedX}/${tileY}.png`,
        style: {
          left: `${tileX * TILE_SIZE - topLeftWorld.value.x}px`,
          top: `${tileY * TILE_SIZE - topLeftWorld.value.y}px`,
          width: `${TILE_SIZE}px`,
          height: `${TILE_SIZE}px`,
        },
      });
    }
  }
  return rows;
});

const stormPoints = computed(() => {
  if (!selectedStorm.value) {
    return [];
  }

  const currentFxTime = selectedStorm.value.current_point?.fxTime || "";
  const track = (selectedStorm.value.track || []).map((item, index) =>
    projectPoint(item, index, "track", item.fxTime === currentFxTime),
  );
  const forecast = (selectedStorm.value.forecast || []).map((item, index) =>
    projectPoint(item, index, "forecast", false),
  );
  // 这里必须按投影后的世界坐标过滤。
  // 上一版错误地检查了 item.x / item.y，但这两个字段要到 renderedPoints 阶段才会生成，
  // 导致所有点位都被提前过滤掉，地图上看不到任何路径点，右侧详情也始终为空。
  return [...track, ...forecast].filter((item) => Number.isFinite(item.worldX) && Number.isFinite(item.worldY));
});

const renderedPoints = computed(() => stormPoints.value.map((item) => ({
  ...item,
  x: item.worldX - topLeftWorld.value.x,
  y: item.worldY - topLeftWorld.value.y,
})));

const selectedPoint = computed(() => {
  if (!renderedPoints.value.length) {
    return null;
  }
  return renderedPoints.value.find((item) => item.key === selectedPointKey.value) || renderedPoints.value[0];
});

const selectedPointLabel = computed(() => {
  if (!selectedPoint.value) {
    return "-";
  }
  if (selectedPoint.value.isCurrent) {
    return "当前位置";
  }
  return selectedPoint.value.kind === "forecast" ? "未来预测点" : "实况路径点";
});

const pathCoordinates = computed(() => renderedPoints.value.map((item) => `${item.x},${item.y}`).join(" "));

watch(
  () => stormButtons.value,
  (items) => {
    if (!items.length) {
      selectedStormId.value = "";
      selectedPointKey.value = "";
      return;
    }
    if (!items.find((item) => item.id === selectedStormId.value)) {
      selectedStormId.value = items[0].id;
    }
  },
  { immediate: true },
);

watch(
  () => selectedStorm.value,
  () => {
    fitStormToViewport();
  },
  { immediate: true },
);

watch(
  () => renderedPoints.value,
  (items) => {
    if (!items.length) {
      selectedPointKey.value = "";
      return;
    }
    if (!items.find((item) => item.key === selectedPointKey.value)) {
      selectedPointKey.value = items.find((item) => item.isCurrent)?.key || items[0].key;
    }
  },
  { immediate: true },
);

onMounted(() => {
  updateViewportSize();
  window.addEventListener("pointermove", handlePointerMove);
  window.addEventListener("pointerup", handlePointerUp);
  window.addEventListener("resize", updateViewportSize);
});

onBeforeUnmount(() => {
  window.removeEventListener("pointermove", handlePointerMove);
  window.removeEventListener("pointerup", handlePointerUp);
  window.removeEventListener("resize", updateViewportSize);
});

function updateViewportSize() {
  if (!mapRef.value) {
    return;
  }
  const rect = mapRef.value.getBoundingClientRect();
  viewport.width = Math.max(640, Math.round(rect.width || 960));
  viewport.height = Math.max(520, Math.round(rect.height || 620));
  fitStormToViewport();
}

function fitStormToViewport() {
  if (!selectedStorm.value) {
    return;
  }
  const points = [...(selectedStorm.value.track || []), ...(selectedStorm.value.forecast || [])]
    .map((item) => ({
      lon: Number(item.lon),
      lat: Number(item.lat),
    }))
    .filter((item) => Number.isFinite(item.lon) && Number.isFinite(item.lat));

  if (!points.length) {
    return;
  }

  const margin = 64;
  const lonValues = points.map((item) => item.lon);
  const latValues = points.map((item) => item.lat);
  const minLon = Math.min(...lonValues);
  const maxLon = Math.max(...lonValues);
  const minLat = Math.min(...latValues);
  const maxLat = Math.max(...latValues);

  const fittedZoom = computeFitZoom(minLon, minLat, maxLon, maxLat, viewport.width - margin * 2, viewport.height - margin * 2);
  zoom.value = clamp(Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, fittedZoom)), MIN_ZOOM, MAX_ZOOM);

  const centerLon = (minLon + maxLon) / 2;
  const centerLat = (minLat + maxLat) / 2;
  center.lon = clamp(centerLon, 70, 145);
  center.lat = clamp(centerLat, 10, 55);
}

function selectStorm(stormId) {
  selectedStormId.value = stormId;
}

function selectPoint(point) {
  selectedPointKey.value = point.key;
}

function zoomIn() {
  zoom.value = Math.min(MAX_ZOOM, zoom.value + 1);
}

function zoomOut() {
  zoom.value = Math.max(MIN_ZOOM, zoom.value - 1);
}

function handleWheel(event) {
  if (event.deltaY < 0) {
    zoomIn();
  } else {
    zoomOut();
  }
}

function handlePointerDown(event) {
  dragging.active = true;
  dragging.startX = event.clientX;
  dragging.startY = event.clientY;
  dragging.startCenterWorldX = centerWorld.value.x;
  dragging.startCenterWorldY = centerWorld.value.y;
}

function handlePointerMove(event) {
  if (!dragging.active) {
    return;
  }
  const nextWorldX = dragging.startCenterWorldX - (event.clientX - dragging.startX);
  const nextWorldY = dragging.startCenterWorldY - (event.clientY - dragging.startY);
  const nextCenter = worldToLonLat(nextWorldX, nextWorldY, zoom.value);
  center.lon = clamp(nextCenter.lon, 70, 145);
  center.lat = clamp(nextCenter.lat, 10, 55);
}

function handlePointerUp() {
  dragging.active = false;
}

function projectPoint(item, index, kind, isCurrent) {
  const lon = Number(item.lon);
  const lat = Number(item.lat);
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) {
    return { x: NaN, y: NaN };
  }
  const world = lonLatToWorld(lon, lat, zoom.value);
  return {
    ...item,
    key: `${kind}-${index}-${item.fxTime}-${item.lat}-${item.lon}`,
    kind,
    isCurrent,
    worldX: world.x,
    worldY: world.y,
  };
}

function computeFitZoom(minLon, minLat, maxLon, maxLat, width, height) {
  const lonZoom = zoomForSpan(Math.max(0.001, maxLon - minLon), width);
  const latZoom = zoomForSpan(Math.max(0.001, maxLat - minLat), height);
  return Math.floor(Math.min(lonZoom, latZoom));
}

function zoomForSpan(spanDegrees, pixelSize) {
  const worldPixelsAtZoom0 = TILE_SIZE;
  const approxPixelsAtZoom0 = (spanDegrees / 360) * worldPixelsAtZoom0;
  if (approxPixelsAtZoom0 <= 0) {
    return MAX_ZOOM;
  }
  return Math.log2(pixelSize / approxPixelsAtZoom0);
}

function lonLatToWorld(lon, lat, level) {
  const size = TILE_SIZE * 2 ** level;
  const x = ((lon + 180) / 360) * size;
  const sinLat = Math.sin((lat * Math.PI) / 180);
  const y = (0.5 - Math.log((1 + sinLat) / (1 - sinLat)) / (4 * Math.PI)) * size;
  return { x, y };
}

function worldToLonLat(x, y, level) {
  const size = TILE_SIZE * 2 ** level;
  const lon = (x / size) * 360 - 180;
  const n = Math.PI - (2 * Math.PI * y) / size;
  const lat = (180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
  return { lon, lat };
}

function mod(value, divisor) {
  return ((value % divisor) + divisor) % divisor;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}
</script>
