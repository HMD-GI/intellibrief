import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.config import settings

logger = logging.getLogger(__name__)

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


class WeatherServiceError(RuntimeError):
    """天气服务统一异常。"""


class BaseWeatherProvider:
    """天气供应商基类。

    技术原理：
    1. 不同天气供应商的原始字段差异很大，需要先在服务层做统一归一化。
    2. 统一处理超时、重试和异常包装，减少重复代码。
    3. 前端、通知模块只依赖统一结构，不直接依赖第三方 API 细节。
    """

    provider_name = "base"
    provider_label = "基础天气源"
    supports_warning = False
    supports_typhoon = False

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            backoff_factor=0.4,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session = requests.Session()
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def get_daily_weather_report(self, region: str) -> dict[str, Any]:
        raise NotImplementedError

    def search_locations(self, keyword: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def _request_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        optional: bool = False,
        method: str = "GET",
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self.session.request(
                method=method.upper(),
                url=url,
                params=params or {},
                headers=headers or {},
                json=json_body,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            if optional:
                logger.warning("Optional weather request failed: %s %s", url, exc)
                return {}
            raise WeatherServiceError(f"{self.provider_label} 请求失败：{exc}") from exc

        if optional and response.status_code in (401, 403, 404):
            logger.warning(
                "Optional weather endpoint unavailable: provider=%s url=%s status=%s",
                self.provider_name,
                url,
                response.status_code,
            )
            return {}

        try:
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            if optional:
                logger.warning("Optional weather response parse failed: %s %s", url, exc)
                return {}
            # 记录响应体前缀，便于定位第三方接口到底是路径错误、权限问题还是业务限制。
            response_preview = ""
            try:
                response_preview = (response.text or "")[:300]
            except Exception:
                response_preview = ""
            raise WeatherServiceError(
                f"{self.provider_label} 返回异常：status={response.status_code} error={exc} body={response_preview}"
            ) from exc

    @staticmethod
    def _now() -> datetime:
        return datetime.now(SHANGHAI_TZ)

    @classmethod
    def _today_str(cls) -> str:
        return cls._now().strftime("%Y-%m-%d")

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        try:
            return int(float(value))
        except Exception:
            return None

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        try:
            return float(value)
        except Exception:
            return None

    @staticmethod
    def _wind_direction_from_degree(degree: Any) -> str:
        value = BaseWeatherProvider._safe_float(degree)
        if value is None:
            return "-"
        directions = ["北", "东北", "东", "东南", "南", "西南", "西", "西北", "北"]
        return directions[round(value / 45) % 8]

    @staticmethod
    def _kmh_to_scale(speed: Any) -> str:
        value = BaseWeatherProvider._safe_float(speed)
        if value is None:
            return "-"
        thresholds = [1, 6, 12, 20, 29, 39, 50, 62, 75, 89, 103, 118]
        for index, limit in enumerate(thresholds):
            if value < limit:
                return f"{index}级"
        return "12级+"

    @classmethod
    def _build_weather_summary(cls, hourly: list[dict[str, Any]]) -> dict[str, Any]:
        temp_values = [cls._safe_int(item.get("temp")) for item in hourly]
        temp_values = [value for value in temp_values if value is not None]
        return {
            "temp_min": min(temp_values) if temp_values else None,
            "temp_max": max(temp_values) if temp_values else None,
            "hourly_count": len(hourly),
        }

    @staticmethod
    def _location_display_name(location: dict[str, Any]) -> str:
        return " / ".join(
            [
                part
                for part in [
                    location.get("country"),
                    location.get("adm1"),
                    location.get("adm2"),
                    location.get("name"),
                ]
                if part
            ]
        )

    def _build_report(
        self,
        *,
        region: str,
        location: dict[str, Any],
        hourly: list[dict[str, Any]],
        warnings: list[dict[str, Any]],
        typhoon: dict[str, Any],
        notices: list[str] | None = None,
        mode: str = "primary",
    ) -> dict[str, Any]:
        return {
            "region": region,
            "date": self._today_str(),
            "provider": {
                "name": self.provider_name,
                "label": self.provider_label,
                "mode": mode,
            },
            "capabilities": {
                "warning": self.supports_warning,
                "typhoon": self.supports_typhoon,
            },
            "location": location,
            "hourly": hourly,
            "weather_summary": self._build_weather_summary(hourly),
            "warnings": warnings,
            "typhoon": typhoon,
            "notices": notices or [],
            "fetched_at": self._now().isoformat(timespec="seconds"),
        }


class QWeatherService(BaseWeatherProvider):
    """和风天气服务。

    采用它作为国内主源的原因：
    1. 逐小时天气、预警、台风能力比较完整。
    2. 地区地理编码质量更适合中文地区联想。
    3. 作为主源时，可以把台风和预警也纳入统一结果。
    """

    provider_name = "qweather"
    provider_label = "和风天气"
    supports_warning = True
    supports_typhoon = True

    def __init__(
        self,
        api_key: str | None = None,
        geo_base_url: str | None = None,
        api_base_url: str | None = None,
        timeout: int | None = None,
    ):
        super().__init__(timeout=timeout or settings.WEATHER_REQUEST_TIMEOUT)
        self.api_key = (api_key or settings.QWEATHER_API_KEY).strip()
        self.geo_base_url = (geo_base_url or settings.QWEATHER_GEO_BASE_URL).rstrip("/")
        self.api_base_url = (api_base_url or settings.QWEATHER_API_BASE_URL).rstrip("/")
        # 缓存当前 Host 不支持的可选能力路径，避免每次查询都重复打 404/400 日志。
        self._disabled_optional_paths: set[str] = set()

    def get_daily_weather_report(self, region: str) -> dict[str, Any]:
        if not self.api_key:
            raise WeatherServiceError("未配置和风天气 QWEATHER_API_KEY。")

        target_region = (region or settings.DEFAULT_WEATHER_REGION).strip()
        if not target_region:
            raise WeatherServiceError("天气查询地区不能为空。")

        locations = self._lookup_locations(target_region)
        if not locations:
            raise WeatherServiceError(f"未找到地区“{target_region}”对应的位置编码。")

        location = self._normalize_location_item(locations[0], match_count=len(locations))
        hourly = self._fetch_hourly_weather(location["id"])
        warnings = self._fetch_warning(location)
        typhoon = self._fetch_typhoon(location, warnings)

        notices: list[str] = []
        if location.get("match_count", 0) > 1:
            notices.append(f"地区“{target_region}”存在多个候选，当前使用首个匹配结果：{location.get('display_name')}")

        return self._build_report(
            region=target_region,
            location=location,
            hourly=hourly,
            warnings=warnings,
            typhoon=typhoon,
            notices=notices,
        )

    def search_locations(self, keyword: str) -> list[dict[str, Any]]:
        target_keyword = (keyword or "").strip()
        if not target_keyword:
            return []
        locations = self._lookup_locations(target_keyword)
        return [
            self._normalize_location_item(item, match_count=len(locations))
            for item in locations
        ]

    def _qweather_request_json(
        self,
        path: str,
        *,
        base_url: str,
        params: dict[str, Any] | None = None,
        optional: bool = False,
    ) -> dict[str, Any]:
        # ?????????????API KEY ??????? `X-QW-Api-Key` ???
        # ????? key ?? query string?????
        # 1. ??????????
        # 2. ?? API Key ??? URL ????
        # 3. ?????? JWT ????????????????
        payload = self._request_json(
            f"{base_url}/{path.lstrip('/')}",
            params=params,
            headers={"X-QW-Api-Key": self.api_key},
            optional=optional,
        )
        if not payload:
            return {}
        code = str(payload.get("code", ""))
        if code and code not in {"200", "204"}:
            if optional:
                logger.warning(
                    "Optional qweather endpoint returned business code %s: %s",
                    code,
                    path,
                )
                return {}
            raise WeatherServiceError(f"{self.provider_label} ???????{code}")
        return payload

    def _lookup_locations(self, keyword: str) -> list[dict[str, Any]]:
        # ??????????GeoAPI ????????? /geo/v2/city/lookup?
        # ??????????????????????????
        candidate_paths = [
            "/geo/v2/city/lookup",
            "/v2/city/lookup",
        ]
        last_error = None
        for path in candidate_paths:
            try:
                data = self._qweather_request_json(
                    path,
                    base_url=self.geo_base_url,
                    params={"location": keyword, "number": 8, "lang": "zh"},
                    optional=path != candidate_paths[0],
                )
                locations = data.get("location") or []
                if locations:
                    return locations
            except WeatherServiceError as exc:
                last_error = exc
                logger.warning("QWeather location lookup path failed: path=%s keyword=%s error=%s", path, keyword, exc)
        if last_error:
            raise last_error
        return []

    def _normalize_location_item(self, location: dict[str, Any], match_count: int) -> dict[str, Any]:
        normalized = {
            "id": location.get("id"),
            "name": location.get("name"),
            "adm1": location.get("adm1"),
            "adm2": location.get("adm2"),
            "country": location.get("country"),
            "lat": location.get("lat"),
            "lon": location.get("lon"),
            "tz": location.get("tz"),
            "match_count": match_count,
        }
        normalized["display_name"] = self._location_display_name(normalized)
        return normalized

    def _fetch_hourly_weather(self, location_id: str) -> list[dict[str, Any]]:
        today_str = self._today_str()
        candidates = ["/v7/weather/24h", "/v7/weather/72h", "/v7/weather/168h"]
        for path in candidates:
            data = self._qweather_request_json(
                path,
                base_url=self.api_base_url,
                params={"location": location_id, "lang": "zh"},
                optional=path != "/v7/weather/24h",
            )
            hours = data.get("hourly") or []
            if not hours:
                continue
            normalized = [self._normalize_hourly_item(item) for item in hours]
            today_items = [item for item in normalized if (item.get("fxTime") or "").startswith(today_str)]
            return today_items or normalized[:24]
        raise WeatherServiceError("和风天气未返回逐小时天气数据。")

    def _fetch_warning(self, location: dict[str, Any]) -> list[dict[str, Any]]:
        # ???????????????????????????? lat/lon?
        latitude = location.get("lat")
        longitude = location.get("lon")
        if not latitude or not longitude:
            return []
        data = self._qweather_request_json(
            f"/weatheralert/v1/current/{latitude}/{longitude}",
            base_url=self.api_base_url,
            params={"lang": "zh", "localTime": "true"},
            optional=True,
        )
        warnings = data.get("warning") or data.get("warnings") or data.get("alerts") or []
        return [
            {
                "id": item.get("id") or item.get("warningId"),
                "title": item.get("title") or item.get("message") or item.get("headline"),
                "text": item.get("text") or item.get("message") or item.get("title"),
                "type": item.get("typeName") or item.get("type") or item.get("warningType") or (item.get("messageType") or {}).get("code"),
                "level": item.get("level") or item.get("severity") or (item.get("severity") or {}).get("color"),
                "pubTime": item.get("pubTime") or item.get("publishTime") or item.get("issuedTime"),
            }
            for item in warnings
        ]

    def _fetch_typhoon(self, location: dict[str, Any], warnings: list[dict[str, Any]]) -> dict[str, Any]:
        """获取当前日期前后一周内的台风数据。"""

        storm_list = self._fetch_typhoon_list()
        normalized_storms = [self._normalize_typhoon_item(storm) for storm in storm_list]
        week_storms = [item for item in normalized_storms if item.get("has_week_data")][:5]
        typhoon_alerts = [
            item
            for item in warnings
            if "台风" in ((item.get("title") or "") + (item.get("text") or ""))
        ]

        if week_storms:
            names = "、".join(item["name"] for item in week_storms if item.get("name"))
            summary = f"当前日期前后一周内监测到 {len(week_storms)} 个台风：{names}"
        else:
            summary = "当前日期前后一周内没有台风"

        return {
            "has_active": bool(week_storms),
            "summary": summary,
            "alerts": typhoon_alerts,
            "active": week_storms,
            "provider_supported": True,
            "window_days": 14,
        }

    def _fetch_typhoon_list(self) -> list[dict[str, Any]]:
        """获取西北太平洋流域台风列表。"""

        path = "/v7/tropical/storm-list"
        if path in self._disabled_optional_paths:
            return []

        years = [str(self._now().year), str(self._now().year - 1)]
        merged: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for year in years:
            data = self._qweather_request_json(
                path,
                base_url=self.api_base_url,
                params={"basin": "NP", "year": year, "lang": "zh"},
                optional=True,
            )
            if not data:
                continue
            storms = self._extract_array(data, ["storm", "storms", "list", "data"])
            for storm in storms:
                storm_id = str(storm.get("id") or storm.get("stormid") or storm.get("stormId") or "")
                if storm_id and storm_id in seen_ids:
                    continue
                if storm_id:
                    seen_ids.add(storm_id)
                merged.append(storm)
        if not merged:
            self._disabled_optional_paths.add(path)
        return merged

    def _fetch_typhoon_forecast(self, storm_id: str) -> list[dict[str, Any]]:
        """?????????????"""

        if not storm_id:
            return []
        path = "/v7/tropical/storm-forecast"
        if path in self._disabled_optional_paths:
            return []
        data = self._qweather_request_json(
            path,
            base_url=self.api_base_url,
            params={"stormid": storm_id, "lang": "zh"},
            optional=True,
        )
        if not data:
            self._disabled_optional_paths.add(path)
            return []
        forecast_items = self._collect_typhoon_points(data, time_keys={"fxTime", "time", "date"})
        return [self._normalize_forecast_item(item) for item in forecast_items[:24]]

    def _fetch_typhoon_track(self, storm_id: str) -> list[dict[str, Any]]:
        """??????????????? now ??????????"""

        if not storm_id:
            return []
        path = "/v7/tropical/storm-track"
        if path in self._disabled_optional_paths:
            return []
        data = self._qweather_request_json(
            path,
            base_url=self.api_base_url,
            params={"stormid": storm_id, "lang": "zh"},
            optional=True,
        )
        if not data:
            self._disabled_optional_paths.add(path)
            return []

        track_items = []
        now_item = data.get("now")
        if isinstance(now_item, dict):
            track_items.append(
                self._normalize_track_item(
                    {
                        "time": now_item.get("pubTime"),
                        "lat": now_item.get("lat"),
                        "lon": now_item.get("lon"),
                        "type": now_item.get("type"),
                        "pressure": now_item.get("pressure"),
                        "windSpeed": now_item.get("windSpeed"),
                        "moveSpeed": now_item.get("moveSpeed"),
                        "moveDir": now_item.get("moveDir"),
                        "move360": now_item.get("move360"),
                        "windRadius30": now_item.get("windRadius30"),
                        "windRadius50": now_item.get("windRadius50"),
                        "windRadius64": now_item.get("windRadius64"),
                        "text": "??????",
                    }
                )
            )

        raw_track_items = self._collect_typhoon_points(data, time_keys={"fxTime", "time", "obsTime", "pubTime"})
        track_items.extend(self._normalize_track_item(item) for item in raw_track_items[:72])

        deduplicated_items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in track_items:
            dedupe_key = f"{item.get('fxTime') or ''}|{item.get('lat') or ''}|{item.get('lon') or ''}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            deduplicated_items.append(item)
        deduplicated_items.sort(
            key=lambda item: self._parse_typhoon_point_time(item.get("fxTime"))
            or self._now().replace(tzinfo=None)
        )
        return deduplicated_items

    def _normalize_typhoon_item(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        storm_id = str(raw_item.get("id") or raw_item.get("stormid") or raw_item.get("stormId") or "")
        track = self._filter_typhoon_points_by_window(self._fetch_typhoon_track(storm_id), past_days=7, future_days=0)
        forecast = self._filter_typhoon_points_by_window(self._fetch_typhoon_forecast(storm_id), past_days=0, future_days=7)
        current_point = self._pick_current_typhoon_point(track)
        return {
            "id": storm_id,
            "name": raw_item.get("name") or raw_item.get("stormName") or raw_item.get("ename") or "未命名台风",
            "level": raw_item.get("level") or raw_item.get("intensity") or raw_item.get("category"),
            "lat": raw_item.get("lat") or raw_item.get("latitude"),
            "lon": raw_item.get("lon") or raw_item.get("longitude"),
            "pressure": raw_item.get("pressure"),
            "windSpeed": raw_item.get("windSpeed") or raw_item.get("wind"),
            "moveDir": raw_item.get("moveDir") or raw_item.get("direction"),
            "moveSpeed": raw_item.get("moveSpeed") or raw_item.get("speed"),
            "track": track,
            "forecast": forecast,
            "current_point": current_point,
            "has_week_data": bool(track or forecast or current_point),
        }

    def _collect_typhoon_points(self, payload: Any, *, time_keys: set[str]) -> list[dict[str, Any]]:
        """?????????"""

        collected: list[dict[str, Any]] = []

        def walk(node: Any) -> None:
            if isinstance(node, list):
                for item in node:
                    walk(item)
                return
            if not isinstance(node, dict):
                return

            has_time = any(node.get(key) for key in time_keys)
            has_lat = node.get("lat") or node.get("latitude")
            has_lon = node.get("lon") or node.get("longitude")
            if has_time and has_lat and has_lon:
                collected.append(node)

            for value in node.values():
                walk(value)

        walk(payload)

        unique_items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in collected:
            time_value = (
                item.get("fxTime")
                or item.get("time")
                or item.get("obsTime")
                or item.get("pubTime")
                or item.get("date")
                or ""
            )
            lat_value = item.get("lat") or item.get("latitude") or ""
            lon_value = item.get("lon") or item.get("longitude") or ""
            key = f"{time_value}|{lat_value}|{lon_value}"
            if key in seen:
                continue
            seen.add(key)
            unique_items.append(item)

        unique_items.sort(
            key=lambda item: self._parse_typhoon_point_time(
                item.get("fxTime")
                or item.get("time")
                or item.get("obsTime")
                or item.get("pubTime")
                or item.get("date")
            )
            or self._now().replace(tzinfo=None)
        )
        return unique_items

    def _filter_typhoon_points_by_window(self, points: list[dict[str, Any]], *, past_days: int, future_days: int) -> list[dict[str, Any]]:
        """按一周时间窗口过滤台风点位。

        这里把台风实况和预报统一裁剪到当前时间附近：
        - 实况路径：保留最近 past_days 天。
        - 未来预报：保留未来 future_days 天。
        """

        now = self._now().replace(tzinfo=None)
        start_time = now - timedelta(days=past_days)
        end_time = now + timedelta(days=future_days)
        filtered: list[dict[str, Any]] = []
        for item in points or []:
            point_time = self._parse_typhoon_point_time(item.get("fxTime"))
            if point_time is None:
                continue
            if start_time <= point_time <= end_time:
                filtered.append(item)
        filtered.sort(key=lambda item: self._parse_typhoon_point_time(item.get("fxTime")) or now)
        return filtered

    def _pick_current_typhoon_point(self, track: list[dict[str, Any]]) -> dict[str, Any] | None:
        """从实况路径中挑出最接近当前时间且不晚于当前时间的点。"""

        now = self._now().replace(tzinfo=None)
        candidates = []
        for item in track or []:
            point_time = self._parse_typhoon_point_time(item.get("fxTime"))
            if point_time is None:
                continue
            if point_time <= now:
                candidates.append((point_time, item))
        if not candidates:
            return None
        candidates.sort(key=lambda pair: pair[0])
        return candidates[-1][1]

    @staticmethod
    def _parse_typhoon_point_time(value: Any) -> datetime | None:
        if not value:
            return None
        text = str(value).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except Exception:
            try:
                parsed = datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")
            except Exception:
                return None
        if parsed.tzinfo:
            parsed = parsed.astimezone(SHANGHAI_TZ).replace(tzinfo=None)
        return parsed

    @staticmethod
    def _normalize_hourly_item(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "fxTime": item.get("fxTime"),
            "temp": item.get("temp"),
            "text": item.get("text"),
            "windDir": item.get("windDir"),
            "windScale": item.get("windScale"),
            "humidity": item.get("humidity"),
            "precip": item.get("precip"),
            "pop": item.get("pop"),
        }

    @staticmethod
    def _normalize_forecast_item(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "fxTime": item.get("fxTime") or item.get("time") or item.get("date"),
            "text": item.get("text") or item.get("description"),
            "windSpeed": item.get("windSpeed") or item.get("wind"),
            "pressure": item.get("pressure"),
            "lat": item.get("lat") or item.get("latitude"),
            "lon": item.get("lon") or item.get("longitude"),
        }

    @staticmethod
    def _normalize_track_item(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "fxTime": item.get("fxTime") or item.get("time") or item.get("obsTime") or item.get("pubTime"),
            "text": item.get("text") or item.get("description") or item.get("level"),
            "windSpeed": item.get("windSpeed") or item.get("wind"),
            "pressure": item.get("pressure"),
            "lat": item.get("lat") or item.get("latitude"),
            "lon": item.get("lon") or item.get("longitude"),
        }

    @staticmethod
    def _extract_array(data: dict[str, Any], keys: list[str]) -> list[dict[str, Any]]:
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                for nested in value.values():
                    if isinstance(nested, list) and nested:
                        return nested
        return []


class OpenMeteoService(BaseWeatherProvider):
    """Open-Meteo 免费天气源。

    采用它作为免费兜底的原因：
    1. 无需 API Key，适合在主源失败时继续提供天气能力。
    2. 提供逐小时天气和地理编码，足够支撑天气页核心展示。
    3. 不具备完整的国内台风与预警能力，因此只作为天气兜底。
    """

    provider_name = "openmeteo"
    provider_label = "Open-Meteo"
    supports_warning = False
    supports_typhoon = False

    def __init__(
        self,
        api_base_url: str | None = None,
        geo_base_url: str | None = None,
        timeout: int | None = None,
    ):
        super().__init__(timeout=timeout or settings.WEATHER_REQUEST_TIMEOUT)
        self.api_base_url = (api_base_url or settings.OPEN_METEO_API_BASE_URL).rstrip("/")
        self.geo_base_url = (geo_base_url or settings.OPEN_METEO_GEO_BASE_URL).rstrip("/")

    def get_daily_weather_report(self, region: str) -> dict[str, Any]:
        target_region = (region or settings.DEFAULT_WEATHER_REGION).strip()
        if not target_region:
            raise WeatherServiceError("天气查询地区不能为空。")

        results = self._lookup_locations(target_region)
        if not results:
            raise WeatherServiceError(f"免费备用天气源未找到地区“{target_region}”。")

        location = self._normalize_location_item(results[0], match_count=len(results))
        hourly = self._fetch_hourly_weather(location)
        notices = [
            "当前使用免费备用天气源，不提供国内台风路径和本地气象预警。",
        ]
        if location.get("match_count", 0) > 1:
            notices.append(f"地区“{target_region}”存在多个候选，当前使用首个匹配结果：{location.get('display_name')}")
        typhoon = {
            "has_active": False,
            "summary": "当前使用免费备用天气源，暂不提供台风路径和未来预测，请配置和风天气 Key 获取完整能力。",
            "alerts": [],
            "active": [],
            "provider_supported": False,
        }
        return self._build_report(
            region=target_region,
            location=location,
            hourly=hourly,
            warnings=[],
            typhoon=typhoon,
            notices=notices,
        )

    def search_locations(self, keyword: str) -> list[dict[str, Any]]:
        target_keyword = (keyword or "").strip()
        if not target_keyword:
            return []
        results = self._lookup_locations(target_keyword)
        return [self._normalize_location_item(item, match_count=len(results)) for item in results]

    def _lookup_locations(self, keyword: str) -> list[dict[str, Any]]:
        data = self._request_json(
            f"{self.geo_base_url}/v1/search",
            params={
                "name": keyword,
                "count": 8,
                "language": "zh",
                "format": "json",
            },
        )
        return data.get("results") or []

    def _normalize_location_item(self, location: dict[str, Any], match_count: int) -> dict[str, Any]:
        normalized = {
            "id": str(location.get("id") or ""),
            "name": location.get("name"),
            "adm1": location.get("admin1"),
            "adm2": location.get("admin2"),
            "country": location.get("country"),
            "lat": location.get("latitude"),
            "lon": location.get("longitude"),
            "tz": location.get("timezone") or "Asia/Shanghai",
            "match_count": match_count,
        }
        normalized["display_name"] = self._location_display_name(normalized)
        return normalized

    def _fetch_hourly_weather(self, location: dict[str, Any]) -> list[dict[str, Any]]:
        data = self._request_json(
            f"{self.api_base_url}/v1/forecast",
            params={
                "latitude": location.get("lat"),
                "longitude": location.get("lon"),
                "forecast_days": 1,
                "timezone": "Asia/Shanghai",
                "hourly": ",".join(
                    [
                        "temperature_2m",
                        "relative_humidity_2m",
                        "weather_code",
                        "wind_speed_10m",
                        "wind_direction_10m",
                        "precipitation",
                        "precipitation_probability",
                    ]
                ),
            },
        )
        hourly = data.get("hourly") or {}
        times = hourly.get("time") or []
        rows: list[dict[str, Any]] = []
        for index, fx_time in enumerate(times):
            rows.append(
                {
                    "fxTime": f"{fx_time}:00+08:00" if len(fx_time) == 13 else fx_time,
                    "temp": self._get_hourly_value(hourly, "temperature_2m", index),
                    "text": self._weather_code_to_text(self._get_hourly_value(hourly, "weather_code", index)),
                    "windDir": self._wind_direction_from_degree(self._get_hourly_value(hourly, "wind_direction_10m", index)),
                    "windScale": self._kmh_to_scale(self._get_hourly_value(hourly, "wind_speed_10m", index)),
                    "humidity": self._get_hourly_value(hourly, "relative_humidity_2m", index),
                    "precip": self._get_hourly_value(hourly, "precipitation", index),
                    "pop": self._get_hourly_value(hourly, "precipitation_probability", index),
                }
            )
        if not rows:
            raise WeatherServiceError("免费备用天气源未返回逐小时天气数据。")
        return rows

    @staticmethod
    def _get_hourly_value(hourly: dict[str, Any], key: str, index: int) -> Any:
        values = hourly.get(key) or []
        if index >= len(values):
            return None
        return values[index]

    @staticmethod
    def _weather_code_to_text(code: Any) -> str:
        mapping = {
            0: "晴",
            1: "大部晴朗",
            2: "局部多云",
            3: "阴",
            45: "雾",
            48: "冻雾",
            51: "小毛毛雨",
            53: "毛毛雨",
            55: "强毛毛雨",
            56: "冻毛毛雨",
            57: "强冻毛毛雨",
            61: "小雨",
            63: "中雨",
            65: "大雨",
            66: "冻雨",
            67: "强冻雨",
            71: "小雪",
            73: "中雪",
            75: "大雪",
            77: "冰粒",
            80: "阵雨",
            81: "强阵雨",
            82: "暴雨阵雨",
            85: "阵雪",
            86: "强阵雪",
            95: "雷暴",
            96: "雷暴夹小冰雹",
            99: "强雷暴夹大冰雹",
        }
        parsed = BaseWeatherProvider._safe_int(code)
        return mapping.get(parsed, "未知天气")


class WeatherService:
    """天气服务门面。

    技术原理：
    1. 通过门面模式统一天气查询与地区联想入口。
    2. 在同一处封装主源、备用源和自动降级策略。
    3. 前端和通知模块无需知道底层具体是哪一家天气供应商。
    """

    def __init__(self):
        self.qweather = QWeatherService()
        self.openmeteo = OpenMeteoService()

    def get_daily_weather_report(self, region: str) -> dict[str, Any]:
        errors: list[str] = []
        for provider, mode in self._provider_chain():
            try:
                report = provider.get_daily_weather_report(region)
                report.setdefault("provider", {})
                report["provider"]["mode"] = mode
                if errors:
                    report.setdefault("notices", []).append("已自动切换备用天气源，原因：" + "；".join(errors))
                return report
            except WeatherServiceError as exc:
                logger.warning(
                    "Weather provider failed: provider=%s region=%s error=%s",
                    provider.provider_name,
                    region,
                    exc,
                )
                errors.append(f"{provider.provider_label}：{exc}")
        raise WeatherServiceError("所有天气供应商均调用失败：" + "；".join(errors))

    def search_locations(self, keyword: str) -> list[dict[str, Any]]:
        errors: list[str] = []
        for provider, _mode in self._provider_chain():
            try:
                suggestions = provider.search_locations(keyword)
                if suggestions:
                    return suggestions
            except WeatherServiceError as exc:
                logger.warning(
                    "Weather location search failed: provider=%s keyword=%s error=%s",
                    provider.provider_name,
                    keyword,
                    exc,
                )
                errors.append(f"{provider.provider_label}：{exc}")
        if errors:
            raise WeatherServiceError("地区联想查询失败：" + "；".join(errors))
        return []

    def _provider_chain(self) -> list[tuple[BaseWeatherProvider, str]]:
        mode = (settings.WEATHER_PROVIDER or "auto").strip().lower()
        if mode == "qweather":
            return [(self.qweather, "primary")]
        if mode == "openmeteo":
            return [(self.openmeteo, "primary")]
        if settings.QWEATHER_API_KEY.strip():
            return [(self.qweather, "primary"), (self.openmeteo, "fallback")]
        return [(self.openmeteo, "primary")]


weather_service = WeatherService()
