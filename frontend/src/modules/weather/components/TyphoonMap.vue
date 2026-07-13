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
          <span class="typhoon-map-source">底图：{{ activeProviderName }}（失败时自动切换可用底图源）</span>
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
              @load="handleTileLoad(tile.providerIndex)"
              @error="handleTileError(tile.providerIndex)"
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
                :style="pointVisualStyle(point)"
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
          <p>台风等级：{{ selectedPointTyphoonLevel }}</p>
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

const TILE_SIZE = 256;
const MIN_ZOOM = 4;
const MAX_ZOOM = 7;
const DEFAULT_CENTER = { lon: 118, lat: 28 };
const PROVIDER_CACHE_KEY = "intellibrief_typhoon_tile_provider";
const PROVIDER_CACHE_TTL_MS = 24 * 60 * 60 * 1000;
const TILE_HEALTHCHECK_TIMEOUT_MS = 1500;
const PROVIDER_FAILURE_THRESHOLD = 3;
const PROVIDER_FAILURE_RATIO = 0.25;
const TILE_PROVIDERS = [
  { name: "OpenStreetMap", type: "osm" },
  { name: "OpenStreetMap DE", type: "osmde" },
  { name: "CARTO", type: "carto" },
];

const mapRef = ref(null);
const zoom = ref(5);
const center = reactive({ ...DEFAULT_CENTER });
const viewport = reactive({ width: 960, height: 620 });
const selectedStormId = ref("");
const selectedPointKey = ref("");
const activeProviderIndex = ref(0);
const providerFailureStats = reactive(
  TILE_PROVIDERS.map(() => ({
    loads: 0,
    failures: 0,
  })),
);
const dragging = reactive({
  active: false,
  startX: 0,
  startY: 0,
  startCenterWorldX: 0,
  startCenterWorldY: 0,
});

const stormButtons = computed(() => props.storms || []);
const activeProviderName = computed(() => TILE_PROVIDERS[activeProviderIndex.value]?.name || "OpenStreetMap");

const selectedStorm = computed(() => {
  if (!stormButtons.value.length) {
    return null;
  }
  return stormButtons.value.find((item) => item.id === selectedStormId.value) || stormButtons.value[0];
});

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
      const coordKey = `${zoom.value}-${wrappedX}-${tileY}`;
      const providerIndex = activeProviderIndex.value;
      rows.push({
        key: `${coordKey}-${providerIndex}`,
        coordKey,
        providerIndex,
        url: buildTileUrl(providerIndex, zoom.value, wrappedX, tileY),
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
  return [...track, ...forecast].filter((item) => Number.isFinite(item.worldX) && Number.isFinite(item.worldY));
});

const renderedPoints = computed(() =>
  stormPoints.value.map((item) => ({
    ...item,
    x: item.worldX - topLeftWorld.value.x,
    y: item.worldY - topLeftWorld.value.y,
  })),
);

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

const selectedPointTyphoonLevel = computed(() => {
  if (!selectedPoint.value?.windSpeed) {
    return "-";
  }
  return formatTyphoonLevel(selectedPoint.value.windSpeed);
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
  selectFastProvider();
  window.addEventListener("pointermove", handlePointerMove);
  window.addEventListener("pointerup", handlePointerUp);
  window.addEventListener("resize", updateViewportSize);
});

onBeforeUnmount(() => {
  window.removeEventListener("pointermove", handlePointerMove);
  window.removeEventListener("pointerup", handlePointerUp);
  window.removeEventListener("resize", updateViewportSize);
});

function buildTileUrl(providerIndex, level, x, y) {
  const provider = TILE_PROVIDERS[providerIndex] || TILE_PROVIDERS[0];
  if (provider.type === "carto") {
    const subdomain = ["a", "b", "c", "d"][(x + y) % 4];
    return `https://${subdomain}.basemaps.cartocdn.com/light_all/${level}/${x}/${y}.png`;
  }
  if (provider.type === "osmde") {
    return `https://tile.openstreetmap.de/${level}/${x}/${y}.png`;
  }
  return `https://tile.openstreetmap.org/${level}/${x}/${y}.png`;
}

function handleTileLoad(providerIndex) {
  // 记录当前底图源成功加载次数，用成功率判断是否需要整体切换底图源。
  const stats = providerFailureStats[providerIndex];
  if (!stats) {
    return;
  }
  stats.loads += 1;
  if (providerIndex === activeProviderIndex.value) {
    saveCachedProviderIndex(providerIndex);
  }
}

function handleTileError(providerIndex) {
  // 底图失败按 provider 聚合统计，达到阈值后整体熔断到下一个底图源。
  const stats = providerFailureStats[providerIndex];
  if (!stats) {
    return;
  }
  stats.failures += 1;

  if (providerIndex !== activeProviderIndex.value) {
    return;
  }

  const total = stats.loads + stats.failures;
  const failureRatio = total > 0 ? stats.failures / total : 0;
  const shouldFallback =
    stats.failures >= PROVIDER_FAILURE_THRESHOLD ||
    (total >= 8 && failureRatio >= PROVIDER_FAILURE_RATIO);

  if (shouldFallback) {
    switchToNextProvider();
  }
}

async function selectFastProvider() {
  // 页面加载时先使用上次成功的底图源，同时后台测速，选出当前网络下最快可用的 provider。
  const cachedProviderIndex = readCachedProviderIndex();
  if (cachedProviderIndex != null) {
    setActiveProvider(cachedProviderIndex);
  }

  const speedResults = await Promise.all(
    TILE_PROVIDERS.map((provider, index) =>
      measureProviderSpeed(index).catch(() => ({
        index,
        elapsed: Number.POSITIVE_INFINITY,
        ok: false,
      })),
    ),
  );
  const fastest = speedResults
    .filter((item) => item.ok)
    .sort((a, b) => a.elapsed - b.elapsed)[0];
  if (fastest) {
    setActiveProvider(fastest.index);
  }
}

function measureProviderSpeed(providerIndex) {
  // 用中心点附近的一张瓦片做健康检查，超时即认为该底图源当前不可用。
  const healthTile = getHealthCheckTileCoord();
  const startedAt = performance.now();
  const url = buildTileUrl(providerIndex, healthTile.zoom, healthTile.x, healthTile.y);

  return new Promise((resolve, reject) => {
    const image = new Image();
    const timer = window.setTimeout(() => {
      image.onload = null;
      image.onerror = null;
      reject(new Error("tile health check timeout"));
    }, TILE_HEALTHCHECK_TIMEOUT_MS);

    image.onload = () => {
      window.clearTimeout(timer);
      resolve({
        index: providerIndex,
        elapsed: performance.now() - startedAt,
        ok: true,
      });
    };
    image.onerror = () => {
      window.clearTimeout(timer);
      reject(new Error("tile health check failed"));
    };
    image.src = url;
  });
}

function getHealthCheckTileCoord() {
  // 使用当前地图中心点对应瓦片测速，比固定瓦片更贴近台风路径图实际展示区域。
  const level = clamp(zoom.value, MIN_ZOOM, MAX_ZOOM);
  const tilesPerAxis = 2 ** level;
  const world = lonLatToWorld(center.lon, center.lat, level);
  return {
    zoom: level,
    x: mod(Math.floor(world.x / TILE_SIZE), tilesPerAxis),
    y: clamp(Math.floor(world.y / TILE_SIZE), 0, tilesPerAxis - 1),
  };
}

function switchToNextProvider() {
  // 当前底图源异常时整体切换到下一个 provider，避免逐格兜底导致等待时间过长。
  const nextIndex = (activeProviderIndex.value + 1) % TILE_PROVIDERS.length;
  setActiveProvider(nextIndex);
}

function setActiveProvider(providerIndex) {
  if (!TILE_PROVIDERS[providerIndex] || activeProviderIndex.value === providerIndex) {
    return;
  }
  activeProviderIndex.value = providerIndex;
  resetProviderStats(providerIndex);
  saveCachedProviderIndex(providerIndex);
}

function resetProviderStats(providerIndex) {
  const stats = providerFailureStats[providerIndex];
  if (!stats) {
    return;
  }
  stats.loads = 0;
  stats.failures = 0;
}

function readCachedProviderIndex() {
  try {
    const cached = JSON.parse(window.localStorage.getItem(PROVIDER_CACHE_KEY) || "null");
    if (!cached || Date.now() - Number(cached.savedAt || 0) > PROVIDER_CACHE_TTL_MS) {
      return null;
    }
    return TILE_PROVIDERS[cached.providerIndex] ? cached.providerIndex : null;
  } catch (error) {
    return null;
  }
}

function saveCachedProviderIndex(providerIndex) {
  if (!TILE_PROVIDERS[providerIndex]) {
    return;
  }
  window.localStorage.setItem(
    PROVIDER_CACHE_KEY,
    JSON.stringify({
      providerIndex,
      savedAt: Date.now(),
    }),
  );
}

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

  const fittedZoom = computeFitZoom(
    minLon,
    minLat,
    maxLon,
    maxLat,
    viewport.width - margin * 2,
    viewport.height - margin * 2,
  );
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
    return { worldX: NaN, worldY: NaN };
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

function formatTyphoonLevel(windSpeed) {
  const value = Number(windSpeed);
  if (!Number.isFinite(value) || value <= 0) {
    return "-";
  }

  const thresholds = [
    { max: 1.5, level: "1级" },
    { max: 3.3, level: "2级" },
    { max: 5.4, level: "3级" },
    { max: 7.9, level: "4级" },
    { max: 10.7, level: "5级" },
    { max: 13.8, level: "6级" },
    { max: 17.1, level: "7级" },
    { max: 20.7, level: "8级" },
    { max: 24.4, level: "9级" },
    { max: 28.4, level: "10级" },
    { max: 32.6, level: "11级" },
    { max: 36.9, level: "12级" },
    { max: 41.4, level: "13级" },
    { max: 46.1, level: "14级" },
    { max: 50.9, level: "15级" },
    { max: 56.0, level: "16级" },
    { max: 61.2, level: "17级" },
    { max: 69.3, level: "18级" },
  ];

  const matched = thresholds.find((item) => value <= item.max);
  if (matched) {
    return `${matched.level}（${value} m/s）`;
  }
  return `18级以上（${value} m/s）`;
}

function parseTyphoonLevelNumber(windSpeed) {
  const value = Number(windSpeed);
  if (!Number.isFinite(value) || value <= 0) {
    return null;
  }

  const thresholds = [
    { max: 1.5, level: 1 },
    { max: 3.3, level: 2 },
    { max: 5.4, level: 3 },
    { max: 7.9, level: 4 },
    { max: 10.7, level: 5 },
    { max: 13.8, level: 6 },
    { max: 17.1, level: 7 },
    { max: 20.7, level: 8 },
    { max: 24.4, level: 9 },
    { max: 28.4, level: 10 },
    { max: 32.6, level: 11 },
    { max: 36.9, level: 12 },
    { max: 41.4, level: 13 },
    { max: 46.1, level: 14 },
    { max: 50.9, level: 15 },
    { max: 56.0, level: 16 },
    { max: 61.2, level: 17 },
    { max: 69.3, level: 18 },
  ];

  const matched = thresholds.find((item) => value <= item.max);
  return matched ? matched.level : 19;
}

function getTyphoonPointColor(levelNumber) {
  if (levelNumber == null) {
    return "#2563eb";
  }
  if (levelNumber <= 7) {
    return "#2563eb";
  }
  if (levelNumber <= 9) {
    return "#16a34a";
  }
  if (levelNumber <= 11) {
    return "#facc15";
  }
  if (levelNumber <= 13) {
    return "#fb923c";
  }
  if (levelNumber <= 15) {
    return "#ef4444";
  }
  return "#a21caf";
}

function pointVisualStyle(point) {
  const levelNumber = parseTyphoonLevelNumber(point.windSpeed);
  const fill = getTyphoonPointColor(levelNumber);
  if (point.isCurrent) {
    return {
      fill,
      stroke: "#ffffff",
      strokeWidth: 3,
    };
  }
  return {
    fill,
    stroke: "#ffffff",
    strokeWidth: 2,
  };
}
</script>
