"""天气服务门面导出。

保持模块边界稳定：后续如果天气服务实现继续拆分，只需要改这个门面文件。
"""

from app.services.weather_service import WeatherServiceError, weather_service

__all__ = ["WeatherServiceError", "weather_service"]

